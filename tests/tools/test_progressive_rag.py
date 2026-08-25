"""Progressive RAG — retrieval that improves across rounds (DR-7, AIUT-2996).

A single similarity search answers the question you already knew how to ask.
Research does not start there. Plan §5B: round 1 is broad and records hits AND
misses; round 2 rebuilds queries from the vocabulary the evidence actually
used; corpus selection narrows to the origins that produced accepted claims.

The substrate cannot make those judgements — they are the model's. What it must
do is make them *answerable* instead of guessed, and that is what is tested:

  * a miss is recorded as a result, not as the absence of one
  * a failure to reach an origin is never counted as "nothing found there"
  * productivity is measured in ACCEPTED CLAIMS, not passages returned, so a
    noisy origin does not attract the next round's budget
  * queries already tried are visible, so a round does not repeat itself
  * retrieved identifiers become citable, so a claim about something genuinely
    fetched is not rejected on a bookkeeping technicality
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture()
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv("ELIDIA_CONFIG_DIR", str(tmp_path))
    import tools.research_tools as module
    importlib.reload(module)
    return module


def _start(rt):
    return json.loads(rt.handle_research_state({
        "action": "start",
        "question": "Does compound X reduce tumour growth?",
        "mode": "investigation",
    }))["run_id"]


def _call(rt, **kw):
    return json.loads(rt.handle_research_state(kw))


# ── recording ──────────────────────────────────────────────────────────

def test_a_retrieval_is_recorded_with_what_it_produced(rt):
    run = _start(rt)
    out = _call(rt, action="record_retrieval", run_id=run,
                origin="pubmed", query="compound X tumour",
                sources=["https://pubmed.ncbi.nlm.nih.gov/1/",
                         "https://pubmed.ncbi.nlm.nih.gov/2/"])

    assert out["origin"] == "pubmed"
    assert out["produced"] == 2
    assert out["returned_nothing"] is False


def test_a_miss_is_a_result_not_an_absence(rt):
    """Round 2 drops a corpus BECAUSE round 1 recorded that it gave nothing."""
    run = _start(rt)
    out = _call(rt, action="record_retrieval", run_id=run,
                origin="ai_vectors_legal_case_law_corpus",
                query="compound X tumour", sources=[])

    assert out["returned_nothing"] is True

    report = _call(rt, action="retrieval_report", run_id=run)
    row = next(r for r in report["origins"]
               if r["origin"] == "ai_vectors_legal_case_law_corpus")
    assert row["empty_results"] == 1
    assert row["times_queried"] == 1


def test_retrieved_identifiers_become_citable(rt):
    """A claim about something genuinely fetched must not be rejected."""
    run = _start(rt)
    _call(rt, action="record_retrieval", run_id=run, origin="pubmed",
          query="q", sources=["https://pubmed.ncbi.nlm.nih.gov/42/"])

    out = _call(rt, action="add_claims", run_id=run, claims=[{
        "claim": "Compound X reduced growth by 40% in mice.",
        "source": "https://pubmed.ncbi.nlm.nih.gov/42/",
        "confidence": "high", "sub_question": "efficacy",
    }])

    assert out["accepted"] == 1, out


def test_a_fabricated_citation_is_still_rejected(rt):
    """record_retrieval must not become a way around the anti-fabrication wall."""
    run = _start(rt)
    _call(rt, action="record_retrieval", run_id=run, origin="pubmed",
          query="q", sources=["https://pubmed.ncbi.nlm.nih.gov/42/"])

    out = _call(rt, action="add_claims", run_id=run, claims=[{
        "claim": "Invented finding.",
        "source": "https://pubmed.ncbi.nlm.nih.gov/999999/",
        "confidence": "high",
    }])

    assert out["accepted"] == 0
    assert out["rejected"], "a never-retrieved source was accepted"


def test_origin_and_query_are_both_required(rt):
    run = _start(rt)
    assert "origin is required" in str(
        _call(rt, action="record_retrieval", run_id=run, query="q"))
    assert "query is required" in str(
        _call(rt, action="record_retrieval", run_id=run, origin="pubmed"))


# ── the report is what aims the next round ─────────────────────────────

def test_budget_follows_accepted_claims_not_passage_count(rt):
    """The core of progressive RAG.

    A noisy origin returns many passages that support nothing; a precise one
    returns two that carry the answer. Ranking by passages would send round 2
    to the noisy one.
    """
    run = _start(rt)
    noisy = [f"https://noisy.example/{i}" for i in range(10)]
    precise = ["https://precise.example/a", "https://precise.example/b"]

    _call(rt, action="record_retrieval", run_id=run, origin="noisy_corpus",
          query="q", sources=noisy)
    _call(rt, action="record_retrieval", run_id=run, origin="precise_corpus",
          query="q", sources=precise)

    _call(rt, action="add_claims", run_id=run, claims=[
        {"claim": "Finding one.", "source": precise[0], "confidence": "high"},
        {"claim": "Finding two.", "source": precise[1], "confidence": "high"},
    ])

    report = _call(rt, action="retrieval_report", run_id=run)
    ranked = [r["origin"] for r in report["origins"]]

    assert ranked[0] == "precise_corpus", (
        f"ranked by passages, not claims: {report['origins']}")
    noisy_row = next(r for r in report["origins"] if r["origin"] == "noisy_corpus")
    assert noisy_row["passages"] == 10
    assert noisy_row["claims_supported"] == 0


def test_origins_with_no_claims_are_named_as_candidates_not_decisions(rt):
    """Dropping an origin is the model's call; the tool supplies the arithmetic."""
    run = _start(rt)
    _call(rt, action="record_retrieval", run_id=run, origin="quiet_corpus",
          query="q", sources=[])

    report = _call(rt, action="retrieval_report", run_id=run)

    assert "quiet_corpus" in report["no_claims_yet"]
    # The guidance must push toward rewording before discarding — a corpus
    # rarely phrases a thing the way the question does.
    assert "vocabulary" in report["guidance"]


