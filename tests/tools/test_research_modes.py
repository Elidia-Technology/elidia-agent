"""Mode-specific termination for investigation and discovery (DR-4).

The shared floor — claims, sources, confidence, gaps — is not a finish line for
every kind of research. "Candidates generated, ranked and evaluated" is a
different contract from "evidence chain complete, contradictions resolved". A
mode that terminates on generic criteria produces a discovery run with no
ranked candidates, which is not discovery.

These tests assert each mode's extra requirement holds independently of the
shared floor, and that the other three modes are unaffected.
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


def _start(rt, mode):
    return json.loads(rt.handle_research_state(
        {"action": "start", "question": "Q", "mode": mode}))["run_id"]


def _clear_floor(rt, run_id, *, contested=False):
    """Satisfy the shared floor so mode requirements are what remain."""
    sources = [f"u{i}" for i in range(3)]
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": sources})
    claims = [
        {"claim": f"claim {i}", "source": sources[i % 3], "confidence": "high",
         "contested": contested and i == 0}
        for i in range(6)
    ]
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": claims})
    rt.handle_research_state({"action": "set_gaps", "run_id": run_id, "gaps": []})


def _gate(rt, run_id):
    return json.loads(rt.handle_research_gate({"run_id": run_id}))


# ── investigation: contradictions must be adjudicated ──────────────────

def test_investigation_blocks_while_a_contested_claim_is_unresolved(rt):
    run_id = _start(rt, "investigation")
    _clear_floor(rt, run_id, contested=True)

    g = _gate(rt, run_id)
    assert g["sufficient"] is False, "shared floor cleared but contradiction ignored"
    assert any("contested" in r for r in g["unmet"])


def test_investigation_passes_once_the_contradiction_is_adjudicated(rt):
    run_id = _start(rt, "investigation")
    _clear_floor(rt, run_id, contested=True)

    out = json.loads(rt.handle_research_state({
        "action": "resolve_contested", "run_id": run_id,
        "resolutions": [{"claim": "claim 0",
                         "assessment": "Source A is more recent and directly on point."}],
    }))
    assert out["accepted"] == 1

    assert _gate(rt, run_id)["sufficient"] is True


def test_unresolved_is_still_a_resolution(rt):
    """Some conflicts genuinely cannot be settled. Saying so is an answer."""
    run_id = _start(rt, "investigation")
    _clear_floor(rt, run_id, contested=True)
    rt.handle_research_state({
        "action": "resolve_contested", "run_id": run_id,
        "resolutions": [{"claim": "claim 0", "assessment": "Cannot be settled on "
                         "available evidence; both readings remain open.", "resolved": False}],
    })
    assert _gate(rt, run_id)["sufficient"] is True


def test_resolution_of_a_claim_never_marked_contested_is_rejected(rt):
    """Otherwise an investigation clears its gate without touching the real conflict."""
    run_id = _start(rt, "investigation")
    _clear_floor(rt, run_id, contested=True)

    out = json.loads(rt.handle_research_state({
        "action": "resolve_contested", "run_id": run_id,
        "resolutions": [{"claim": "claim 3", "assessment": "hand-wave"}],
    }))
    assert out["accepted"] == 0
    assert "no contested claim matches" in out["rejected"][0]["reason"]
    assert _gate(rt, run_id)["sufficient"] is False


def test_resolution_requires_an_assessment(rt):
    run_id = _start(rt, "investigation")
    _clear_floor(rt, run_id, contested=True)
    out = json.loads(rt.handle_research_state({
        "action": "resolve_contested", "run_id": run_id,
        "resolutions": [{"claim": "claim 0"}],
    }))
    assert out["accepted"] == 0


def test_investigation_without_contested_claims_needs_no_resolutions(rt):
    run_id = _start(rt, "investigation")
    _clear_floor(rt, run_id, contested=False)
    assert _gate(rt, run_id)["sufficient"] is True


# ── discovery: candidates generated, ranked, evaluated ─────────────────

def test_discovery_blocks_with_no_candidates_despite_a_clean_floor(rt):
    run_id = _start(rt, "discovery")
    _clear_floor(rt, run_id)

    g = _gate(rt, run_id)
    assert g["sufficient"] is False, "discovery finished without producing candidates"
    assert any("candidates" in r for r in g["unmet"])


def test_discovery_blocks_while_a_candidate_is_unscored(rt):
    run_id = _start(rt, "discovery")
    _clear_floor(rt, run_id)
    rt.handle_research_state({"action": "add_candidates", "run_id": run_id, "candidates": [
        {"name": "A", "score": 0.9, "evaluated": True},
        {"name": "B", "score": 0.5},
        {"name": "C"},  # generated but never ranked
    ]})

    g = _gate(rt, run_id)
    assert g["sufficient"] is False
    assert any("unranked" in r for r in g["unmet"])


def test_discovery_blocks_when_nothing_was_actually_evaluated(rt):
    """Generating and ranking is not evaluating."""
    run_id = _start(rt, "discovery")
    _clear_floor(rt, run_id)
    rt.handle_research_state({"action": "add_candidates", "run_id": run_id, "candidates": [
        {"name": "A", "score": 0.9}, {"name": "B", "score": 0.5}, {"name": "C", "score": 0.2},
    ]})

    g = _gate(rt, run_id)
    assert g["sufficient"] is False
    assert any("evaluated" in r for r in g["unmet"])


def test_discovery_passes_when_generated_ranked_and_evaluated(rt):
    run_id = _start(rt, "discovery")
    _clear_floor(rt, run_id)
    rt.handle_research_state({"action": "add_candidates", "run_id": run_id, "candidates": [
        {"name": "A", "score": 0.9, "evaluated": True, "evaluation": "binds at 2.1 nM"},
        {"name": "B", "score": 0.5}, {"name": "C", "score": 0.2},
    ]})

    assert _gate(rt, run_id)["sufficient"] is True


def test_candidates_update_in_place_rather_than_duplicating(rt):
    """Ranking is usually a separate pass from generation."""
    run_id = _start(rt, "discovery")
    rt.handle_research_state({"action": "add_candidates", "run_id": run_id,
                              "candidates": [{"name": "A"}, {"name": "B"}]})
    out = json.loads(rt.handle_research_state({"action": "add_candidates", "run_id": run_id,
                                               "candidates": [{"name": "A", "score": 0.8}]}))
    assert out["added"] == 0 and out["updated"] == 1
    assert out["total_candidates"] == 2
    assert out["ranking"][0] == {"name": "A", "score": 0.8}


def test_candidates_are_returned_in_rank_order(rt):
    run_id = _start(rt, "discovery")
    out = json.loads(rt.handle_research_state({"action": "add_candidates", "run_id": run_id,
        "candidates": [{"name": "low", "score": 0.1}, {"name": "high", "score": 0.9},
                       {"name": "mid", "score": 0.5}]}))
    assert [c["name"] for c in out["ranking"]] == ["high", "mid", "low"]


def test_non_numeric_score_is_rejected(rt):
    run_id = _start(rt, "discovery")
    out = json.loads(rt.handle_research_state({"action": "add_candidates", "run_id": run_id,
        "candidates": [{"name": "A", "score": "very promising"}]}))
    assert out["added"] == 0
    assert "not a number" in out["rejected"][0]["reason"]


def test_candidate_without_a_name_is_rejected(rt):
    run_id = _start(rt, "discovery")
    out = json.loads(rt.handle_research_state({"action": "add_candidates", "run_id": run_id,
                                               "candidates": [{"score": 0.5}]}))
    assert out["added"] == 0


# ── the other three modes now have floors of their own ─────────────────
# This test previously asserted that simulation, planning and market stopped on
# the shared floor alone. That was true, and it was the gap DR-6 closed: those
# modes had an output contract with nothing enforcing it, so a run could stop
# having done none of what the mode is for. Clearing the shared floor is now
# necessary but no longer sufficient for them.
#
# The criteria themselves are exercised in test_modes_sim_plan_market.py; what
# this asserts is the boundary — that each still has something left to do.

@pytest.mark.parametrize("mode,expected", [
    ("simulation", "simulation"),
    ("planning", "option"),
    ("market", "falsifier"),
])
def test_the_three_contract_modes_require_more_than_the_shared_floor(rt, mode, expected):
    run_id = _start(rt, mode)
    _clear_floor(rt, run_id)

    gate = _gate(rt, run_id)
    assert gate["sufficient"] is False, (
        f"{mode} cleared the gate having recorded none of what the mode is for")
    assert expected in " ".join(gate["unmet"]).lower()


# ── output contracts ───────────────────────────────────────────────────

def test_every_mode_declares_an_output_contract(rt):
    for mode in rt.RESEARCH_MODES:
        sections = rt.MODE_SPECS[mode]["output_sections"]
        assert sections, f"{mode} has no output contract"
        assert any("limitation" in s.lower() for s in sections), (
            f"{mode} does not require a limitations section — a report that hides "
            "what it does not know is worse than a shorter one"
        )


def test_gate_reports_the_output_contract_for_the_run_mode(rt):
    run_id = _start(rt, "discovery")
    g = _gate(rt, run_id)
    assert g["mode"] == "discovery"
    assert "Ranked candidates with rationale" in g["output_contract"]


def test_mode_specs_cover_exactly_the_selectable_modes(rt):
    assert set(rt.MODE_SPECS) == set(rt.RESEARCH_MODES)


# ── persistence ────────────────────────────────────────────────────────

def test_candidates_and_resolutions_survive_a_reload(rt):
    run_id = _start(rt, "discovery")
    rt.handle_research_state({"action": "add_candidates", "run_id": run_id,
                              "candidates": [{"name": "A", "score": 0.7}]})

    import tools.research_tools as module
    importlib.reload(module)

    state = json.loads(module.handle_research_state({"action": "get", "run_id": run_id}))
    assert state["candidates"][0]["name"] == "A"
    assert state["candidates_ranked"][0]["score"] == 0.7
