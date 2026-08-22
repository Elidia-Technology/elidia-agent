#!/usr/bin/env python3
"""
Schema → widget mapper.

Maps a tool's input JSON Schema to structured "widget" descriptors the agent
can render as `clarify` questions/choices — so required (and optional) inputs
are collected from the user through the platform's native prompt UI, instead
of the model guessing or fabricating values.

Pure and side-effect-free: it takes a schema dict and returns plain dicts, so
it is usable from any tool or the agent loop and trivially testable. It is a
helper library (no ``registry.register`` call), not a tool itself.
"""

from __future__ import annotations

from typing import Optional

# Mirrors ``tools.clarify_tool.MAX_CHOICES`` — keep the two in sync so a mapped
# enum never exceeds the number of choices the clarify UI can render.
MAX_CHOICES = 4


def _humanize(field: str) -> str:
    """``'aspect_ratio'`` → ``'aspect ratio'`` / ``'aspect-ratio'`` → same."""
    return field.replace("_", " ").replace("-", " ").strip().lower()


def _choices_for(prop: dict) -> Optional[list]:
    """Derive multiple-choice options for a property, or ``None`` (open-ended)."""
    enum = prop.get("enum")
    if isinstance(enum, list) and enum:
        return [str(value) for value in enum[:MAX_CHOICES]]

    if prop.get("type") == "boolean":
        return ["yes", "no"]

    # Everything else (free-form strings, numbers, uri/email formats, arrays,
    # objects) is open-ended — the user types a value rather than picking one.
    return None


def schema_to_widgets(schema: dict) -> list:
    """Map a tool input JSON Schema to a list of widget descriptors.

    Each descriptor has ``field``, ``type``, ``required``, ``question``
    (description text when present, else the humanized field name),
    ``choices`` (derived from ``enum`` / ``boolean``, else ``None``), and
    ``default``. Returns ``[]`` for a missing/malformed schema.
    """
    if not isinstance(schema, dict):
        return []

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []

    required = set(schema.get("required") or [])
    widgets = []
    for field, prop in properties.items():
        if not isinstance(prop, dict):
            continue
        widgets.append(
            {
                "field": field,
                "type": prop.get("type", "string"),
                "required": field in required,
                "question": prop.get("description") or _humanize(field),
                "choices": _choices_for(prop),
                "default": prop.get("default"),
            }
        )
    return widgets


def build_clarify_prompts(schema: dict, only_required: bool = False) -> list:
    """Produce ``{field, question, choices}`` prompts for the ``clarify`` tool.

    ``only_required=True`` restricts the result to required fields, which is
    the usual case: ask the user only for what the tool cannot run without.
    """
    prompts = []
    for widget in schema_to_widgets(schema):
        if only_required and not widget["required"]:
            continue
        prompts.append(
            {
                "field": widget["field"],
                "question": widget["question"],
                "choices": widget["choices"],
            }
        )
    return prompts
