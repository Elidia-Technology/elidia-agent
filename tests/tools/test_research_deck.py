"""Deck analytics computed from recorded state (DR-8).

The properties that matter:

  1. Numbers come from the RECORD, not from prose. A model asked to summarise
     its own confidence produces something that sounds calibrated; counting is
     checkable.

  2. Limitations are ASSEMBLED, not remembered. Unmet gate criteria, uncovered
     sub-questions and unresolved contradictions are collected here so the
     section cannot quietly shrink when the agent writes the report.

  3. No template is returned. The owner directive is that the agent composes
     each deck; a test fails if HTML starts appearing in this tool's output.
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


@pytest.fixture()
def rd(rt):
    import tools.research_deck as module
    importlib.reload(module)
    return module


def _run(rt, mode="investigation", subs=("A", "B")):
    return json.loads(rt.handle_research_state({
        "action": "start", "question": "Does X cause Y?", "mode": mode,
        "persona": "medical", "sub_questions": list(subs),
    }))["run_id"]


def _deck(rd, run_id):
    return json.loads(rd._handle({"run_id": run_id}))


# ── analytics come from the record ─────────────────────────────────────

def test_confidence_mix_is_counted_not_described(rt, rd):
    run_id = _run(rt)
    rt.handle_research_state({"action": "record_sources", "run_id": run_id,
                              "sources": ["https://a.example/1", "https://b.example/2"]})
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": [
        {"claim": "c1", "source": "https://a.example/1", "confidence": "high", "sub_question": "A"},
        {"claim": "c2", "source": "https://a.example/1", "confidence": "low", "sub_question": "A"},
        {"claim": "c3", "source": "https://b.example/2", "confidence": "medium", "sub_question": "B"},
        {"claim": "c4", "source": "https://b.example/2", "confidence": "high", "sub_question": "B"},
    ]})

    mix = _deck(rd, run_id)["analytics"]["confidence_mix"]
    assert mix["high"]["count"] == 2
    assert mix["low"]["count"] == 1
    assert mix["high"]["share"] == 0.5


def test_sources_group_by_origin_not_by_url(rt, rd):
    """Eleven pages from one domain is different work from eleven domains."""
    run_id = _run(rt)
    srcs = [f"https://same.example/page{i}" for i in range(3)] + ["https://other.example/x"]
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": srcs})
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": [
        {"claim": f"c{i}", "source": s, "confidence": "high", "sub_question": "A"}
        for i, s in enumerate(srcs)
    ]})

    dist = _deck(rd, run_id)["analytics"]["source_distribution"]
    top = dist[0]
    assert top["source"] == "same.example"
    assert top["claims"] == 3
    assert {d["source"] for d in dist} == {"same.example", "other.example"}


def test_www_prefix_is_stripped_so_one_site_is_one_bar(rt, rd):
    run_id = _run(rt)
    rt.handle_research_state({"action": "record_sources", "run_id": run_id,
                              "sources": ["https://www.site.example/a", "https://site.example/b"]})
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": [
        {"claim": "c1", "source": "https://www.site.example/a", "confidence": "high", "sub_question": "A"},
        {"claim": "c2", "source": "https://site.example/b", "confidence": "high", "sub_question": "A"},
    ]})

    dist = _deck(rd, run_id)["analytics"]["source_distribution"]
    assert len(dist) == 1
    assert dist[0]["claims"] == 2


def test_corpus_sources_group_by_collection(rt, rd):
    run_id = _run(rt)
    rt.handle_research_state({"action": "record_sources", "run_id": run_id,
                              "sources": ["corpus://legal_kb/doc1", "corpus://legal_kb/doc2"]})
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": [
        {"claim": "c1", "source": "corpus://legal_kb/doc1", "confidence": "high", "sub_question": "A"},
        {"claim": "c2", "source": "corpus://legal_kb/doc2", "confidence": "high", "sub_question": "A"},
    ]})

    dist = _deck(rd, run_id)["analytics"]["source_distribution"]
    assert dist[0]["source"] == "corpus:legal_kb"
    assert dist[0]["claims"] == 2


def test_an_uncovered_sub_question_is_visible(rt, rd):
    """The most important thing a reader can know, and invisible unless counted."""
    run_id = _run(rt, subs=("A", "B"))
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": ["s1"]})
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": [
        {"claim": "only about A", "source": "s1", "confidence": "high", "sub_question": "A"},
    ]})

    a = _deck(rd, run_id)["analytics"]
    assert a["uncovered_sub_questions"] == ["B"]
    covB = next(c for c in a["coverage"] if c["sub_question"] == "B")
    assert covB["claims"] == 0 and covB["uncovered"] is True


def test_claims_not_tied_to_a_sub_question_are_counted(rt, rd):
    """A tangent recorded as a claim should be visible as unattributed."""
    run_id = _run(rt, subs=("A",))
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": ["s1"]})
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": [
        {"claim": "tangent", "source": "s1", "confidence": "medium"},
    ]})

    assert _deck(rd, run_id)["analytics"]["unattributed_claims"] == 1


def test_ranked_candidates_are_returned_in_order(rt, rd):
    run_id = _run(rt, mode="discovery")
    rt.handle_research_state({"action": "add_candidates", "run_id": run_id, "candidates": [
        {"name": "low", "score": 0.1}, {"name": "high", "score": 0.9, "evaluated": True},
    ]})

    ranked = _deck(rd, run_id)["analytics"]["candidates_ranked"]
    assert [c["name"] for c in ranked] == ["high", "low"]
    assert ranked[0]["evaluated"] is True


def test_empty_run_does_not_divide_by_zero(rt, rd):
    run_id = _run(rt)
    a = _deck(rd, run_id)["analytics"]
    assert a["totals"]["claims"] == 0
    assert a["confidence_mix"]["high"]["share"] == 0.0


# ── limitations are assembled, not remembered ──────────────────────────

def test_unmet_gate_criteria_become_limitations(rt, rd):
    run_id = _run(rt)
    out = _deck(rd, run_id)
    assert out["limitations"], "a run with no evidence reported no limitations"
    assert any("claims" in l for l in out["limitations"])


def test_uncovered_sub_question_becomes_a_limitation(rt, rd):
    run_id = _run(rt, subs=("A", "B"))
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": ["s1"]})
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": [
        {"claim": "about A", "source": "s1", "confidence": "high", "sub_question": "A"},
    ]})

    assert any("No evidence was found for: B" in l for l in _deck(rd, run_id)["limitations"])


def test_unresolved_contradiction_becomes_a_limitation(rt, rd):
    run_id = _run(rt)
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": ["s1"]})
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": [
        {"claim": "disputed thing", "source": "s1", "confidence": "medium",
         "sub_question": "A", "contested": True},
    ]})

    out = _deck(rd, run_id)
    assert any("Contradiction left unresolved: disputed thing" in l for l in out["limitations"])
    assert out["analytics"]["contested"][0]["resolved"] is False


def test_a_resolved_contradiction_is_not_listed_as_a_limitation(rt, rd):
    run_id = _run(rt)
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": ["s1"]})
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": [
        {"claim": "disputed thing", "source": "s1", "confidence": "medium",
         "sub_question": "A", "contested": True},
    ]})
    rt.handle_research_state({"action": "resolve_contested", "run_id": run_id,
        "resolutions": [{"claim": "disputed thing", "assessment": "A is better supported"}]})

    out = _deck(rd, run_id)
    assert not any("Contradiction left unresolved" in l for l in out["limitations"])
    assert out["analytics"]["contested"][0]["resolved"] is True


# ── no template, per the owner directive ───────────────────────────────

def test_the_tool_returns_no_markup(rt, rd):
    """Decks are composed per run. A template here would be layout-by-rote."""
    run_id = _run(rt)
    body = rd._handle({"run_id": run_id})

    for marker in ("<html", "<!doctype", "<div", "<section", "<style", "<script"):
        assert marker not in body.lower(), f"deck tool emitted markup: {marker!r}"


def test_constraints_are_stated_as_requirements(rt, rd):
    run_id = _run(rt)
    joined = " ".join(_deck(rd, run_id)["constraints"]).lower()

    assert "no network" in joined
    assert "no template" in joined
    assert "limitations are a section" in joined
    assert "print css" in joined


def test_output_contract_matches_the_run_mode(rt, rd):
    run_id = _run(rt, mode="discovery")
    contract = _deck(rd, run_id)["output_contract"]
    assert any("Ranked candidates" in s for s in contract)


# ── errors ─────────────────────────────────────────────────────────────

def test_unknown_run_id_is_an_error(rt, rd):
    assert "nope" in rd._handle({"run_id": "nope"})


def test_missing_run_id_is_an_error(rt, rd):
    assert "run_id is required" in rd._handle({})


# ── registration ───────────────────────────────────────────────────────

def test_registered_and_schema_serialises(rd):
    json.dumps(rd.RESEARCH_DECK_SCHEMA)

    from tools.registry import discover_builtin_tools, registry
    discover_builtin_tools()
    assert registry.get_schema("research_deck")


def test_subset_invariant_holds():
    import toolsets

    cli = set(toolsets.TOOLSETS["elidia-cli"]["tools"])
    for surface in ("elidia-acp", "elidia-api-server"):
        assert set(toolsets.TOOLSETS[surface]["tools"]) - cli == set()
    assert "research_deck" in cli