def test_queries_already_tried_are_visible(rt):
    """So a later round does not ask the same thing again."""
    run = _start(rt)
    _call(rt, action="record_retrieval", run_id=run, origin="pubmed",
          query="compound X tumour growth", sources=[])
    _call(rt, action="record_retrieval", run_id=run, origin="pubmed",
          query="X antineoplastic mechanism", sources=["https://p/1"])

    report = _call(rt, action="retrieval_report", run_id=run)
    row = next(r for r in report["origins"] if r["origin"] == "pubmed")

    assert row["times_queried"] == 2
    assert set(row["queries_tried"]) == {
        "compound X tumour growth", "X antineoplastic mechanism"}


def test_a_failure_is_not_counted_as_nothing_found(rt):
    """Being unable to look says nothing about whether the evidence exists."""
    run = _start(rt)
    _call(rt, action="record_retrieval", run_id=run, origin="pubmed",
          query="q", sources=[], failed=True)

    report = _call(rt, action="retrieval_report", run_id=run)
    row = next(r for r in report["origins"] if r["origin"] == "pubmed")

    assert row["failures"] == 1


def test_rounds_are_attributed_so_narrowing_is_visible(rt):
    run = _start(rt)
    _call(rt, action="record_retrieval", run_id=run, origin="a", query="q1",
          sources=["https://a/1"])
    _call(rt, action="next_round", run_id=run)
    _call(rt, action="record_retrieval", run_id=run, origin="a", query="q2",
          sources=["https://a/2"])

    state = _call(rt, action="get", run_id=run)
    rounds = [entry["round"] for entry in state["retrievals"]]
    assert rounds == [0, 1], rounds


def test_an_empty_report_is_valid_before_any_retrieval(rt):
    run = _start(rt)
    report = _call(rt, action="retrieval_report", run_id=run)

    assert report["origins"] == []
    assert report["no_claims_yet"] == []


def test_the_new_actions_are_in_the_schema(rt):
    enum = rt.RESEARCH_STATE_SCHEMA["parameters"]["properties"]["action"]["enum"]
    assert "record_retrieval" in enum
    assert "retrieval_report" in enum
    json.dumps(rt.RESEARCH_STATE_SCHEMA)
