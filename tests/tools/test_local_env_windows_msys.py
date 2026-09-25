"""Tests for the Windows / Git Bash MSYS-path normalization in
``LocalEnvironment``.

Background
----------
On Windows, ``pwd -P`` inside Git Bash emits paths like
``/c/Users/NVIDIA``. ``subprocess.Popen(..., cwd=...)`` only accepts
native Windows paths (``C:\\Users\\NVIDIA``), and the validation done
by ``_resolve_safe_cwd`` was also checking the MSYS form against
``os.path.isdir``, which returns ``False`` on Windows. The combined
effect was a warning logged on every single terminal call:

    LocalEnvironment cwd '/c/Users/NVIDIA' is missing on disk;
    falling back to '/' so terminal commands keep working.

These tests fake the Windows env on Linux CI by patching ``_IS_WINDOWS``
and ``os.path.isdir`` so the MSYS path tests as "missing" exactly like
on the real OS.
"""

import os

from unittest.mock import patch

import pytest

from tools.environments import local as local_mod
from tools.environments.local import (
    LocalEnvironment,
    _find_bash,
    _is_wsl_bash_stub,
    _msys_to_windows_path,
    _resolve_safe_cwd,
)


# ---------------------------------------------------------------------------
# _msys_to_windows_path — pure-function unit tests
# ---------------------------------------------------------------------------

