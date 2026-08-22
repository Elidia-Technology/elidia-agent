"""Regression tests for _apply_profile_override ELIDIA_HOME guard (issue #22502).

When ELIDIA_HOME is set to the elidia root (e.g. systemd hardcodes
ELIDIA_HOME=/root/.elidia), _apply_profile_override must still read
active_profile and update ELIDIA_HOME to the profile directory.

When ELIDIA_HOME is already a profile directory (.../profiles/<name>),
_apply_profile_override must trust it and return without re-reading
active_profile (child-process inheritance contract).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path



def _run_apply_profile_override(
    tmp_path, monkeypatch, *, elidia_home: str | None, active_profile: str | None,
    argv: list[str] | None = None,
):
    """Run _apply_profile_override in isolation.

    Returns the value of os.environ["ELIDIA_HOME"] after the call,
    or None if unset.
    """
    elidia_root = tmp_path / ".elidia"
    elidia_root.mkdir(parents=True, exist_ok=True)

    if active_profile is not None:
        (elidia_root / "active_profile").write_text(active_profile)

    if active_profile and active_profile != "default":
        (elidia_root / "profiles" / active_profile).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if elidia_home is not None:
        monkeypatch.setenv("ELIDIA_HOME", elidia_home)
    else:
        monkeypatch.delenv("ELIDIA_HOME", raising=False)

    monkeypatch.setattr(sys, "argv", argv or ["elidia", "gateway", "start"])

    from elidia_cli.main import _apply_profile_override
    _apply_profile_override()

    return os.environ.get("ELIDIA_HOME")


class TestApplyProfileOverrideElidiaHomeGuard:
    """Regression guard for issue #22502.

    Verifies that ELIDIA_HOME pointing to the elidia root does NOT suppress
    the active_profile check, while ELIDIA_HOME already pointing to a
    profile directory IS trusted as-is.
    """

    def test_elidia_home_at_root_with_active_profile_is_redirected(
        self, tmp_path, monkeypatch
    ):
        """ELIDIA_HOME=/root/.elidia + active_profile=coder must redirect
        ELIDIA_HOME to .../profiles/coder.

        Bug scenario from #22502: systemd sets ELIDIA_HOME to the elidia root
        and the user switches to a profile via `elidia profile use`.
        Before the fix, the guard returned early and active_profile was ignored.
        """
        elidia_root = tmp_path / ".elidia"
        elidia_root.mkdir(parents=True, exist_ok=True)

        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            elidia_home=str(elidia_root),
            active_profile="coder",
        )

        assert result is not None, "ELIDIA_HOME must be set after profile redirect"
        assert "profiles" in result, (
            f"Expected ELIDIA_HOME to point into profiles/ dir, got: {result!r}"
        )
        assert result.endswith("coder"), (
            f"Expected ELIDIA_HOME to end with 'coder', got: {result!r}"
        )

    def test_elidia_home_already_profile_dir_is_trusted(self, tmp_path, monkeypatch):
        """ELIDIA_HOME=.../profiles/coder must not be overridden even when
        active_profile says something different.

        Preserves the child-process inheritance contract: a subprocess spawned
        with ELIDIA_HOME already set to a specific profile must stay in that
        profile.
        """
        elidia_root = tmp_path / ".elidia"
        profile_dir = elidia_root / "profiles" / "coder"
        profile_dir.mkdir(parents=True, exist_ok=True)

        (elidia_root / "active_profile").write_text("other")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("ELIDIA_HOME", str(profile_dir))
        monkeypatch.setattr(sys, "argv", ["elidia", "gateway", "start"])

        from elidia_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("ELIDIA_HOME") == str(profile_dir), (
            "ELIDIA_HOME must remain unchanged when already pointing to a profile dir"
        )

    def test_elidia_home_unset_reads_active_profile(self, tmp_path, monkeypatch):
        """Classic case: ELIDIA_HOME unset + active_profile=coder must set
        ELIDIA_HOME to the profile directory (existing behaviour must not regress).
        """
        result = _run_apply_profile_override(
            tmp_path,
            monkeypatch,
            elidia_home=None,
            active_profile="coder",
        )

        assert result is not None
        assert "coder" in result

    def test_elidia_home_unset_default_profile_no_redirect(self, tmp_path, monkeypatch):
        """active_profile=default must not redirect ELIDIA_HOME."""
        elidia_root = tmp_path / ".elidia"
        elidia_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("ELIDIA_HOME", raising=False)
        monkeypatch.setattr(sys, "argv", ["elidia", "gateway", "start"])
        (elidia_root / "active_profile").write_text("default")

        from elidia_cli.main import _apply_profile_override
        _apply_profile_override()

        assert os.environ.get("ELIDIA_HOME") is None
