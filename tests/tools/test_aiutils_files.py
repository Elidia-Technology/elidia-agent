"""F7 — the agent's access to AiUtils file storage.

The judgements worth testing are the ones that protect the conversation and
the user:

  * a binary is offered for download, not decoded into the conversation
  * a large file is refused for `read` and pointed at `download`, because
    pulling 40 MB into context costs far more than working with it on disk
  * an upload tells the user what happens to the file — a vault file is kept,
    an ordinary one disappears in 10 days, and silence about that is worse
    than either
  * no key material is ever handled here; decryption is server-side

The SDK is substituted at the client boundary. Everything above it is the real
handler.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture()
def af():
    import tools.aiutils_files as module
    importlib.reload(module)
    return module


class _FakeFiles:
    def __init__(self, records=None, content=b"", meta=None):
        self._records = records or []
        self._content = content
        self._meta = meta or {}
        self.calls = []

    def list(self, vaulted=None, limit=50):
        self.calls.append(("list", vaulted, limit))
        if vaulted is None:
            return self._records
        return [r for r in self._records if bool(r.get("vaulted")) is bool(vaulted)]

    def get(self, file_id):
        self.calls.append(("get", file_id))
        return self._meta

    def download(self, file_id):
        self.calls.append(("download", file_id))
        return self._content

    def download_to(self, file_id, destination):
        import os
        self.calls.append(("download_to", file_id, destination))
        target = destination
        if os.path.isdir(destination):
            target = os.path.join(destination, self._meta.get("filename", "f.bin"))
        with open(target, "wb") as fh:
            fh.write(self._content)
        return target

    def upload(self, path, purpose="general"):
        self.calls.append(("upload", path, purpose))
        return self._meta


@pytest.fixture()
def fake_client(af, monkeypatch):
    holder = {}

    def _install(files):
        holder["files"] = files
        monkeypatch.setattr(af, "_client", lambda: type("C", (), {"files": files})())
        return files

    return _install


# ── listing ────────────────────────────────────────────────────────────

def test_listing_shows_which_files_expire(af, fake_client):
    """The distinction a user most needs: kept, or gone in 10 days."""
    fake_client(_FakeFiles(records=[
        {"id": "1", "filename": "keep.pdf", "content_type": "application/pdf",
         "bytes_original": 100, "vaulted": True, "expires_at": None},
        {"id": "2", "filename": "temp.csv", "content_type": "text/csv",
         "bytes_original": 50, "vaulted": False, "expires_at": 1234567890},
    ]))

    out = json.loads(af.handle_aiutils_files({"action": "list"}))

    assert out["count"] == 2
    kept = next(f for f in out["files"] if f["id"] == "1")
    temp = next(f for f in out["files"] if f["id"] == "2")
    assert kept["vaulted"] is True and kept["expires_at"] is None
    assert temp["vaulted"] is False and temp["expires_at"] is not None


def test_listing_marks_what_can_be_read_as_text(af, fake_client):
    """So the agent chooses read vs download without a failed attempt."""
    fake_client(_FakeFiles(records=[
        {"id": "1", "filename": "a.csv", "content_type": "text/csv",
         "bytes_original": 10, "vaulted": False},
        {"id": "2", "filename": "b.pdf", "content_type": "application/pdf",
         "bytes_original": 10, "vaulted": False},
    ]))

    out = json.loads(af.handle_aiutils_files({"action": "list"}))
    by_id = {f["id"]: f for f in out["files"]}

    assert by_id["1"]["readable_as_text"] is True
    assert by_id["2"]["readable_as_text"] is False


def test_vaulted_filter_is_passed_through(af, fake_client):
    files = fake_client(_FakeFiles(records=[]))
    af.handle_aiutils_files({"action": "list", "vaulted": True})
    assert files.calls[0] == ("list", True, 50)


# ── reading ────────────────────────────────────────────────────────────

def test_reading_a_text_file_returns_its_content(af, fake_client):
    fake_client(_FakeFiles(
        content=b"col_a,col_b\n1,2\n",
        meta={"filename": "d.csv", "content_type": "text/csv",
              "bytes_original": 17, "vaulted": True},
    ))

    out = json.loads(af.handle_aiutils_files({"action": "read", "file_id": "1"}))
    assert out["content"] == "col_a,col_b\n1,2\n"
    assert out["vaulted"] is True


def test_a_binary_is_not_decoded_into_the_conversation(af, fake_client):
    """Rendering a PDF as mojibake helps nobody."""
    fake_client(_FakeFiles(meta={
        "filename": "report.pdf", "content_type": "application/pdf",
        "bytes_original": 5000, "vaulted": False,
    }))

    out = af.handle_aiutils_files({"action": "read", "file_id": "1"})
    assert "not text" in out
    assert "download" in out


def test_a_large_text_file_is_refused_for_read(af, fake_client):
    """Pulling 40 MB into context costs more than working with it on disk."""
    fake_client(_FakeFiles(meta={
        "filename": "huge.csv", "content_type": "text/csv",
        "bytes_original": af.MAX_READ_BYTES + 1, "vaulted": True,
    }))

    out = af.handle_aiutils_files({"action": "read", "file_id": "1"})
    assert "read limit" in out
    assert "download" in out


def test_a_file_at_the_limit_is_still_readable(af, fake_client):
    """The boundary is inclusive; an off-by-one here is a confusing refusal."""
    fake_client(_FakeFiles(
        content=b"x" * 10,
        meta={"filename": "edge.txt", "content_type": "text/plain",
              "bytes_original": af.MAX_READ_BYTES, "vaulted": False},
    ))

    out = json.loads(af.handle_aiutils_files({"action": "read", "file_id": "1"}))
    assert out["content"] == "x" * 10


def test_text_that_is_not_valid_utf8_is_reported_honestly(af, fake_client):
    fake_client(_FakeFiles(
        content=b"\xff\xfe\x00\x01",
        meta={"filename": "odd.txt", "content_type": "text/plain",
              "bytes_original": 4, "vaulted": False},
    ))

    out = af.handle_aiutils_files({"action": "read", "file_id": "1"})
    assert "not valid UTF-8" in out


def test_read_requires_a_file_id(af, fake_client):
    fake_client(_FakeFiles())
    assert "file_id is required" in af.handle_aiutils_files({"action": "read"})


# ── downloading ────────────────────────────────────────────────────────

def test_download_writes_the_file_and_reports_the_path(af, fake_client, tmp_path):
    fake_client(_FakeFiles(
        content=b"binary payload here",
        meta={"filename": "out.bin", "content_type": "application/pdf"},
    ))

    out = json.loads(af.handle_aiutils_files({
        "action": "download", "file_id": "1", "destination": str(tmp_path),
    }))

    assert out["path"].endswith("out.bin")
    assert out["bytes"] == len(b"binary payload here")
    with open(out["path"], "rb") as fh:
        assert fh.read() == b"binary payload here"


def test_download_refuses_a_missing_directory(af, fake_client, tmp_path):
    fake_client(_FakeFiles())
    out = af.handle_aiutils_files({
        "action": "download", "file_id": "1",
        "destination": str(tmp_path / "nope" / "x.bin"),
    })
    assert "Directory does not exist" in out


def test_download_requires_a_destination(af, fake_client):
    fake_client(_FakeFiles())
    out = af.handle_aiutils_files({"action": "download", "file_id": "1"})
    assert "destination is required" in out


# ── uploading ──────────────────────────────────────────────────────────

def test_upload_tells_the_user_a_plain_file_will_be_deleted(af, fake_client, tmp_path):
    """A file that silently disappears in 10 days is worse than one explained."""
    source = tmp_path / "notes.txt"
    source.write_text("content")
    fake_client(_FakeFiles(meta={
        "id": "1", "filename": "notes.txt", "bytes_original": 7,
        "bytes_stored": 7, "encrypted": False, "vaulted": False,
        "expires_at": 1234567890,
    }))

    out = json.loads(af.handle_aiutils_files({"action": "upload", "path": str(source)}))
    assert out["vaulted"] is False
    assert "Deleted after 10 days" in out["retention"]
    assert "vault" in out["retention"].lower()


def test_upload_says_a_vault_file_is_kept(af, fake_client, tmp_path):
    source = tmp_path / "keep.txt"
    source.write_text("content")
    fake_client(_FakeFiles(meta={
        "id": "1", "filename": "keep.txt", "bytes_original": 7,
        "bytes_stored": 40, "encrypted": True, "vaulted": True,
        "expires_at": None,
    }))

    out = json.loads(af.handle_aiutils_files({"action": "upload", "path": str(source)}))
    assert out["vaulted"] is True
    assert out["encrypted"] is True
    assert "Kept indefinitely" in out["retention"]


def test_upload_refuses_a_path_that_does_not_exist(af, fake_client):
    fake_client(_FakeFiles())
    out = af.handle_aiutils_files({"action": "upload", "path": "/no/such/file.txt"})
    assert "No such file" in out


# ── surface ────────────────────────────────────────────────────────────

def test_unknown_action_names_the_valid_ones(af, fake_client):
    fake_client(_FakeFiles())
    out = af.handle_aiutils_files({"action": "teleport"})
    for valid in ("list", "read", "download", "upload"):
        assert valid in out


def test_no_key_material_is_handled_here(af):
    """Decryption is server-side; this module must never see a key.

    Checked against the AST rather than the source text: the module docstring
    legitimately *describes* unwrapping as something the server does, and a
    substring search would flag that prose as a violation. Only real
    identifiers count.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(af))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            continue  # string literals are prose, not key handling

    forbidden = {"dek_wrapped", "kek_id", "unwrap_key", "unwrap_user_key",
                 "AESGCM", "uek_wrapped", "wrap_key"}
    leaked = forbidden & names
    assert not leaked, f"agent-side module handles key material: {sorted(leaked)}"

    # And it must not import the crypto or key modules at all.
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("encryption" in m or "user_keys" in m or "cryptography" in m
                   for m in imported), f"unexpected crypto import: {imported}"


def test_registered_and_schema_serialises(af):
    json.dumps(af.AIUTILS_FILES_SCHEMA)

    from tools.registry import discover_builtin_tools, registry
    discover_builtin_tools()
    assert registry.get_schema("aiutils_files")


def test_listed_in_the_aiutils_toolset():
    """Registering alone does not make a tool reachable."""
    import toolsets

    assert "aiutils_files" in toolsets.TOOLSETS["aiutils"]["tools"]
