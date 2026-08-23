"""Tests for the JSON-Schema → widget/clarify mapper."""

from tools import schema_widgets
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
    def test_oversized_enum_is_open_ended_not_truncated(self):
        """Changed 2026-08-22 (AIUT-2948). This previously asserted
        ``== ["a", "b", "c", "d"]`` — i.e. it locked in silent truncation to
        MAX_CHOICES, which made values beyond the fourth impossible for the
        user to select. Offering a misleading partial list is worse than
        offering none: the field is now open-ended and the permitted values are
        named in the question text instead."""
        prop = {"type": "string", "enum": ["a", "b", "c", "d", "e"]}
        assert _choices_for(prop) is None

    def test_enum_that_fits_is_offered_whole(self):
        prop = {"type": "string", "enum": ["a", "b", "c", "d"]}
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


class TestEnumsThatDoNotFitAsChoices:
    """AIUT-2948: enums larger than MAX_CHOICES were truncated to the first
    four, making the remaining values unreachable through the clarify UI."""

    SCHEMA = {
        "type": "object",
        "properties": {
            "aspect_ratio": {
                "type": "string",
                "description": "Output aspect ratio",
                "enum": ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9"],
            }
        },
        "required": ["aspect_ratio"],
    }

    def test_large_enum_is_not_silently_truncated(self):
        widget = schema_widgets.schema_to_widgets(self.SCHEMA)[0]
        # Either every value is offered, or none are — never a silent subset.
        assert widget["choices"] is None

    def test_large_enum_values_are_named_in_the_question(self):
        widget = schema_widgets.schema_to_widgets(self.SCHEMA)[0]
        for value in self.SCHEMA["properties"]["aspect_ratio"]["enum"]:
            assert value in widget["question"], f"{value} must remain discoverable"

    def test_small_enum_still_renders_every_value_as_a_choice(self):
        schema = {
            "type": "object",
            "properties": {"size": {"type": "string", "enum": ["small", "large"]}},
        }
        widget = schema_widgets.schema_to_widgets(schema)[0]
        assert widget["choices"] == ["small", "large"]


class TestAnyOfOneOfEnums:
    """AIUT-2948: the mapper only read a top-level ``enum``, so the common
    optional-enum shape degraded to free text."""

    def test_anyof_optional_enum_is_recognised(self):
        schema = {
            "type": "object",
            "properties": {
                "quality": {
                    "description": "Render quality",
                    "anyOf": [{"enum": ["draft", "final"]}, {"type": "null"}],
                }
            },
        }
        widget = schema_widgets.schema_to_widgets(schema)[0]
        assert widget["choices"] == ["draft", "final"], "null branch must be ignored"

    def test_oneof_enum_is_recognised(self):
        schema = {
            "type": "object",
            "properties": {"mode": {"oneOf": [{"enum": ["fast", "slow"]}]}},
        }
        widget = schema_widgets.schema_to_widgets(schema)[0]
        assert widget["choices"] == ["fast", "slow"]

    def test_ref_property_stays_open_ended(self):
        """$ref cannot be resolved from a single property dict — it must stay
        open-ended rather than being guessed at."""
        schema = {"type": "object", "properties": {"style": {"$ref": "#/defs/Style"}}}
        widget = schema_widgets.schema_to_widgets(schema)[0]
        assert widget["choices"] is None
