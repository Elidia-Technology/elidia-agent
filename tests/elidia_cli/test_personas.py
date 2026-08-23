"""Tests for built-in personality presets (B11).

/personality shipped with an empty preset map, so it listed nothing until a user
hand-wrote config. These cover the two things that matter: the built-ins are
well-formed for the consumer in cli.py, and a user's own persona is never
silently replaced by a shipped one.
"""

import pytest

from elidia_cli.personas import BUILTIN_PERSONALITIES, merge_personalities


class TestBuiltins:
    def test_ships_the_portal_persona_set(self):
        """Same names as backend/app/elidia/domain_personas.py, so a persona
        behaves consistently across Portal and CLI."""
        expected = {
            "legal", "medical", "creative", "business", "student",
            "engineering", "research_scientist", "writer", "trader", "musician",
        }
        assert set(BUILTIN_PERSONALITIES) == expected

    @pytest.mark.parametrize("name", sorted(BUILTIN_PERSONALITIES))
    def test_each_has_the_fields_cli_reads(self, name):
        """_resolve_personality_prompt reads system_prompt/tone/style; the
        listing reads description. A missing system_prompt would set an empty
        overlay and silently do nothing."""
        persona = BUILTIN_PERSONALITIES[name]
        assert persona["system_prompt"].strip(), f"{name} has no system_prompt"
        assert persona["description"].strip(), f"{name} has no description"

    @pytest.mark.parametrize("name", sorted(BUILTIN_PERSONALITIES))
    def test_description_fits_the_fixed_width_listing(self, name):
        """/personality prints `{name:<12} - {description}`; long text wraps
        and breaks the column."""
        assert len(BUILTIN_PERSONALITIES[name]["description"]) <= 80

    @pytest.mark.parametrize("name", sorted(BUILTIN_PERSONALITIES))
    def test_key_is_typeable_as_a_command_argument(self, name):
        """The key is what the user types after /personality."""
        assert name == name.lower()
        assert " " not in name

    def test_resolves_through_the_cli_helper_shape(self):
        """Mirrors _resolve_personality_prompt so a shape change is caught here
        rather than at runtime."""
        def resolve(value):
            if isinstance(value, dict):
                parts = [value.get("system_prompt", "")]
                if value.get("tone"):
                    parts.append(f'Tone: {value["tone"]}')
                if value.get("style"):
                    parts.append(f'Style: {value["style"]}')
                return "\n".join(p for p in parts if p)
            return str(value)

        for name, persona in BUILTIN_PERSONALITIES.items():
            prompt = resolve(persona)
            assert prompt.strip(), f"{name} resolved to an empty prompt"
            assert "Tone:" in prompt or "tone" not in persona


class TestMerge:
    def test_returns_builtins_when_user_has_none(self):
        assert merge_personalities({}) == BUILTIN_PERSONALITIES
        assert merge_personalities(None) == BUILTIN_PERSONALITIES

    def test_user_entry_wins_on_a_name_collision(self):
        """Upgrading must not overwrite a persona the user wrote themselves."""
        merged = merge_personalities({"legal": "my own legal persona"})
        assert merged["legal"] == "my own legal persona"

    def test_user_additions_are_kept_alongside_builtins(self):
        merged = merge_personalities({"pirate": "Arr."})
        assert merged["pirate"] == "Arr."
        assert "legal" in merged

    def test_does_not_mutate_the_builtins(self):
        """A merged copy leaking back into the module would let one session's
        config bleed into the next."""
        before = dict(BUILTIN_PERSONALITIES)
        merge_personalities({"legal": "override", "new": "x"})
        assert BUILTIN_PERSONALITIES == before


class TestSelectionStaysWithTheUser:
    """The portal pairs its persona map with an LLM classifier that picks one
    from the message. That is deliberately not ported: /personality is an
    explicit choice, and nothing here inspects user text."""

    def test_module_exposes_no_classifier(self):
        import elidia_cli.personas as personas

        exported = {n for n in dir(personas) if not n.startswith("_")}
        for banned in ("classify", "detect", "infer_persona", "PERSONA_CLASSIFIER_PROMPT"):
            assert banned not in exported

    def test_module_imports_no_regex_engine(self):
        import ast
        import inspect

        import elidia_cli.personas as personas

        tree = ast.parse(inspect.getsource(personas))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "re" not in imported
