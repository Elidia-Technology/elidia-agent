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


def _enum_values(prop: dict) -> Optional[list]:
    """Collect enum values from a property, looking through ``anyOf``/``oneOf``.

    Real-world tool schemas rarely put ``enum`` at the top level of a property.
    The common optional-enum shape is
    ``{"anyOf": [{"enum": [...]}, {"type": "null"}]}``; ``oneOf`` is used the
    same way. Reading only ``prop["enum"]`` silently treats those as free text,
    so the user types a value that then fails validation.

    ``$ref`` is deliberately not followed: resolving it needs the whole
    document (and can cycle), and the caller passes a single property dict.
    A ``$ref`` property stays open-ended rather than being guessed at.
    """
    enum = prop.get("enum")
    if isinstance(enum, list) and enum:
        return list(enum)

    for key in ("anyOf", "oneOf"):
        variants = prop.get(key)
        if not isinstance(variants, list):
            continue
        collected: list = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            # Skip the null branch that makes such a field optional.
            if variant.get("type") == "null":
                continue
            sub = variant.get("enum")
            if isinstance(sub, list):
                collected.extend(sub)
        if collected:
            return collected

    return None


def _choices_for(prop: dict) -> Optional[list]:
    """Derive multiple-choice options for a property, or ``None`` (open-ended).

    When an enum has more options than the clarify UI can render, the options
    are **not** truncated to the first :data:`MAX_CHOICES`: silently dropping
    the rest makes those values unreachable — the user cannot pick what is not
    shown. Such a field becomes open-ended instead, and
    :func:`_question_for` lists the permitted values in the question text so
    the user still knows what is valid.
    """
    enum = _enum_values(prop)
    if enum:
        if len(enum) > MAX_CHOICES:
            return None
        return [str(value) for value in enum]

    if prop.get("type") == "boolean":
        return ["yes", "no"]

    # Everything else (free-form strings, numbers, uri/email formats, arrays,
    # objects) is open-ended — the user types a value rather than picking one.
    return None


def _question_for(field: str, prop: dict) -> str:
    """Question text for a property, naming the valid values when they cannot
    all be shown as choices."""
    question = prop.get("description") or _humanize(field)
    enum = _enum_values(prop)
    if enum and len(enum) > MAX_CHOICES:
        allowed = ", ".join(str(value) for value in enum)
        question = f"{question} (one of: {allowed})"
    return question


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
                "question": _question_for(field, prop),
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
