"""Simulation, planning and market termination criteria (DR-6, AIUT-2993).

Investigation and discovery already had criteria the gate enforces. These three
modes had `output_sections` and nothing else — prose contracts with no floor, so
a run could stop having done none of what the mode is for.

"The loop is behaviour. The floor is code." These tests are about the floor:

  * simulation cannot conclude while a side is unargued or unchallenged, which
    is what stops it producing a summary that splits the difference
  * planning cannot conclude on one option, or on options with no cost or no
    named risk
  * market cannot conclude on undated figures, on claims that do not say
    whether they are measured or projected, or with no stated falsifier

Each criterion is asserted independently. A floor that only happens to hold
when everything else aligns is not a floor.
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
    return json.loads(rt.handle_research_state({
        "action": "start", "question": "Should we proceed?", "mode": mode,
    }))["run_id"]


def _call(rt, **kw):
    return json.loads(rt.handle_research_state(kw))


def _gate(rt, run):
    return json.loads(rt.handle_research_gate({"run_id": run}))


def _satisfy_shared_floor(rt, run, *, dated=False):
    """Clear the mode-independent criteria so mode rules are what remain."""
    sources = [f"https://example.org/{i}" for i in range(4)]
    _call(rt, action="record_sources", run_id=run, sources=sources)
    claims = []
    for i in range(6):
        claim = {"claim": f"Finding number {i}.", "source": sources[i % 4],
                 "confidence": "high", "sub_question": "main"}
        if dated:
            claim["as_of"] = "2026-Q2"
            claim["basis"] = "measured"
        claims.append(claim)
    _call(rt, action="add_claims", run_id=run, claims=claims)
    _call(rt, action="set_gaps", run_id=run, gaps=[])


def _unmet_text(rt, run):
    return " ".join(_gate(rt, run)["unmet"]).lower()


# ── simulation ─────────────────────────────────────────────────────────

def test_simulation_needs_at_least_two_positions(rt):
    run = _start(rt, "simulation")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_positions", run_id=run, positions=[
        {"name": "For", "argument": "The strongest case for.",
         "weaknesses": ["Relies on one study."]}])

    assert _gate(rt, run)["sufficient"] is False
    assert "one side is not a simulation" in _unmet_text(rt, run)


def test_simulation_cannot_conclude_with_a_side_unargued(rt):
    """The failure this mode exists to prevent: a summary splitting the difference."""
    run = _start(rt, "simulation")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_positions", run_id=run, positions=[
        {"name": "For", "argument": "Strong case.", "weaknesses": ["Thin data."]},
        {"name": "Against", "weaknesses": ["Also thin."]},
    ])

    assert _gate(rt, run)["sufficient"] is False
    assert "not yet argued" in _unmet_text(rt, run)
    assert "against" in _unmet_text(rt, run)


def test_simulation_cannot_conclude_with_a_side_unchallenged(rt):
    """A position argued with no weaknesses has not been tested."""
    run = _start(rt, "simulation")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_positions", run_id=run, positions=[
        {"name": "For", "argument": "Strong case.", "weaknesses": ["Thin data."]},
        {"name": "Against", "argument": "Also strong."},
    ])

    assert _gate(rt, run)["sufficient"] is False
    assert "no weakness named" in _unmet_text(rt, run)


def test_simulation_passes_when_both_sides_are_argued_and_challenged(rt):
    run = _start(rt, "simulation")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_positions", run_id=run, positions=[
        {"name": "For", "argument": "Strongest case for.",
         "weaknesses": ["Depends on one dataset."]},
        {"name": "Against", "argument": "Strongest case against.",
         "weaknesses": ["Assumes conditions hold."]},
    ])

    gate = _gate(rt, run)
    assert gate["sufficient"] is True, gate["unmet"]


def test_a_position_can_be_strengthened_in_a_later_round(rt):
    """Naming a side and arguing it well are usually separate passes."""
    run = _start(rt, "simulation")
    _call(rt, action="add_positions", run_id=run,
          positions=[{"name": "For"}])
    out = _call(rt, action="add_positions", run_id=run,
                positions=[{"name": "For", "argument": "Now argued.",
                            "weaknesses": ["A weakness."]}])

    assert out["total_positions"] == 1, "the position was duplicated"
    assert out["missing_argument"] == []
    assert out["missing_weaknesses"] == []


def test_weaknesses_accumulate_without_duplicating(rt):
    run = _start(rt, "simulation")
    _call(rt, action="add_positions", run_id=run,
          positions=[{"name": "For", "weaknesses": ["A"]}])
    _call(rt, action="add_positions", run_id=run,
          positions=[{"name": "For", "weaknesses": ["A", "B"]}])

    state = _call(rt, action="get", run_id=run)
    assert state["positions"][0]["weaknesses"] == ["A", "B"]


# ── planning ───────────────────────────────────────────────────────────

def test_planning_needs_more_than_one_option(rt):
    run = _start(rt, "planning")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_options", run_id=run, options=[
        {"name": "Build", "cost": "3 engineers, 2 months", "risk": "Scope creep."}])

    assert _gate(rt, run)["sufficient"] is False
    assert "one option is not a choice" in _unmet_text(rt, run)


def test_an_uncosted_option_blocks_the_gate(rt):
    """An option with no cost is a wish."""
    run = _start(rt, "planning")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_options", run_id=run, options=[
        {"name": "Build", "cost": "3 engineers", "risk": "Scope creep."},
        {"name": "Buy", "risk": "Vendor lock-in."},
    ])

    assert _gate(rt, run)["sufficient"] is False
    assert "uncosted" in _unmet_text(rt, run)


def test_an_option_with_no_named_risk_blocks_the_gate(rt):
    run = _start(rt, "planning")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_options", run_id=run, options=[
        {"name": "Build", "cost": "3 engineers", "risk": "Scope creep."},
        {"name": "Buy", "cost": "$40k/yr"},
    ])

    assert _gate(rt, run)["sufficient"] is False
    assert "no risk named" in _unmet_text(rt, run)


def test_planning_passes_when_every_option_is_costed_and_risked(rt):
    run = _start(rt, "planning")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_options", run_id=run, options=[
        {"name": "Build", "cost": "3 engineers, 2 months", "risk": "Scope creep.",
         "trade_offs": "Full control, slower."},
        {"name": "Buy", "cost": "$40k/yr", "risk": "Vendor lock-in."},
    ])

    gate = _gate(rt, run)
    assert gate["sufficient"] is True, gate["unmet"]


def test_the_response_names_what_is_still_missing(rt):
    """"need to fix something" is not actionable; naming the option is."""
    run = _start(rt, "planning")
    out = _call(rt, action="add_options", run_id=run, options=[
        {"name": "Build", "cost": "3 engineers"},
        {"name": "Buy", "risk": "Lock-in."},
    ])

    assert out["missing_risk"] == ["Build"]
    assert out["missing_cost"] == ["Buy"]


# ── market ─────────────────────────────────────────────────────────────

def test_market_requires_a_falsifier(rt):
    """A thesis nothing could falsify is not a finding."""
    run = _start(rt, "market")
    _satisfy_shared_floor(rt, run, dated=True)

    assert _gate(rt, run)["sufficient"] is False
    assert "no falsifier recorded" in _unmet_text(rt, run)


def test_market_requires_every_figure_dated(rt):
    """A figure with no date is unreadable a month later."""
    run = _start(rt, "market")
    _satisfy_shared_floor(rt, run, dated=False)
    _call(rt, action="set_falsifier", run_id=run,
          falsifier="Two consecutive quarters of declining revenue.")

    assert _gate(rt, run)["sufficient"] is False
    assert "carry no date" in _unmet_text(rt, run)


def test_market_requires_measured_and_projected_to_be_distinguished(rt):
    """Presenting a projection as a measurement is this genre's failure mode."""
    run = _start(rt, "market")
    sources = ["https://example.org/a", "https://example.org/b",
               "https://example.org/c"]
    _call(rt, action="record_sources", run_id=run, sources=sources)
    _call(rt, action="add_claims", run_id=run, claims=[
        {"claim": f"Figure {i}.", "source": sources[i % 3], "confidence": "high",
         "as_of": "2026-Q2"} for i in range(6)])
    _call(rt, action="set_gaps", run_id=run, gaps=[])
    _call(rt, action="set_falsifier", run_id=run, falsifier="Revenue falls.")

    assert _gate(rt, run)["sufficient"] is False
    assert "measured or projected" in _unmet_text(rt, run)


