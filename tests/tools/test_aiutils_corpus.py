"""The agent's reach into the platform corpora (AIUT-2985).

Before this tool the agent could not touch a single one of the platform's 4.4M
embedded passages: it reaches RAG through the Developer API, whose collections
are developer-owned and empty on production.

What is worth testing here is the judgement the tool protects:

  * corpora must be chosen, not guessed — there is no topic-to-corpus mapping,
    and the tool must not grow one
  * a corpus that returned nothing is surfaced, because the next round needs it
  * an empty result explains what to try, rather than reading as "no answer
    exists"

The SDK is substituted at the client boundary; everything above it is the real
handler.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture()
def ac():
    import tools.aiutils_corpus as module
    importlib.reload(module)
    return module


class _FakeRag:
    def __init__(self, corpora=None, result=None):
        self._corpora = corpora or []
        self._result = result or {}
        self.calls = []

    def corpora(self, family=None, samples=False):
        self.calls.append(("corpora", family, samples))
        if family is None:
            return self._corpora
        return [c for c in self._corpora if c.get("family") == family]

    def search_corpora(self, query, corpora, top_k=8, min_similarity=0.0):
        self.calls.append(("search", query, list(corpora), top_k, min_similarity))
        return self._result


@pytest.fixture()
def fake_client(ac, monkeypatch):
    def _install(rag):
        monkeypatch.setattr(ac, "_client",
                            lambda: type("C", (), {"rag": rag})())
        return rag
    return _install


# ── listing ────────────────────────────────────────────────────────────

def test_listing_reports_what_exists(ac, fake_client):
    fake_client(_FakeRag(corpora=[
        {"name": "ai_vectors_legal_case_law_corpus", "family": "legal",
         "approx_rows": 38514},
        {"name": "ai_vectors_medical_chatbot_qa", "family": "medical",
         "approx_rows": 252396},
    ]))

    out = json.loads(ac.handle_aiutils_corpus({"action": "list"}))

    assert out["count"] == 2
    assert set(out["families"]) == {"legal", "medical"}


def test_a_family_filter_is_passed_through(ac, fake_client):
    rag = fake_client(_FakeRag(corpora=[
        {"name": "ai_vectors_legal_x", "family": "legal", "approx_rows": 1},
        {"name": "ai_vectors_medical_y", "family": "medical", "approx_rows": 1},
    ]))

    out = json.loads(ac.handle_aiutils_corpus({"action": "list", "family": "legal"}))

    assert rag.calls[0] == ("corpora", "legal", False)
    assert out["count"] == 1


def test_samples_are_requested_when_asked(ac, fake_client):
    """A name and a row count do not reveal what a corpus holds."""
    rag = fake_client(_FakeRag(corpora=[
        {"name": "ai_vectors_legal_x", "family": "legal", "approx_rows": 1,
         "sample": "Section 438 anticipatory bail"},
    ]))

    ac.handle_aiutils_corpus({"action": "list", "samples": True})
    assert rag.calls[0] == ("corpora", None, True)


def test_an_empty_catalog_explains_the_next_step(ac, fake_client):
    fake_client(_FakeRag(corpora=[]))
    out = ac.handle_aiutils_corpus({"action": "list", "family": "nonexistent"})
    assert "No corpora found" in out
    assert "without a family filter" in out


# ── searching ──────────────────────────────────────────────────────────

def test_search_returns_passages_with_their_similarity(ac, fake_client):
    fake_client(_FakeRag(result={
        "query": "anticipatory bail",
        "searched": ["ai_vectors_legal_indian_law_knowledge"],
        "hits": [{"corpus": "ai_vectors_legal_indian_law_knowledge",
                  "family": "legal", "document_id": "d1",
                  "content": "Section 438 CrPC provides...",
                  "metadata": {}, "similarity": 0.7049}],
        "returned_nothing": [],
        "failed": [],
    }))

    out = json.loads(ac.handle_aiutils_corpus({
        "action": "search", "query": "anticipatory bail",
        "corpora": ["ai_vectors_legal_indian_law_knowledge"],
    }))

    assert out["count"] == 1
    assert out["hits"][0]["similarity"] == 0.7049
    assert "Section 438" in out["hits"][0]["content"]


def test_corpora_that_returned_nothing_reach_the_agent(ac, fake_client):
    """The miss decides where the next round spends its budget."""
    fake_client(_FakeRag(result={
        "query": "q", "searched": ["a", "b"],
        "hits": [{"corpus": "a", "family": "legal", "document_id": "1",
                  "content": "x", "metadata": {}, "similarity": 0.8}],
        "returned_nothing": ["ai_vectors_medical_chatbot_qa"],
        "failed": [],
    }))

    out = json.loads(ac.handle_aiutils_corpus({
        "action": "search", "query": "q", "corpora": ["a", "b"]}))

    assert out["returned_nothing"] == ["ai_vectors_medical_chatbot_qa"]


def test_no_hits_suggests_rewording_rather_than_denying_an_answer(ac, fake_client):
    """"Nothing found" and "no answer exists" are different claims."""
    fake_client(_FakeRag(result={
        "query": "q", "searched": ["ai_vectors_legal_x"], "hits": [],
        "returned_nothing": ["ai_vectors_legal_x"], "failed": [],
    }))

    out = ac.handle_aiutils_corpus({
        "action": "search", "query": "q", "corpora": ["ai_vectors_legal_x"]})

    assert "vocabulary" in out or "wording" in out
    assert "list" in out


def test_search_requires_a_corpus_and_says_whose_call_it_is(ac, fake_client):
    fake_client(_FakeRag())
    out = ac.handle_aiutils_corpus({"action": "search", "query": "q"})
    assert "corpora is required" in out
    assert "your call" in out


def test_a_single_corpus_name_is_accepted_as_a_string(ac, fake_client):
    """A caller passing one name should not fail on a shape technicality."""
    rag = fake_client(_FakeRag(result={
        "query": "q", "searched": ["ai_vectors_legal_x"],
        "hits": [{"corpus": "ai_vectors_legal_x", "family": "legal",
                  "document_id": "1", "content": "x", "metadata": {},
                  "similarity": 0.9}],
        "returned_nothing": [], "failed": [],
    }))

    ac.handle_aiutils_corpus({
        "action": "search", "query": "q", "corpora": "ai_vectors_legal_x"})

    assert rag.calls[0][2] == ["ai_vectors_legal_x"]


def test_search_requires_a_query(ac, fake_client):
    fake_client(_FakeRag())
    assert "query is required" in ac.handle_aiutils_corpus(
        {"action": "search", "corpora": ["a"]})


# ── the rule that must not erode ───────────────────────────────────────

def test_the_tool_holds_no_topic_to_corpus_mapping(ac):
    """Selection is the model's judgement.

    A rule sending "drug interaction" to a medical corpus would send "what did
    the court say about the drug schedule" there too, and miss the legal corpus
    holding the answer. Checked against the AST so the tool's own prose — which
    legitimately describes this — cannot trip it.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ac))

    # A mapping would be a dict literal pairing subject words with corpus names.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        values = [v.value for v in node.values
                  if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        mapped = [v for v in values if v.startswith("ai_vectors_")]
        assert not (keys and mapped), (
            f"a dict maps terms to corpus names: {keys[:3]} -> {mapped[:3]}"
        )


