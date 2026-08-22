"""Tests for the JSON-Schema → widget/clarify mapper."""

from tools.schema_widgets import (
    _choices_for,
    _humanize,
    build_clarify_prompts,
    schema_to_widgets,
)

SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string", "description": "The image description."},
        "aspect_ratio": {
            "type": "string",
            "enum": ["landscape", "portrait", "square"],
            "default": "square",
        },
        "watermark": {"type": "boolean", "description": "Add a watermark?"},
        "seed": {"type": "integer"},
    },
    "required": ["prompt"],
}


class TestHumanize:
    def test_snake_case(self):
        assert _humanize("aspect_ratio") == "aspect ratio"

    def test_kebab_case(self):
        assert _humanize("image-url") == "image url"

    def test_single_word(self):
        assert _humanize("prompt") == "prompt"


class TestChoicesFor:
    def test_enum_capped(self):
        prop = {"type": "string", "enum": ["a", "b", "c", "d", "e"]}
        assert _choices_for(prop) == ["a", "b", "c", "d"]

    def test_boolean(self):
        assert _choices_for({"type": "boolean"}) == ["yes", "no"]

    def test_open_ended(self):
        assert _choices_for({"type": "string"}) is None
        assert _choices_for({"type": "integer"}) is None


class TestSchemaToWidgets:
    def test_maps_fields(self):
        widgets = schema_to_widgets(SAMPLE_SCHEMA)
        by_field = {w["field"]: w for w in widgets}
        assert set(by_field) == {"prompt", "aspect_ratio", "watermark", "seed"}

    def test_required_flag(self):
        by_field = {w["field"]: w for w in schema_to_widgets(SAMPLE_SCHEMA)}
        assert by_field["prompt"]["required"] is True
        assert by_field["seed"]["required"] is False

    def test_question_from_description(self):
        by_field = {w["field"]: w for w in schema_to_widgets(SAMPLE_SCHEMA)}
        assert by_field["prompt"]["question"] == "The image description."
        # no description → humanized field name
        assert by_field["seed"]["question"] == "seed"

    def test_choices_and_default(self):
        by_field = {w["field"]: w for w in schema_to_widgets(SAMPLE_SCHEMA)}
        assert by_field["aspect_ratio"]["choices"] == ["landscape", "portrait", "square"]
        assert by_field["aspect_ratio"]["default"] == "square"
        assert by_field["watermark"]["choices"] == ["yes", "no"]

    def test_missing_schema_returns_empty(self):
        assert schema_to_widgets(None) == []
        assert schema_to_widgets({}) == []
        assert schema_to_widgets({"type": "object"}) == []


class TestBuildClarifyPrompts:
    def test_all_fields(self):
        prompts = build_clarify_prompts(SAMPLE_SCHEMA)
        assert len(prompts) == 4

    def test_only_required(self):
        prompts = build_clarify_prompts(SAMPLE_SCHEMA, only_required=True)
        assert [p["field"] for p in prompts] == ["prompt"]