def test_market_passes_when_dated_attributed_and_falsifiable(rt):
    run = _start(rt, "market")
    _satisfy_shared_floor(rt, run, dated=True)
    _call(rt, action="set_falsifier", run_id=run,
          falsifier="Two consecutive quarters of declining revenue.")

    gate = _gate(rt, run)
    assert gate["sufficient"] is True, gate["unmet"]


def test_an_empty_falsifier_is_refused(rt):
    run = _start(rt, "market")
    out = _call(rt, action="set_falsifier", run_id=run, falsifier="   ")
    assert "falsifier is required" in str(out)


def test_a_projected_claim_is_accepted_and_marked(rt):
    """Projections are legitimate — presenting them as measurements is not."""
    run = _start(rt, "market")
    _call(rt, action="record_sources", run_id=run, sources=["https://example.org/a"])
    _call(rt, action="add_claims", run_id=run, claims=[{
        "claim": "Revenue expected to grow 8%.", "source": "https://example.org/a",
        "confidence": "medium", "as_of": "2027", "basis": "projected"}])

    state = _call(rt, action="get", run_id=run)
    assert state["claims"][0]["basis"] == "projected"
    assert state["claims"][0]["as_of"] == "2027"


def test_the_output_contract_says_it_is_not_investment_advice(rt):
    """A structural part of the contract, not a footnote left to memory."""
    spec = rt.mode_spec("market")
    joined = " ".join(spec["output_sections"]).lower()
    assert "not investment advice" in joined


# ── the other modes are untouched ──────────────────────────────────────

def test_investigation_is_unaffected_by_the_new_criteria(rt):
    """An investigation has no positions or options and must not be blocked."""
    run = _start(rt, "investigation")
    _satisfy_shared_floor(rt, run)

    gate = _gate(rt, run)
    assert gate["sufficient"] is True, gate["unmet"]


def test_discovery_is_unaffected(rt):
    run = _start(rt, "discovery")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_candidates", run_id=run, candidates=[
        {"name": "A", "score": 0.9, "evaluated": True},
        {"name": "B", "score": 0.5},
        {"name": "C", "score": 0.2},
    ])

    gate = _gate(rt, run)
    assert gate["sufficient"] is True, gate["unmet"]


def test_the_deck_surfaces_mode_material(rt):
    from tools import research_deck

    run = _start(rt, "planning")
    _satisfy_shared_floor(rt, run)
    _call(rt, action="add_options", run_id=run, options=[
        {"name": "Build", "cost": "3 engineers", "risk": "Scope creep."},
        {"name": "Buy", "cost": "$40k", "risk": "Lock-in."},
    ])

    deck = json.loads(research_deck._handle({"run_id": run}))
    assert deck["mode"] == "planning"
    assert len(deck["mode_material"]["options"]) == 2
    assert "positions" not in deck["mode_material"], (
        "an investigation-shaped section leaked into a planning deck")