def test_registered_and_reachable(ac):
    import json as _json

    _json.dumps(ac.AIUTILS_CORPUS_SCHEMA)

    from tools.registry import discover_builtin_tools, registry
    discover_builtin_tools()
    assert registry.get_schema("aiutils_corpus")

    import toolsets
    assert "aiutils_corpus" in toolsets.TOOLSETS["aiutils"]["tools"]


def test_unknown_action_names_the_valid_ones(ac, fake_client):
    fake_client(_FakeRag())
    out = ac.handle_aiutils_corpus({"action": "teleport"})
    assert "list" in out and "search" in out


# ── the registry contract ──────────────────────────────────────────────

def test_check_fn_returns_a_plain_bool_not_a_tuple():
    """The registry tests truthiness, and every non-empty tuple is truthy.

    This shipped returning `(False, "unavailable")` on its failure path, which
    the registry read as True — advertising the tool as available at exactly
    the moment its own check had failed. Asserted for all three AiUtils tools
    because they shared the same mistake.
    """
    from tools.aiutils_account import check_aiutils_account_requirements
    from tools.aiutils_corpus import check_aiutils_corpus_requirements
    from tools.aiutils_files import check_aiutils_files_requirements

    for name, fn in (
        ("files", check_aiutils_files_requirements),
        ("corpus", check_aiutils_corpus_requirements),
        ("account", check_aiutils_account_requirements),
    ):
        value = fn()
        assert isinstance(value, bool), (
            f"{name} check_fn returned {type(value).__name__}; the registry "
            f"treats a (False, reason) tuple as available"
        )


def test_a_broken_client_reports_unavailable(monkeypatch):
    """The failure path specifically — that is where the tuple used to leak."""
    import tools.aiutils_corpus as module
    from tools import aiutils_client

    def _explode():
        raise RuntimeError("SDK import failed")

    monkeypatch.setattr(aiutils_client, "check_aiutils_requirements", _explode)

    result = module.check_aiutils_corpus_requirements()
    assert result is False, f"a broken client reported {result!r}"
