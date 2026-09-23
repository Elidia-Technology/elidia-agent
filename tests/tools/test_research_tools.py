"""Tests for the deep-research loop substrate (DR-1).

The two properties that matter are the ones a prompt cannot guarantee:

  1. A claim citing a source that was never retrieved is REJECTED, not stored.
     This is what makes a fabricated citation impossible rather than merely
     discouraged.

  2. The sufficiency floor is arithmetic over recorded state, so it cannot be
     argued past. Each criterion is asserted independently, because a floor that
     only happens to pass when all four align is not a floor.

Everything here writes to a tmp_path-scoped ELIDIA_CONFIG_DIR, so no test
touches a real run in ~/.elidia/research.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture()
def rt(tmp_path, monkeypatch):
    """research_tools bound to an isolated config dir."""
    monkeypatch.setenv("ELIDIA_CONFIG_DIR", str(tmp_path))
    import tools.research_tools as module
    importlib.reload(module)
    return module


def _start(rt, **kw):
    args = {"action": "start", "question": "Does X cause Y?", "mode": "investigation"}
    args.update(kw)
    return json.loads(rt.handle_research_state(args))


def _gate(rt, run_id):
    return json.loads(rt.handle_research_gate({"run_id": run_id}))


# ── run lifecycle ──────────────────────────────────────────────────────

def test_start_returns_run_id_and_seeds_gaps_from_sub_questions(rt):
    out = _start(rt, sub_questions=["a", "b"])

    assert out["run_id"]
    assert out["sub_questions"] == ["a", "b"]
    state = json.loads(rt.handle_research_state({"action": "get", "run_id": out["run_id"]}))
    # Sub-questions start life as open gaps — nothing is answered yet.
    assert state["open_gaps"] == ["a", "b"]


def test_start_rejects_an_unknown_mode_and_names_the_valid_ones(rt):
    out = _start(rt, mode="vibes")

    assert "error" in out
    assert "investigation" in out["valid_modes"]


def test_caps_are_clamped_not_trusted(rt):
    out = _start(rt, max_rounds=9999, wall_clock_seconds=1)

    assert out["max_rounds"] == rt.MAX_ROUNDS_CEILING
    assert out["wall_clock_seconds"] == 60  # floor, not the 1 that was asked for


def test_state_survives_a_reload(rt, tmp_path, monkeypatch):
    """A run interrupted mid-loop must resume, not restart."""
    run_id = _start(rt, sub_questions=["a"])["run_id"]
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": ["u1"]})
    rt.handle_research_state({"action": "next_round", "run_id": run_id})

    import tools.research_tools as module
    importlib.reload(module)

    state = json.loads(module.handle_research_state({"action": "get", "run_id": run_id}))
    assert state["rounds_done"] == 1
    assert state["sources"] == ["u1"]


# ── the anti-fabrication wall ──────────────────────────────────────────

def test_claim_citing_an_unretrieved_source_is_rejected(rt):
    run_id = _start(rt)["run_id"]
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": ["https://real.example/a"]})

    out = json.loads(rt.handle_research_state({
        "action": "add_claims",
        "run_id": run_id,
        "claims": [
            {"claim": "grounded", "source": "https://real.example/a", "confidence": "high"},
            {"claim": "invented", "source": "https://never-fetched.example/b", "confidence": "high"},
        ],
    }))

    assert out["accepted"] == 1
    assert out["total_claims"] == 1
    assert len(out["rejected"]) == 1
    assert "never recorded as retrieved" in out["rejected"][0]["reason"]


def test_claims_without_a_source_are_rejected(rt):
    run_id = _start(rt)["run_id"]

    out = json.loads(rt.handle_research_state({
        "action": "add_claims",
        "run_id": run_id,
        "claims": [{"claim": "unsourced assertion", "confidence": "high"}],
    }))

    assert out["accepted"] == 0
    assert out["rejected"][0]["reason"] == "claim has no source"


def test_invalid_confidence_falls_back_to_medium_rather_than_being_trusted(rt):
    run_id = _start(rt)["run_id"]
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": ["u1"]})

    rt.handle_research_state({
        "action": "add_claims", "run_id": run_id,
        "claims": [{"claim": "c", "source": "u1", "confidence": "absolutely-certain"}],
    })

    state = json.loads(rt.handle_research_state({"action": "get", "run_id": run_id}))
    assert state["claims"][0]["confidence"] == "medium"


# ── the floor, criterion by criterion ──────────────────────────────────

def _populate(rt, run_id, *, n_claims, n_sources, n_high):
    sources = [f"u{i}" for i in range(n_sources)]
    rt.handle_research_state({"action": "record_sources", "run_id": run_id, "sources": sources})
    claims = []
    for i in range(n_claims):
        claims.append({
            "claim": f"claim {i}",
            "source": sources[i % n_sources],
            "confidence": "high" if i < n_high else "low",
        })
    rt.handle_research_state({"action": "add_claims", "run_id": run_id, "claims": claims})


def test_gate_blocks_on_too_few_claims(rt):
    run_id = _start(rt)["run_id"]
    _populate(rt, run_id, n_claims=2, n_sources=2, n_high=2)
    rt.handle_research_state({"action": "set_gaps", "run_id": run_id, "gaps": []})

    g = _gate(rt, run_id)
    assert g["sufficient"] is False
    assert any("need 5 claims" in r for r in g["unmet"])


def test_gate_blocks_on_too_few_unique_sources(rt):
    run_id = _start(rt)["run_id"]
    # 6 claims, all from one source — plenty of claims, no corroboration.
    _populate(rt, run_id, n_claims=6, n_sources=1, n_high=6)
    rt.handle_research_state({"action": "set_gaps", "run_id": run_id, "gaps": []})

    g = _gate(rt, run_id)
    assert g["sufficient"] is False
    assert any("unique sources" in r for r in g["unmet"])


def test_gate_blocks_on_low_confidence_ratio(rt):
    run_id = _start(rt)["run_id"]
    # 8 claims across 4 sources but only 1 high-confidence → 12.5% < 30%
    _populate(rt, run_id, n_claims=8, n_sources=4, n_high=1)
    rt.handle_research_state({"action": "set_gaps", "run_id": run_id, "gaps": []})

    g = _gate(rt, run_id)
    assert g["sufficient"] is False
    assert any("high-confidence" in r for r in g["unmet"])


def test_gate_blocks_while_gaps_remain_even_when_evidence_is_otherwise_ample(rt):
    run_id = _start(rt, sub_questions=["unanswered thing"])["run_id"]
    _populate(rt, run_id, n_claims=10, n_sources=5, n_high=10)

    g = _gate(rt, run_id)
    assert g["sufficient"] is False
    assert any("open gap" in r for r in g["unmet"])


def test_gate_passes_only_when_every_criterion_is_met(rt):
    run_id = _start(rt)["run_id"]
    _populate(rt, run_id, n_claims=6, n_sources=3, n_high=3)
    rt.handle_research_state({"action": "set_gaps", "run_id": run_id, "gaps": []})

    g = _gate(rt, run_id)
    assert g["sufficient"] is True
    assert g["unmet"] == []
    assert "you may synthesize" in g["verdict"]


# ── budget is reported separately from sufficiency ─────────────────────

def test_out_of_rounds_but_insufficient_is_reported_as_both(rt):
    """The honest outcome: stop, but do not claim the answer is complete."""
    run_id = _start(rt, max_rounds=1)["run_id"]
    rt.handle_research_state({"action": "next_round", "run_id": run_id})

    g = _gate(rt, run_id)
    assert g["sufficient"] is False
    assert g["may_continue"] is False
    assert any("round cap" in r for r in g["budget_exhausted_because"])
    assert "limitations" in g["verdict"]


def test_wall_clock_exhaustion_is_detected(rt, monkeypatch):
    run_id = _start(rt, wall_clock_seconds=60)["run_id"]

    real_time = rt.time.time
    monkeypatch.setattr(rt.time, "time", lambda: real_time() + 3600)

    g = _gate(rt, run_id)
    assert g["may_continue"] is False
    assert any("wall clock" in r for r in g["budget_exhausted_because"])


# ── error surfaces ─────────────────────────────────────────────────────

def test_unknown_run_id_is_an_error_not_a_silent_empty_state(rt):
    out = rt.handle_research_gate({"run_id": "does-not-exist"})
    assert "does-not-exist" in out

    out2 = rt.handle_research_state({"action": "get", "run_id": "nope"})
    assert "nope" in out2


def test_unknown_action_names_the_valid_ones(rt):
    run_id = _start(rt)["run_id"]
    out = rt.handle_research_state({"action": "teleport", "run_id": run_id})
    assert "add_claims" in out


def test_list_reports_recent_runs(rt):
    a = _start(rt, question="first")["run_id"]
    b = _start(rt, question="second")["run_id"]

    out = json.loads(rt.handle_research_state({"action": "list"}))
    ids = {r["run_id"] for r in out["runs"]}
    assert {a, b} <= ids


# ── registration ───────────────────────────────────────────────────────

def test_both_tools_are_registered_and_schemas_serialise(rt):
    # A tool the model cannot receive is not wired, however good the code is.
    for schema in (rt.RESEARCH_STATE_SCHEMA, rt.RESEARCH_GATE_SCHEMA):
        json.dumps(schema)
        assert schema["parameters"]["required"]

    from tools.registry import registry
    assert registry.get_schema("research_state")
    assert registry.get_schema("research_gate")


def test_subset_invariant_holds_for_derived_surfaces():
    """Nothing may exist on a derived surface that elidia-cli lacks."""
    import toolsets
    cli = set(toolsets.TOOLSETS["elidia-cli"]["tools"])
    for surface in ("elidia-acp", "elidia-api-server"):
        assert set(toolsets.TOOLSETS[surface]["tools"]) - cli == set()
    assert {"research_state", "research_gate"} <= cli
