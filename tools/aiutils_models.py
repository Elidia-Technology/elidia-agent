#!/usr/bin/env python3
"""
AiUtils API-knowledge layer (B3).

The agent cannot reason about what it is able to call unless it can see the
catalog. Without this it either guesses model ids, or fabricates parameters
that the Developer API then rejects. These two tools close that gap:

``aiutils_model_catalog``
    Discovery. Search/filter the catalog and get back a compact listing —
    enough to choose a model, not enough to flood the context window.

``aiutils_model_info``
    Precision. One model's full record, including its ``input_schema``, plus
    the schema mapped through :mod:`tools.schema_widgets` into clarify-ready
    widgets so required inputs can be collected from the user rather than
    invented.

Both are **read-only and unbilled** — ``GET /v1/models`` and
``GET /v1/models/{id}`` do not spend DT — so unlike the generation tools they
deliberately do NOT run the credit guard. Adding one here would be wrong: it
would refuse discovery when a wallet is empty, which is exactly when a user
most needs to see what things cost.

Catalog responses are cached in-process with a short TTL. The catalog changes
rarely but the agent may consult it several times inside one turn, and each
call is a network round-trip.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

from tools import aiutils_client, schema_widgets
from tools.registry import registry, tool_error

# Long enough to cover a multi-step turn, short enough that a newly-enabled
# model shows up without restarting the agent.
CACHE_TTL_SECONDS = 300
# Keeps a broad "what can you do?" answer from swamping the context window.
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

_cache: dict[tuple, tuple[float, Any]] = {}


def _cached(key: tuple, produce):
    """Return a cached value for ``key``, computing it via ``produce`` on miss."""
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and hit[0] > now:
        logger.debug("aiutils catalog cache hit: %s", key)
        return hit[1]
    value = produce()
    _cache[key] = (now + CACHE_TTL_SECONDS, value)
    return value


def _clear_cache() -> None:
    """Drop every cached catalog response (used by tests)."""
    _cache.clear()


CATALOG_SCHEMA = {
    "name": "aiutils_model_catalog",
    "description": (
        "Discover which AiUtils models are available to call. Filter by category "
        "(e.g. image, video, audio, 3d, text), vendor, or a free-text search. "
        "Returns a compact listing with id, label, modality, DT cost and "
        "capabilities. Use aiutils_model_info for one model's full parameters."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "Filter by category, e.g. 'image'."},
            "vendor": {"type": "string", "description": "Filter by vendor."},
            "search": {"type": "string", "description": "Free-text search over model names."},
            "limit": {
                "type": "integer",
                "description": f"Max models to return (default {DEFAULT_LIMIT}, max {MAX_LIMIT}).",
            },
        },
    },
}

INFO_SCHEMA = {
    "name": "aiutils_model_info",
    "description": (
        "Get one AiUtils model's full record — pricing, capabilities, and its "
        "input schema — plus that schema mapped into clarify-ready widgets. Call "
        "this before aiutils_generate so required parameters are collected from "
        "the user instead of guessed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model_id": {"type": "string", "description": "Model id, e.g. 'fal:flux/dev'."},
        },
        "required": ["model_id"],
    },
}


def _compact(model) -> dict:
    """Reduce a ModelInfo to the fields needed to choose between models."""
    pricing = getattr(model, "pricing", None)
    caps = getattr(model, "capabilities", None)
    return {
        "id": getattr(model, "id", None),
        "label": getattr(model, "label", None) or getattr(model, "name", None),
        "vendor": getattr(model, "vendor", None),
        "modality": getattr(model, "modality", None),
        "category": getattr(model, "category", None),
        "dt_cost": getattr(pricing, "dt_cost", None) if pricing else None,
        "free": bool(getattr(pricing, "free", False)) if pricing else False,
        "vision": bool(getattr(caps, "vision", False)) if caps else False,
        "async": bool(getattr(model, "is_async", False)),
    }


def _handle_catalog(args, **kw):
    category = (args.get("category") or "").strip() or None
    vendor = (args.get("vendor") or "").strip() or None
    search = (args.get("search") or "").strip() or None

    try:
        limit = int(args.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    key = ("catalog", category, vendor, search, limit)
    try:
        payload = _cached(
            key,
            lambda: aiutils_client.get_client().models.list(
                category=category, vendor=vendor, search=search, page_size=limit
            ),
        )
    except Exception as exc:
        logger.warning("aiutils_model_catalog failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="catalog lookup")
        return tool_error(handled or f"Could not load the model catalog: {exc}")

    models = [_compact(m) for m in (getattr(payload, "data", None) or [])]
    return json.dumps(
        {
            "models": models,
            "returned": len(models),
            "total": getattr(payload, "total", len(models)),
            "filters": {"category": category, "vendor": vendor, "search": search},
        },
        ensure_ascii=False,
        default=str,
    )


def _handle_model_info(args, **kw):
    model_id = (args.get("model_id") or "").strip()
    if not model_id:
        return tool_error("model_id is required")

    key = ("info", model_id)
    try:
        info = _cached(
            key, lambda: aiutils_client.get_client().models.get_info(model_id)
        )
    except Exception as exc:
        logger.warning("aiutils_model_info failed for %r: %s", model_id, exc)
        return tool_error(f"Could not load model {model_id}: {exc}")

    input_schema = getattr(info, "input_schema", None)
    # Map the schema into widgets so the caller can ask for required inputs
    # through the native clarify prompt rather than inventing values.
    widgets = schema_widgets.schema_to_widgets(input_schema) if input_schema else []
    required_prompts = (
        schema_widgets.build_clarify_prompts(input_schema, only_required=True)
        if input_schema
        else []
    )

    payload = _compact(info)
    payload.update(
        {
            "description": getattr(info, "description", None),
            "input_schema": input_schema,
            "output_schema": getattr(info, "output_schema", None),
            "widgets": widgets,
            "required_prompts": required_prompts,
        }
    )

    # What this model has actually cost this user, when it has been run before.
    # The catalog gives a price; this gives the bill. They differ once input
    # size is involved, and the second one is the one a user recognises.
    try:
        from tools import aiutils_cost_memory

        observed = aiutils_cost_memory.describe(aiutils_cost_memory.model_key(model_id))
        if observed:
            payload["observed_cost"] = observed
    except Exception as exc:  # never let bookkeeping break a catalog read
        logger.debug("Could not read observed cost for %r: %s", model_id, exc)

    return json.dumps(payload, ensure_ascii=False, default=str)


registry.register(
    name="aiutils_model_catalog",
    toolset="aiutils",
    schema=CATALOG_SCHEMA,
    handler=_handle_catalog,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="📚",
)

registry.register(
    name="aiutils_model_info",
    toolset="aiutils",
    schema=INFO_SCHEMA,
    handler=_handle_model_info,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🔎",
)