class TestMsysToWindowsPath:
    def test_noop_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", False)
        # On a non-Windows host the function must never rewrite the path
        # — POSIX-style paths are real paths there.
        assert _msys_to_windows_path("/c/Users/NVIDIA") == "/c/Users/NVIDIA"
        assert _msys_to_windows_path("/home/teknium") == "/home/teknium"

    def test_translates_drive_path(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        assert _msys_to_windows_path("/c/Users/NVIDIA") == r"C:\Users\NVIDIA"
        assert _msys_to_windows_path("/d/Projects/foo bar") == r"D:\Projects\foo bar"

    def test_translates_bare_drive_root(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        # Bare "/c" alone should resolve to the drive root.
        assert _msys_to_windows_path("/c") == "C:\\"
        # Trailing slash on the drive letter is also a root.
        assert _msys_to_windows_path("/c/") == "C:\\"

    def test_idempotent_on_already_windows_path(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        assert _msys_to_windows_path(r"C:\Users\NVIDIA") == r"C:\Users\NVIDIA"

    def test_does_not_translate_multi_char_first_segment(self, monkeypatch):
        """``/tmp/foo`` and ``/home/x`` must NOT be misread as drive paths
        just because they start with ``/`` and a single letter — the regex
        only matches when the first segment is exactly one character."""
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        assert _msys_to_windows_path("/tmp/foo") == "/tmp/foo"
        assert _msys_to_windows_path("/home/x") == "/home/x"

    def test_empty_string(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        assert _msys_to_windows_path("") == ""


# ---------------------------------------------------------------------------
# _is_wsl_bash_stub — WindowsApps WSL alias detection
# ---------------------------------------------------------------------------

class TestIsWslBashStub:
    def test_detects_windowsapps_stub(self):
        stub = r"C:\Users\ADMIN\AppData\Local\Microsoft\WindowsApps\bash.exe"
        assert _is_wsl_bash_stub(stub) is True
        # Forward-slash form (e.g. from shutil.which on a mixed-separator PATH)
        assert _is_wsl_bash_stub(stub.replace("\\", "/")) is True

    def test_rejects_real_git_bash(self):
        assert _is_wsl_bash_stub(r"C:\Program Files\Git\bin\bash.exe") is False
        assert _is_wsl_bash_stub(r"C:\Program Files\Git\usr\bin\bash.exe") is False

    def test_rejects_empty_and_other_bash(self):
        assert _is_wsl_bash_stub("") is False
        assert _is_wsl_bash_stub(None) is False
        assert _is_wsl_bash_stub(r"C:\msys64\usr\bin\bash.exe") is False


# ---------------------------------------------------------------------------
# _find_bash — Windows resolution must prefer real Git Bash over the WSL stub
# ---------------------------------------------------------------------------

class TestFindBashWindows:
    def test_prefers_program_files_git_over_wsl_stub(self, monkeypatch):
        r"""#3414: Git for Windows is installed but only ``Git\cmd`` is on PATH,
        so ``shutil.which("bash")`` returns the WindowsApps WSL stub. ``_find_bash``
        must probe the Program Files Git bash *before* consulting ``shutil.which``
        and return the real bash."""
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        monkeypatch.delenv("ELIDIA_GIT_BASH_PATH", raising=False)

        # Build the candidate the same way _find_bash does (os.path.join uses
        # "/" on Linux CI, "\" on Windows), so the fake isfile matches the
        # exact path the function probes.
        real_bash = os.path.join(r"C:\Program Files", "Git", "bin", "bash.exe")
        wsl_stub = r"C:\Users\ADMIN\AppData\Local\Microsoft\WindowsApps\bash.exe"

        def fake_isfile(path):
            return path == real_bash

        with patch.object(local_mod.shutil, "which", return_value=wsl_stub), \
             patch.object(local_mod.os.path, "isfile", side_effect=fake_isfile):
            assert _find_bash() == real_bash

    def test_skips_wsl_stub_and_raises_when_no_real_bash(self, monkeypatch):
        """When only the WSL stub exists (no Git Bash anywhere), ``_find_bash``
        must NOT return the stub — it must raise the actionable Git Bash error."""
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        monkeypatch.delenv("ELIDIA_GIT_BASH_PATH", raising=False)

        wsl_stub = r"C:\Users\ADMIN\AppData\Local\Microsoft\WindowsApps\bash.exe"

        with patch.object(local_mod.shutil, "which", return_value=wsl_stub), \
             patch.object(local_mod.os.path, "isfile", return_value=False):
            with pytest.raises(RuntimeError, match="Git Bash not found"):
                _find_bash()

    def test_returns_non_wsl_which_bash(self, monkeypatch):
        """A non-WSL bash found via PATH (e.g. MSYS2) is still acceptable when
        no Program Files Git exists."""
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
        monkeypatch.delenv("ELIDIA_GIT_BASH_PATH", raising=False)

        msys_bash = r"C:\msys64\usr\bin\bash.exe"

        with patch.object(local_mod.shutil, "which", return_value=msys_bash), \
             patch.object(local_mod.os.path, "isfile", return_value=False):
            assert _find_bash() == msys_bash


# ---------------------------------------------------------------------------
# _resolve_safe_cwd — Windows fast path
# ---------------------------------------------------------------------------

class TestResolveSafeCwdWindows:
    def test_msys_path_resolves_to_native_when_native_exists(
        self, monkeypatch, tmp_path,
    ):
        """The whole point of this fix: a Git Bash ``/c/Users/x`` value
        should resolve to its native equivalent if that native dir exists,
        WITHOUT falling back to the temp dir."""
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)

        # tmp_path is a real native dir on the test host. Build a fake
        # MSYS form pointing at it and prove the resolver finds it.
        native = str(tmp_path)
        # Construct a synthetic MSYS form for whatever tmp_path is.
        # On Linux CI tmp_path is /tmp/... ; the resolver shouldn't even
        # try to translate that (regex won't match), so emulate the
        # mapping by pointing the translator at the real native dir.
        with patch.object(
            local_mod, "_msys_to_windows_path", return_value=native
        ):
            assert _resolve_safe_cwd("/c/whatever") == native


# ---------------------------------------------------------------------------
# End-to-end: _update_cwd via marker file (Windows simulation)
# ---------------------------------------------------------------------------

class TestUpdateCwdWindowsMsys:
    def test_marker_file_msys_path_stored_in_native_form(
        self, monkeypatch, tmp_path,
    ):
        """When Git Bash writes ``/c/Users/x`` to the cwd marker file on
        Windows, ``_update_cwd`` must translate to native form before
        validating and storing — otherwise ``os.path.isdir`` rejects a
        perfectly real directory."""
        original = tmp_path / "starting"
        original.mkdir()

        # Fake Windows for the test
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)

        with patch.object(
            LocalEnvironment, "init_session", autospec=True, return_value=None
        ):
            env = LocalEnvironment(cwd=str(original), timeout=10)

        # Pretend Git Bash wrote an MSYS path that maps to tmp_path/"next"
        new_dir = tmp_path / "next"
        new_dir.mkdir()

        with open(env._cwd_file, "w") as f:
            f.write("/c/whatever/from/bash")

        # Translate the synthetic MSYS string to the real native dir.
        def fake_translate(p):
            if p == "/c/whatever/from/bash":
                return str(new_dir)
            return p

        with patch.object(local_mod, "_msys_to_windows_path", side_effect=fake_translate):
            env._update_cwd({"output": "", "returncode": 0})

        assert env.cwd == str(new_dir)


# ---------------------------------------------------------------------------
# End-to-end: _extract_cwd_from_output rollback when marker is invalid
# ---------------------------------------------------------------------------

class TestExtractCwdFromOutputWindowsMsys:
    def test_stale_msys_marker_does_not_clobber_cwd(self, monkeypatch, tmp_path):
        """When the cwd marker in stdout points at a non-existent path,
        ``LocalEnvironment._extract_cwd_from_output`` must roll back to
        the previous cwd instead of propagating a bad value."""
        original = tmp_path / "starting"
        original.mkdir()

        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)

        with patch.object(
            LocalEnvironment, "init_session", autospec=True, return_value=None
        ):
            env = LocalEnvironment(cwd=str(original), timeout=10)

        marker = env._cwd_marker
        result = {
            "output": f"some command output\n{marker}/c/no/such/path{marker}\n",
            "returncode": 0,
        }

        # Translation produces a path that doesn't exist on disk → rollback.
        with patch.object(
            local_mod,
            "_msys_to_windows_path",
            return_value=str(tmp_path / "definitely-does-not-exist"),
        ):
            env._extract_cwd_from_output(result)

        assert env.cwd == str(original)

    def test_valid_msys_marker_normalized_to_native(self, monkeypatch, tmp_path):
        original = tmp_path / "starting"
        original.mkdir()
        new_dir = tmp_path / "next"
        new_dir.mkdir()

        monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)

        with patch.object(
            LocalEnvironment, "init_session", autospec=True, return_value=None
        ):
            env = LocalEnvironment(cwd=str(original), timeout=10)

        marker = env._cwd_marker
        result = {
            "output": f"x\n{marker}/c/whatever{marker}\n",
            "returncode": 0,
        }

        with patch.object(local_mod, "_msys_to_windows_path", return_value=str(new_dir)):
            env._extract_cwd_from_output(result)

        assert env.cwd == str(new_dir)
