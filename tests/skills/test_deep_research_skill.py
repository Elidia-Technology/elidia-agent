"""Contract tests binding the deep-research SKILL to the tools it drives.

A skill is documentation the model executes, so an inaccuracy in it is a bug —
the model will faithfully call an action that does not exist. The platform has
already shipped that class of defect once: DomainSpec.rag_collections named 30
collections that were never created, and nothing noticed because nothing read
the field (AIUT-2985).

These tests read the skill and assert every tool, action and mode it names is
real, so the skill cannot drift away from research_tools.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / "research" / "deep-research" / "SKILL.md"


@pytest.fixture(scope="module")
def raw() -> str:
    assert SKILL_PATH.exists(), f"skill missing at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def flat(raw) -> str:
    """Whitespace-collapsed lowercase text.

    The skill is hard-wrapped markdown, so a phrase like "no network" can span
    a line break. These assertions are about what the skill SAYS, not how it is
    wrapped, so match against normalised text.
    """
    return re.sub(r"\s+", " ", raw).lower()


@pytest.fixture(scope="module")
def frontmatter(raw):
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    assert m, "skill has no frontmatter block"
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(m.group(1))


def test_frontmatter_has_the_fields_the_loader_reads(frontmatter):
    for key in ("name", "description", "version", "prerequisites"):
        assert key in frontmatter, f"frontmatter missing {key!r}"
    assert frontmatter["name"] == "deep-research"


def test_parses_through_the_real_skill_loader(raw):
    """Guards against a frontmatter change the loader silently drops."""
    import tools.skills_tool as st

    fm, body = st._parse_frontmatter(raw[:4000])
    assert fm.get("name") == "deep-research"
    assert body.strip(), "skill body is empty after frontmatter parsing"
    assert st.skill_matches_platform(fm), "skill excluded on this platform"


def test_every_prerequisite_tool_is_actually_registered(frontmatter):
    from tools.registry import discover_builtin_tools, registry

    discover_builtin_tools()
    tools = frontmatter["prerequisites"]["tools"]
    assert tools, "skill declares no prerequisite tools"
    for name in tools:
        assert registry.get_schema(name), f"prerequisite tool {name!r} is not registered"


def test_skill_names_no_action_the_tool_does_not_implement(raw):
    """The failure this prevents: the model calls action='summarise' forever.

    The skill drives two action-taking tools, so an action is valid if EITHER
    implements it. Checking against only one enum would reject legitimate
    research_personas calls.
    """
    import tools.research_personas as rp
    import tools.research_tools as rt
    import tools.research_sources as rs
    import tools.research_deck as rd

    referenced = set(re.findall(r'action="(\w+)"', raw))
    valid = (
        set(rt.RESEARCH_STATE_SCHEMA["parameters"]["properties"]["action"]["enum"])
        | set(rp.RESEARCH_PERSONAS_SCHEMA["parameters"]["properties"]["action"]["enum"])
        | set(rs.RESEARCH_SOURCES_SCHEMA["parameters"]["properties"]["action"]["enum"])
        | set(rd.RESEARCH_DECK_SCHEMA["parameters"]["properties"]["action"]["enum"])
    )
    invented = referenced - valid
    assert not invented, f"skill references non-existent actions: {sorted(invented)}"
    assert referenced, "skill documents no actions at all"


def test_skill_tells_the_agent_to_announce_the_persona(flat):
    """The lens must never be adopted silently — that is the ambient-chat rule
    personas.py records, and the only reason auto-selection is acceptable here."""
    assert "honour an override" in flat
    assert "never be silent" in flat


def test_skill_requires_reporting_unavailable_resources(flat):
    """A thin run must be visible as thin."""
    assert "resource_pack_unavailable" in flat


def test_skill_names_no_mode_the_tool_does_not_implement(raw):
    import tools.research_tools as rt

    referenced = set(re.findall(r"`(investigation|discovery|simulation|planning|market)`", raw))
    unknown = referenced - set(rt.RESEARCH_MODES)
    assert not unknown, f"skill references unknown modes: {sorted(unknown)}"


def test_all_five_modes_are_documented(flat):
    """Every mode the tool accepts needs a stated termination contract, or the
    model has no basis for choosing between them."""
    import tools.research_tools as rt

    for mode in rt.RESEARCH_MODES:
        assert mode in flat, f"mode {mode!r} is selectable but undocumented in the skill"


def test_the_floor_stated_in_the_skill_matches_the_code(flat):
    """If the skill quotes different thresholds than the gate enforces, the
    model plans against a floor that does not exist."""
    import tools.research_tools as rt

    c = rt.Criteria()
    assert f"{c.min_total_claims} claims" in flat
    assert f"{c.min_unique_sources} unique sources" in flat
    assert f"{int(c.min_high_confidence_ratio * 100)}%" in flat


def test_skill_documents_all_three_gate_outcomes(flat):
    """Two-outcome thinking is what produces a run that stops early or one that
    presents a budget-exhausted partial as complete."""
    assert "sufficient" in flat
    assert "budget remains" in flat
    assert "budget spent" in flat
    assert "limitations" in flat


def test_skill_forbids_templating_the_deck(flat):
    """Owner directive: decks are composed per run, never filled from a template."""
    assert "no template" in flat


def test_skill_requires_self_contained_offline_deck(flat):
    assert "no network" in flat
    assert "inline" in flat


def test_skill_is_registered_under_the_research_category(raw):
    assert SKILL_PATH.parent.parent.name == "research"
