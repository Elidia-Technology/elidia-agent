"""Tests for the AiUtils skill packs (B10).

A skill is a contract with the agent: its frontmatter declares tools the agent
will try to call. A skill naming a tool that does not exist is worse than no
skill — the agent reads it as available, plans around it, and fails at call
time. So the load-bearing test is that every declared tool actually resolves in
the registry.
"""

import pathlib
import re

import pytest
import yaml

SKILLS_DIR = pathlib.Path(__file__).resolve().parents[2] / "skills" / "aiutils"
TOOLS_DIR = pathlib.Path(__file__).resolve().parents[2] / "tools"

SKILL_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))


def _frontmatter(path: pathlib.Path) -> dict:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert match, f"{path} has no YAML frontmatter"
    return yaml.safe_load(match.group(1))


def _registered_tool_names() -> set[str]:
    names: set[str] = set()
    for module in TOOLS_DIR.glob("*.py"):
        names |= set(re.findall(r'name="([a-z_]+)"', module.read_text()))
    return names


def test_skill_pack_exists():
    assert SKILL_FILES, "no AiUtils skills found"


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
class TestSkillContract:
    def test_frontmatter_parses(self, path):
        assert _frontmatter(path)

    def test_required_fields_present(self, path):
        fm = _frontmatter(path)
        for field in ("name", "description", "version", "license"):
            assert fm.get(field), f"{path.parent.name} missing {field}"

    def test_every_declared_tool_actually_exists(self, path):
        """The one that matters. A skill promising a tool the agent cannot call
        makes the agent plan around a capability it does not have."""
        fm = _frontmatter(path)
        declared = (fm.get("prerequisites") or {}).get("tools", [])
        assert declared, f"{path.parent.name} declares no tools"
        missing = sorted(set(declared) - _registered_tool_names())
        assert not missing, f"{path.parent.name} references non-existent tools: {missing}"

    def test_name_matches_directory(self, path):
        """The loader keys on directory; a mismatch makes a skill hard to find."""
        assert _frontmatter(path)["name"].endswith(path.parent.name)

    def test_has_a_when_to_use_section(self, path):
        """Without it the agent cannot judge applicability and either never
        invokes the skill or invokes it for everything."""
        assert "## When to use this skill" in path.read_text()

    def test_related_skills_point_at_real_siblings(self, path):
        fm = _frontmatter(path)
        related = ((fm.get("metadata") or {}).get("elidia") or {}).get("related_skills", [])
        known = {_frontmatter(p)["name"] for p in SKILL_FILES}
        for ref in related:
            assert ref in known, f"{path.parent.name} references unknown skill {ref!r}"


class TestSafetyBoundaries:
    """The medical and legal packs carry refusals that must not quietly erode
    into advice."""

    def test_medical_skill_refuses_to_diagnose(self):
        text = (SKILLS_DIR / "medical-research" / "SKILL.md").read_text()
        assert "does not diagnose" in text
        assert "seek immediate medical care" in text, "must handle urgent presentations"

    def test_legal_skill_states_it_is_not_advice(self):
        text = (SKILLS_DIR / "legal-analysis" / "SKILL.md").read_text()
        assert "not legal advice" in text
        assert "Never fabricate case law" in text

    def test_generation_skills_require_cost_confirmation(self):
        """Generation is billed; the user should not learn the price afterwards."""
        for name in ("image-generation", "video-generation", "audio-generation"):
            text = (SKILLS_DIR / name / "SKILL.md").read_text()
            assert "aiutils_estimate" in text, f"{name} must estimate before spending"

    def test_knowledge_base_states_it_is_free(self):
        """Users otherwise assume ingest is billed and avoid using it."""
        text = (SKILLS_DIR / "knowledge-base" / "SKILL.md").read_text()
        assert "Free" in text or "free" in text
