#!/usr/bin/env python3
"""
Domain routing (B8) — resolve a task kind to the right AiUtils model.

The agent knows what it can call (B3 catalog) but not which model suits the job.
Picking blind means paying frontier prices for a summarisation, or sending an
image request to a text-only model and getting an error back.

**This does NOT classify the user's request.** The ``task_kind`` is chosen by the
model itself from a fixed enum in the tool schema — this module only maps that
decision onto candidate models. There is deliberately no keyword, substring or
regex matching against user text anywhere here. Cue-list routing pre-empts the
reasoning model and produces exactly the failures it is meant to avoid: an
enterprise "AI transformation platform" request hijacked to image editing
because it contained "transform". Intent stays with the LLM; this is a lookup
keyed on a decision already made.

Profiles describe **capability requirements**, not fixed model ids. Hardcoding
ids would rot the moment the catalog changes; resolving requirements against the
live catalog keeps recommendations correct as models come and go.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

from tools import aiutils_client
from tools.registry import registry, tool_error

# Candidates considered per task before ranking. Enough to survive a few
# unavailable models without pulling the whole catalog on every call.
CANDIDATE_POOL = 40
DEFAULT_SUGGESTIONS = 3
MAX_SUGGESTIONS = 10

# Each profile is a set of catalog filters plus a ranking bias.
#   category  — catalog category to search
#   requires  — capability flags that must be true
#   prefer    — "cost" ranks cheapest first; "quality" ranks richest first
#   why       — shown to the model so its choice is informed, not blind
TASK_PROFILES: dict[str, dict[str, Any]] = {
    "text_reasoning": {
        "category": "text",
        "prefer": "quality",
        "why": "Multi-step reasoning, analysis, planning. Favours capability over price.",
    },
    "text_fast_cheap": {
        "category": "text",
        "prefer": "cost",
        "why": "High-volume or low-stakes text: summarising, classifying, extracting, reformatting.",
    },
    "code": {
        "category": "text",
        "prefer": "quality",
        "why": "Writing or reviewing code. Favours stronger instruction-following.",
    },
    "vision": {
        "category": "text",
        "requires": ("vision",),
        "prefer": "quality",
        "why": "Any task where an image is an INPUT — reading a screenshot, describing a photo.",
    },
    "image_generation": {
        "category": "image",
        "prefer": "quality",
        "why": "Producing an image from a prompt. Image as OUTPUT, not input.",
    },
    "video_generation": {
        "category": "video",
        "prefer": "quality",
        "why": "Producing video from a prompt or an image.",
    },
    "audio_generation": {
        "category": "audio",
        "prefer": "quality",
        "why": "Speech, music or sound effects as output.",
    },
    "three_d_generation": {
        "category": "3d",
        "prefer": "quality",
        "why": "3D assets and meshes.",
    },
    "embedding": {
        "category": "embedding",
        "prefer": "cost",
        "why": "Vectorising text for similarity. Note the RAG tools embed for free — "
               "use aiutils_rag_* rather than paying for this directly.",
    },
}


def _rank_key(model: dict, prefer: str):
    """Sort key for a candidate.

    Free models sort first when optimising for cost; a model with no price is
    treated as most expensive when optimising for quality, so an unpriced entry
    never silently wins on either axis.
    """
    dt = model.get("dt_cost")
    if prefer == "cost":
        # Unpriced -> very large, so it does not masquerade as free.
        return (0 if model.get("free") else 1, dt if dt is not None else 10**9)
    return (0 if not model.get("free") else 1, -(dt if dt is not None else 0))


def _compact(model) -> dict:
    pricing = getattr(model, "pricing", None)
    caps = getattr(model, "capabilities", None)
    return {
        "id": getattr(model, "id", None),
        "label": getattr(model, "label", None) or getattr(model, "name", None),
        "vendor": getattr(model, "vendor", None),
        "modality": getattr(model, "modality", None),
        "dt_cost": getattr(pricing, "dt_cost", None) if pricing else None,
        "free": bool(getattr(pricing, "free", False)) if pricing else False,
        "vision": bool(getattr(caps, "vision", False)) if caps else False,
    }


ROUTER_SCHEMA = {
    "name": "aiutils_model_for_task",
    "description": (
        "Recommend AiUtils models for a kind of task, ranked, with DT costs. "
        "Call this when you need to pick a model and are not sure which suits "
        "the job — for example before aiutils_generate. YOU decide which "
        "task_kind applies from the task at hand; this tool does not inspect "
        "the user's wording."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_kind": {
                "type": "string",
                "enum": sorted(TASK_PROFILES),
                "description": "The kind of work the model must do. Choose the closest match.",
            },
            "limit": {
                "type": "integer",
                "description": f"How many suggestions (default {DEFAULT_SUGGESTIONS}, max {MAX_SUGGESTIONS}).",
            },
            "free_only": {
                "type": "boolean",
                "description": "Return only models that cost nothing.",
            },
        },
        "required": ["task_kind"],
    },
}


def _handle_route(args, **kw):
    task_kind = (args.get("task_kind") or "").strip()
    if not task_kind:
        return tool_error("task_kind is required")

    profile = TASK_PROFILES.get(task_kind)
    if profile is None:
        return tool_error(
            f"Unknown task_kind {task_kind!r}. Valid kinds: {', '.join(sorted(TASK_PROFILES))}"
        )

    try:
        limit = int(args.get("limit") or DEFAULT_SUGGESTIONS)
    except (TypeError, ValueError):
        limit = DEFAULT_SUGGESTIONS
    limit = max(1, min(limit, MAX_SUGGESTIONS))

    try:
        client = aiutils_client.get_client()
        payload = client.models.list(category=profile["category"], page_size=CANDIDATE_POOL)
    except Exception as exc:
        logger.warning("aiutils_model_for_task failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="model routing")
        return tool_error(handled or f"Could not load the model catalog: {exc}")

    candidates = [_compact(m) for m in (getattr(payload, "data", None) or [])]

    for capability in profile.get("requires", ()):
        candidates = [c for c in candidates if c.get(capability)]
    if args.get("free_only"):
        candidates = [c for c in candidates if c.get("free")]

    candidates.sort(key=lambda c: _rank_key(c, profile.get("prefer", "quality")))
    suggestions = candidates[:limit]

    return json.dumps(
        {
            "task_kind": task_kind,
            "rationale": profile["why"],
            "ranked_by": profile.get("prefer", "quality"),
            "suggestions": suggestions,
            "count": len(suggestions),
            "note": (
                f"No model in category {profile['category']!r} matched these "
                "requirements. Use aiutils_model_catalog to browse what exists."
                if not suggestions
                else "Ranked suggestions — pass a chosen id to aiutils_generate."
            ),
        },
        ensure_ascii=False,
        default=str,
    )


registry.register(
    name="aiutils_model_for_task",
    toolset="aiutils",
    schema=ROUTER_SCHEMA,
    handler=_handle_route,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🧭",
)
