"""Publishing a research deck so it outlives the session (DR-8, AIUT-2997).

Tier A — writing the deck to the user's own filesystem — already shipped and is
the default: permanent, theirs, works offline. This is tier B, the copy kept
server-side so a deck can be reopened from another machine or another session.

The behaviour that matters is honesty about retention. A published deck is kept
indefinitely for an account with a vault and deleted after 10 days without one,
and which applies is a fact about the account, not something the agent can
predict. So:

  * the retention sentence is built from what the SERVER returned, never assumed
  * the 10-day expiry is stated at publish time, in words, not implied by a
    timestamp the user has to interpret
  * a failed publish still leaves the local file, and says so — losing the
    session's work because an upload failed would be the worst outcome here

The SDK is substituted at the client boundary; the handler above it is real.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture()
def rd(tmp_path, monkeypatch):
    monkeypatch.setenv("ELIDIA_CONFIG_DIR", str(tmp_path))
    import tools.research_tools  # noqa: F401  (deck loads runs through it)
    importlib.reload(tools.research_tools)
    import tools.research_deck as module
    importlib.reload(module)
    return module


@pytest.fixture()
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv("ELIDIA_CONFIG_DIR", str(tmp_path))
    import tools.research_tools as module
    importlib.reload(module)
    return module


class _FakeFiles:
    def __init__(self, record=None, error=None, artifacts=None):
        self._record = record or {}
        self._error = error
        self._artifacts = artifacts or []
        self.calls = []

    def upload(self, path, purpose="general", metadata=None):
        self.calls.append(("upload", path, purpose, metadata))
        if self._error:
            raise self._error
        return self._record

    def artifacts(self, limit=50):
        self.calls.append(("artifacts", limit))
        if self._error:
            raise self._error
        return self._artifacts


@pytest.fixture()
def fake_client(rd, monkeypatch):
    from tools import aiutils_client

    def _install(files):
        monkeypatch.setattr(
            aiutils_client, "get_client",
            lambda: type("C", (), {"files": files})())
        return files
    return _install


def _run(rt):
    return json.loads(rt.handle_research_state({
        "action": "start", "question": "Does compound X reduce tumour growth?",
        "mode": "investigation",
    }))["run_id"]


def _deck(tmp_path):
    path = tmp_path / "deck.html"
    path.write_text("<!doctype html><title>Report</title><h1>Findings</h1>")
    return str(path)


# ── retention is reported, never guessed ───────────────────────────────

def test_a_deck_without_a_vault_says_ten_days_in_words(rd, rt, fake_client, tmp_path):
    """A timestamp the user has to decode is not a warning."""
    run = _run(rt)
    fake_client(_FakeFiles(record={
        "id": "f1", "bytes_original": 500, "vaulted": False,
        "expires_at": 1767225600, "encrypted": False,
    }))

    out = json.loads(rd._handle({
        "action": "publish", "run_id": run, "path": _deck(tmp_path)}))

    assert out["vaulted"] is False
    assert "10 days" in out["retention"]
    assert "local file" in out["retention"], "the permanent copy is not mentioned"


def test_a_vaulted_deck_says_it_is_kept(rd, rt, fake_client, tmp_path):
    run = _run(rt)
    fake_client(_FakeFiles(record={
        "id": "f2", "bytes_original": 500, "vaulted": True,
        "expires_at": None, "encrypted": True,
    }))

    out = json.loads(rd._handle({
        "action": "publish", "run_id": run, "path": _deck(tmp_path)}))

    assert out["vaulted"] is True
    assert "Kept indefinitely" in out["retention"]
    assert "10 days" not in out["retention"]


def test_the_retention_sentence_follows_the_server_not_the_tool(rd, rt, fake_client, tmp_path):
    """If the server says vaulted, that is the answer — no local prediction."""
    run = _run(rt)
    # No vault was set up in this run's state; the server still says vaulted.
    fake_client(_FakeFiles(record={
        "id": "f3", "bytes_original": 1, "vaulted": True, "expires_at": None}))

    out = json.loads(rd._handle({
        "action": "publish", "run_id": run, "path": _deck(tmp_path)}))

    assert "Kept indefinitely" in out["retention"]


# ── what gets recorded ─────────────────────────────────────────────────

def test_the_run_is_recorded_so_the_deck_is_findable_later(rd, rt, fake_client, tmp_path):
    """A filename and a date cannot tell two investigations apart."""
    run = _run(rt)
    files = fake_client(_FakeFiles(record={
        "id": "f4", "bytes_original": 10, "vaulted": False, "expires_at": 1}))

    rd._handle({"action": "publish", "run_id": run, "path": _deck(tmp_path)})

    _, path, purpose, metadata = files.calls[0]
    assert purpose == "research_deck", "the deck would not appear in artifacts"
    assert metadata["run_id"] == run
    assert metadata["question"] == "Does compound X reduce tumour growth?"
    assert metadata["mode"] == "investigation"
    assert "claims" in metadata and "sources" in metadata


# ── failure must not cost the work ─────────────────────────────────────

def test_a_failed_publish_points_at_the_local_file(rd, rt, fake_client, tmp_path):
    """Losing the deck because an upload failed would be the worst outcome."""
    run = _run(rt)
    fake_client(_FakeFiles(error=RuntimeError("gateway unreachable")))
    path = _deck(tmp_path)

    out = rd._handle({"action": "publish", "run_id": run, "path": path})

    assert "Could not publish" in out or "unreachable" in out
    assert path in out, "the surviving local copy was not named"


def test_publish_requires_a_written_file(rd, rt, fake_client, tmp_path):
    run = _run(rt)
    fake_client(_FakeFiles())

    assert "path is required" in rd._handle({"action": "publish", "run_id": run})
    assert "No such file" in rd._handle({
        "action": "publish", "run_id": run, "path": str(tmp_path / "nope.html")})


def test_publish_requires_a_real_run(rd, fake_client, tmp_path):
    fake_client(_FakeFiles())
    out = rd._handle({
        "action": "publish", "run_id": "no-such-run", "path": _deck(tmp_path)})
    assert "no research run" in out


# ── finding a deck again ───────────────────────────────────────────────

def test_listing_returns_published_decks(rd, fake_client):
    fake_client(_FakeFiles(artifacts=[
        {"id": "a1", "question": "Does X cause Y?", "created_at": 1,
         "retention": "Deleted 10 days after upload.",
         "open_url": "/v1/files/a1/content"},
    ]))

    out = json.loads(rd._handle({"action": "list"}))

    assert out["count"] == 1
    assert out["artifacts"][0]["question"] == "Does X cause Y?"


def test_an_empty_listing_explains_how_to_publish(rd, fake_client):
    fake_client(_FakeFiles(artifacts=[]))
    out = rd._handle({"action": "list"})
    assert "No decks have been published" in out
    assert "publish" in out


# ── the default path is unchanged ──────────────────────────────────────

def test_analytics_remains_the_default_action(rd, rt):
    """Every existing caller passes run_id with no action."""
    run = _run(rt)
    out = json.loads(rd._handle({"run_id": run}))

    assert "analytics" in out
    assert "constraints" in out
    assert "limitations" in out


def test_unknown_action_names_the_valid_ones(rd, rt):
    run = _run(rt)
    out = rd._handle({"action": "teleport", "run_id": run})
    for valid in ("analytics", "publish", "list"):
        assert valid in out


def test_schema_exposes_the_new_actions(rd):
    enum = rd.RESEARCH_DECK_SCHEMA["parameters"]["properties"]["action"]["enum"]
    assert enum == ["analytics", "publish", "list"]
    json.dumps(rd.RESEARCH_DECK_SCHEMA)
