"""Tests for persona + mode selection (DR-3).

Three properties matter here:

  1. The persona registry is REUSED, not duplicated. An earlier draft of this
     work invented a parallel ten-persona set; these tests fail if that
     regresses.

  2. Resource packs are DISCOVERED. A persona naming a skill is a preference,
     not a claim that it is installed — availability is checked against the
     filesystem and anything missing is reported rather than silently dropped.
     Naming resources that do not exist is the DomainSpec.rag_collections
     failure (AIUT-2985).

  3. An invented persona cannot be stored. research_state validates against the
     real registry instead of accepting any string.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture()
def rp():
    import tools.research_personas as module
    importlib.reload(module)
    return module


@pytest.fixture()
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv("ELIDIA_CONFIG_DIR", str(tmp_path))
    import tools.research_tools as module
    importlib.reload(module)
    return module


# ── reuse, not duplication ─────────────────────────────────────────────

def test_personas_come_from_the_canonical_registry(rp):
    from elidia_cli.personas import BUILTIN_PERSONALITIES

    assert set(rp.valid_persona_names()) == set(BUILTIN_PERSONALITIES)


def test_module_defines_no_parallel_persona_prompts(rp):
    """Guards the duplication that an earlier draft introduced.

    This module may map personas to resource packs; it must not carry its own
    copies of their prompts, which would drift from personas.py.
    """
    import inspect

    from elidia_cli.personas import BUILTIN_PERSONALITIES

    src = inspect.getsource(rp)

    # Prompts are fetched from the registry, never written literally here.
    assert 'spec.get("system_prompt"' in src
    assert "BUILTIN_PERSONALITIES" in src

    # And no persona's prompt text is copied into this module. A substring of a
    # real prompt appearing here means someone pasted instead of importing.
    for name, spec in BUILTIN_PERSONALITIES.items():
        prompt = (spec.get("system_prompt") or "").strip()
        if len(prompt) >= 40:
            assert prompt[:40] not in src, f"{name}'s prompt appears copied into research_personas"


def test_every_persona_has_a_pack_entry_and_grounding_note(rp):
    for name in rp.valid_persona_names():
        assert name in rp.DOMAIN_PACKS, f"{name} has no resource-pack entry"
        assert name in rp.PACK_NOTES, f"{name} has no grounding note"


# ── discovery, not assertion ───────────────────────────────────────────

def test_listed_pack_skills_actually_exist_on_disk(rp):
    """Anything reported as available must be real."""
    payload = json.loads(rp.handle_research_personas({"action": "list"}))
    for entry in payload["personas"]:
        for skill in entry["resource_pack"]:
            assert rp._skill_installed(skill), (
                f"{entry['persona']} lists {skill!r} as available but it is not installed"
            )


def test_unavailable_pack_skills_are_reported_not_hidden(rp, monkeypatch):
    """A missing skill must surface, so a thin run is visible as thin."""
    monkeypatch.setattr(rp, "_skill_installed", lambda name: False)
    payload = json.loads(rp.handle_research_personas({"action": "list"}))

    legal = next(p for p in payload["personas"] if p["persona"] == "legal")
    assert legal["resource_pack"] == []
    assert set(legal["resource_pack_unavailable"]) == set(rp.DOMAIN_PACKS["legal"])


def test_list_includes_every_mode_with_its_contract(rp):
    from tools.research_tools import RESEARCH_MODES

    payload = json.loads(rp.handle_research_personas({"action": "list"}))
    listed = {m["mode"]: m["contract"] for m in payload["modes"]}
    assert listed == RESEARCH_MODES


# ── resolve ────────────────────────────────────────────────────────────

def test_resolve_returns_prompt_pack_and_announcement(rp):
    out = json.loads(rp.handle_research_personas(
        {"action": "resolve", "persona": "legal", "mode": "investigation"}))

    assert out["persona"] == "legal"
    assert out["mode"] == "investigation"
    assert out["system_prompt"], "resolve returned no system prompt"
    assert out["announcement"].startswith("Researching as legal in investigation mode")
    assert out["mode_contract"]


def test_announcement_is_always_produced(rp, monkeypatch):
    """The choice must never be silent, even with an empty resource pack."""
    monkeypatch.setattr(rp, "_skill_installed", lambda name: False)
    out = json.loads(rp.handle_research_personas(
        {"action": "resolve", "persona": "musician", "mode": "planning"}))
    assert out["announcement"]


def test_resolve_rejects_an_invented_persona_and_lists_the_real_ones(rp):
    out = json.loads(rp.handle_research_personas(
        {"action": "resolve", "persona": "quantum_lawyer", "mode": "investigation"}))

    assert "error" in out
    assert "legal" in out["valid_personas"]


def test_resolve_rejects_an_invented_mode(rp):
    out = json.loads(rp.handle_research_personas(
        {"action": "resolve", "persona": "legal", "mode": "vibes"}))

    assert "error" in out
    assert "investigation" in out["valid_modes"]


def test_resolve_requires_both_arguments(rp):
    assert "persona is required" in rp.handle_research_personas({"action": "resolve"})
    assert "mode is required" in rp.handle_research_personas(
        {"action": "resolve", "persona": "legal"})


def test_unknown_action_names_the_valid_ones(rp):
    out = rp.handle_research_personas({"action": "teleport"})
    assert "list" in out and "resolve" in out


# ── no keyword classification anywhere ─────────────────────────────────

def test_module_does_not_classify_user_text(rp):
    """The lens is the model's choice from an enum, never inferred from wording.

    Cue-list routing pre-empts the model's judgement and fails on exactly the
    questions that matter, so there must be no matching against user text here.
    """
    import inspect

    src = inspect.getsource(rp)
    for banned in ("re.search", "re.match", "re.findall", ".lower() in ", "if keyword"):
        assert banned not in src, f"persona selection appears to inspect text via {banned!r}"


# ── the DR-1 validation gap this closed ────────────────────────────────

def test_research_state_rejects_an_invented_persona(rt):
    out = json.loads(rt.handle_research_state({
        "action": "start", "question": "Q", "mode": "investigation",
        "persona": "quantum_lawyer",
    }))

    assert "error" in out, "an invented persona was silently accepted"
    assert "legal" in out["valid_personas"]


def test_research_state_accepts_a_real_persona(rt):
    out = json.loads(rt.handle_research_state({
        "action": "start", "question": "Q", "mode": "investigation", "persona": "legal",
    }))

    assert "run_id" in out
    state = json.loads(rt.handle_research_state({"action": "get", "run_id": out["run_id"]}))
    assert state["persona"] == "legal"


def test_persona_remains_optional(rt):
    """Not every run needs a lens; only a WRONG one is refused."""
    out = json.loads(rt.handle_research_state({
        "action": "start", "question": "Q", "mode": "investigation",
    }))
    assert "run_id" in out


# ── registration ───────────────────────────────────────────────────────

def test_tool_is_registered_and_schema_serialises(rp):
    json.dumps(rp.RESEARCH_PERSONAS_SCHEMA)

    from tools.registry import discover_builtin_tools, registry
    discover_builtin_tools()
    assert registry.get_schema("research_personas")


def test_subset_invariant_still_holds():
    import toolsets

    cli = set(toolsets.TOOLSETS["elidia-cli"]["tools"])
    for surface in ("elidia-acp", "elidia-api-server"):
        assert set(toolsets.TOOLSETS[surface]["tools"]) - cli == set()
    assert "research_personas" in cli
