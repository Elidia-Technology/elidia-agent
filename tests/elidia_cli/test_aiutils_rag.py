"""Tests for the CLI RAG tools (Module 6 of AIUT-2954, closes B6).

Handlers are driven directly against a fake SDK client — no network. These cover
what the tool layer owns: argument validation, truncation of oversized results,
and the fact that these tools are UNBILLED and must never consult the credit
guard.
"""

import json
import types

import pytest

from tools import aiutils_client, aiutils_rag


class _FakeRAG:
    def __init__(self):
        self.calls = []

    def ingest(self, **kw):
        self.calls.append(("ingest", kw))
        return types.SimpleNamespace(
            document_id="doc-1", collection=kw["collection"], chunks=3, skipped=False
        )

    def search(self, **kw):
        self.calls.append(("search", kw))
        return [types.SimpleNamespace(
            content="a relevant passage about refunds",
            score=0.87, collection="handbook", title="Policy", source_ref=None,
        )]

    def list_collections(self):
        self.calls.append(("list_collections", {}))
        return [types.SimpleNamespace(
            name="handbook", kind="user", document_count=2, chunk_count=12, description=None
        )]

    def list_documents(self, collection=None):
        self.calls.append(("list_documents", {"collection": collection}))
        return [types.SimpleNamespace(
            id="doc-1", title="Policy", collection="handbook", source_ref=None, chunk_count=4
        )]


class _FakeClient:
    def __init__(self):
        self.rag = _FakeRAG()


@pytest.fixture
def client(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(aiutils_client, "get_client", lambda base_url=None: fake)
    return fake


def _parse(result):
    return json.loads(result)


class TestIngest:
    def test_stores_and_reports_chunks(self, client):
        out = _parse(aiutils_rag._handle_ingest({"collection": "notes", "content": "hello"}))
        assert out["chunks"] == 3
        assert out["skipped"] is False
        assert client.rag.calls[0][1]["collection"] == "notes"

    def test_collection_is_required(self, client):
        assert "collection is required" in _parse(
            aiutils_rag._handle_ingest({"content": "x"})
        )["error"]

    def test_empty_content_is_rejected(self, client):
        assert "content is required" in _parse(
            aiutils_rag._handle_ingest({"collection": "c", "content": "   "})
        )["error"]

    def test_oversized_content_is_refused_before_the_call(self, client):
        out = _parse(aiutils_rag._handle_ingest({
            "collection": "c", "content": "x" * (aiutils_rag.MAX_INGEST_CHARS + 1),
        }))
        assert "limit is" in out["error"]
        assert client.rag.calls == [], "must not reach the API"

    def test_skipped_reingest_is_explained(self, client, monkeypatch):
        monkeypatch.setattr(client.rag, "ingest", lambda **kw: types.SimpleNamespace(
            document_id="d", collection="c", chunks=3, skipped=True
        ))
        out = _parse(aiutils_rag._handle_ingest({"collection": "c", "content": "same"}))
        assert out["skipped"] is True
        assert "re-embedded" in out["note"]


class TestSearch:
    def test_returns_passages_with_scores(self, client):
        out = _parse(aiutils_rag._handle_search({"query": "refunds"}))
        assert out["count"] == 1
        assert "refunds" in out["results"][0]["content"]
        assert out["results"][0]["score"] == 0.87

    def test_query_is_required(self, client):
        assert "query is required" in _parse(aiutils_rag._handle_search({"query": " "}))["error"]

    def test_top_k_is_clamped(self, client):
        aiutils_rag._handle_search({"query": "q", "top_k": 9999})
        assert client.rag.calls[-1][1]["top_k"] == aiutils_rag.MAX_TOP_K

    def test_oversized_chunks_are_truncated(self, client, monkeypatch):
        """A broad search must not flood the agent's context window."""
        monkeypatch.setattr(client.rag, "search", lambda **kw: [
            types.SimpleNamespace(content="x" * 5000, score=0.5,
                                  collection="c", title=None, source_ref=None)
        ])
        out = _parse(aiutils_rag._handle_search({"query": "q"}))
        assert out["results"][0]["truncated"] is True
        assert len(out["results"][0]["content"]) <= aiutils_rag.CHUNK_PREVIEW_CHARS + 1

    def test_empty_result_explains_how_to_check(self, client, monkeypatch):
        monkeypatch.setattr(client.rag, "search", lambda **kw: [])
        out = _parse(aiutils_rag._handle_search({"query": "q"}))
        assert out["count"] == 0
        assert "aiutils_rag_collections" in out["note"]

    def test_results_are_labelled_as_sources_not_an_answer(self, client):
        out = _parse(aiutils_rag._handle_search({"query": "q"}))
        assert "not an answer" in out["note"]


class TestListing:
    def test_collections_report_sizes(self, client):
        out = _parse(aiutils_rag._handle_collections({}))
        assert out["total"] == 1
        assert out["collections"][0]["chunks"] == 12

    def test_documents_filter_by_collection(self, client):
        aiutils_rag._handle_documents({"collection": "handbook"})
        assert client.rag.calls[-1][1]["collection"] == "handbook"

    def test_documents_without_filter_pass_none(self, client):
        aiutils_rag._handle_documents({})
        assert client.rag.calls[-1][1]["collection"] is None


class TestRagToolsAreUnbilled:
    """Embeddings run on AiUtils hardware, so nothing is charged. Guarding these
    would refuse retrieval on an empty wallet — exactly when a user most needs
    their own notes. Same call as the catalog tools: guard what spends, never
    what reads."""

    def test_no_handler_consults_the_credit_guard(self, client, monkeypatch):
        def _refuse(*a, **kw):
            raise AssertionError("RAG tools are free and must not consult the credit guard")

        monkeypatch.setattr(aiutils_client, "check_spend_allowed", _refuse)
        monkeypatch.setattr(aiutils_client, "check_credit_before_spend", _refuse)

        assert _parse(aiutils_rag._handle_ingest({"collection": "c", "content": "x"}))["chunks"] == 3
        assert _parse(aiutils_rag._handle_search({"query": "q"}))["count"] == 1
        assert _parse(aiutils_rag._handle_collections({}))["total"] == 1
        assert _parse(aiutils_rag._handle_documents({}))["total"] == 1
