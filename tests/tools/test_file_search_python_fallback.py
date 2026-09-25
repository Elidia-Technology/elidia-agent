"""Tests for the pure-Python file/content search fallback.

The fallback (tools/file_operations.py) triggers on local backends when
neither ripgrep/find (file search) nor ripgrep/grep (content search) is
available — e.g. Windows without Git Bash.  These tests simulate that by
stubbing ``_has_command`` to False and ``_is_local_backend`` to True, then
assert the local-tree walk returns correct results.
"""

from unittest.mock import MagicMock

import os
import pytest

from tools.file_operations import ShellFileOperations


def _make_ops(monkeypatch, *, local=True):
    env = MagicMock()
    env.cwd = "/"
    ops = ShellFileOperations(env)
    # No external search binaries available.
    monkeypatch.setattr(ops, "_has_command", lambda cmd: False)
    # Force the local-backend branch (the real env is a mock, not a
    # LocalEnvironment, so _is_local_backend() would otherwise be False).
    monkeypatch.setattr(ops, "_is_local_backend", lambda: local)
    return ops


class TestSearchFilesPythonFallback:
    def test_matches_by_substring(self, tmp_path, monkeypatch):
        (tmp_path / "hello_world.py").write_text("x")
        (tmp_path / "goodbye.py").write_text("x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "hello_again.txt").write_text("x")

        ops = _make_ops(monkeypatch)
        result = ops._search_files("hello", str(tmp_path), limit=50, offset=0)

        assert result.error is None
        got = {os.path.basename(p) for p in result.files}
        assert got == {"hello_world.py", "hello_again.txt"}

    def test_matches_by_glob(self, tmp_path, monkeypatch):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.txt").write_text("x")

        ops = _make_ops(monkeypatch)
        result = ops._search_files("*.py", str(tmp_path), limit=50, offset=0)

        assert result.error is None
        assert result.files == [str(tmp_path / "a.py")]

    def test_skips_hidden_directories(self, tmp_path, monkeypatch):
        (tmp_path / "visible.log").write_text("x")
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "secret.log").write_text("x")

        ops = _make_ops(monkeypatch)
        result = ops._search_files("*.log", str(tmp_path), limit=50, offset=0)

        assert result.error is None
        assert result.files == [str(tmp_path / "visible.log")]

    def test_sorts_by_mtime_newest_first(self, tmp_path, monkeypatch):
        older = tmp_path / "older.log"
        newer = tmp_path / "newer.log"
        older.write_text("x")
        newer.write_text("x")
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))

        ops = _make_ops(monkeypatch)
        result = ops._search_files("*.log", str(tmp_path), limit=50, offset=0)

        assert result.error is None
        assert result.files[0] == str(newer)
        assert result.files[1] == str(older)

    def test_nonexistent_path_returns_error(self, tmp_path, monkeypatch):
        ops = _make_ops(monkeypatch)
        result = ops._search_files("x", str(tmp_path / "missing"), limit=50, offset=0)
        assert result.error is not None
        assert result.total_count == 0

    def test_remote_backend_keeps_actionable_error(self, tmp_path, monkeypatch):
        ops = _make_ops(monkeypatch, local=False)
        result = ops._search_files("x", str(tmp_path), limit=50, offset=0)
        assert result.error is not None
        assert "ripgrep" in result.error or "rg" in result.error


class TestSearchContentPythonFallback:
    def _write(self, tmp_path):
        (tmp_path / "a.py").write_text("def foo():\n    return 42\n")
        (tmp_path / "b.txt").write_text("no match here\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.py").write_text("foo bar\n")

    def test_content_matches(self, tmp_path, monkeypatch):
        self._write(tmp_path)
        ops = _make_ops(monkeypatch)
        result = ops._search_content("foo", str(tmp_path), None, 50, 0, "content", 0)

        assert result.error is None
        paths = {m.path for m in result.matches}
        assert str(tmp_path / "a.py") in paths
        assert str(tmp_path / "sub" / "c.py") in paths
        assert str(tmp_path / "b.txt") not in paths

    def test_files_only_mode(self, tmp_path, monkeypatch):
        self._write(tmp_path)
        ops = _make_ops(monkeypatch)
        result = ops._search_content("foo", str(tmp_path), None, 50, 0, "files_only", 0)

        assert result.error is None
        got = set(result.files)
        assert str(tmp_path / "a.py") in got
        assert str(tmp_path / "sub" / "c.py") in got
        assert str(tmp_path / "b.txt") not in got

    def test_count_mode(self, tmp_path, monkeypatch):
        self._write(tmp_path)
        ops = _make_ops(monkeypatch)
        result = ops._search_content("foo", str(tmp_path), None, 50, 0, "count", 0)

        assert result.error is None
        assert result.counts[str(tmp_path / "a.py")] == 1
        assert result.counts[str(tmp_path / "sub" / "c.py")] == 1

    def test_skips_binary_files(self, tmp_path, monkeypatch):
        (tmp_path / "blob.bin").write_bytes(b"foo\x00\x01\x02")
        (tmp_path / "ok.txt").write_text("foo here\n")

        ops = _make_ops(monkeypatch)
        result = ops._search_content("foo", str(tmp_path), None, 50, 0, "content", 0)

        assert result.error is None
        paths = {m.path for m in result.matches}
        assert str(tmp_path / "blob.bin") not in paths
        assert str(tmp_path / "ok.txt") in paths

    def test_invalid_regex_returns_error(self, tmp_path, monkeypatch):
        (tmp_path / "a.txt").write_text("x\n")
        ops = _make_ops(monkeypatch)
        result = ops._search_content("([", str(tmp_path), None, 50, 0, "content", 0)
        assert result.error is not None

    def test_remote_backend_keeps_actionable_error(self, tmp_path, monkeypatch):
        (tmp_path / "a.txt").write_text("foo\n")
        ops = _make_ops(monkeypatch, local=False)
        result = ops._search_content("foo", str(tmp_path), None, 50, 0, "content", 0)
        assert result.error is not None
        assert "ripgrep" in result.error or "grep" in result.error
