"""Portal media tools — 3D generation + the media-model catalog.

Two tools that only exist in portal provider mode (``provider: portal``):

``generate_3d``
    Generate a 3D model. Routed by :mod:`tools.portal_tool_proxy` to the
    portal's ``generate_3d`` (billed to the user's portal credits); there is no
    native 3D backend in the gateway, so outside portal mode the tool is not
    exposed (``check_fn`` returns False) and the handler returns a clear error.

``list_media_models``
    Read-only, unbilled. Fetches the portal's ``GET /agent-v2/v1/media/models``
    catalog so the agent can present a real 5-10 model choice (premium →
    economical) and pass the chosen ``id`` back as ``model`` to the media
    generation tools. It does NOT invent models — every entry returned comes
    straight from the portal's active ``fal_models`` rows.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

from tools.registry import registry, tool_error


def check_portal_media_requirements() -> bool:
    """These tools are portal-mode-only (no native 3D backend / catalog)."""
    logger.debug("Entered into check_portal_media_requirements")
    try:
        from tools.portal_tool_proxy import _is_portal_mode
        return _is_portal_mode()
    except Exception:
        return False


# ── generate_3d ─────────────────────────────────────────────────────

GENERATE_3D_SCHEMA: Dict[str, Any] = {
    "name": "generate_3d",
    "description": (
        "Generate a 3D model from a text description. Billed to the user's "
        "portal credits. Choose a specific model with `model` (an id from "
        "`list_media_models`) or omit it to auto-pick by quality tier."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed description of the 3D model (object, material, style).",
            },
            "quality": {
                "type": "string",
                "enum": ["economy", "standard", "premium"],
                "description": "Quality tier when no explicit model is chosen.",
            },
            "model": {
                "type": "string",
                "description": "Explicit model id from `list_media_models`. Omit to auto-pick.",
            },
        },
        "required": ["prompt"],
    },
}


def _handle_generate_3d(args, **kw) -> str:
    prompt = args.get("prompt", "")
    if not prompt:
        return tool_error("prompt is required for 3D generation")
    # In portal mode the proxy intercepts `generate_3d` before this handler.
    # Reaching here means the tool ran without a portal proxy — no native 3D.
    return json.dumps({
        "success": False,
        "error": (
            "3D generation is only available through the portal. "
            "Configure the gateway with `provider: portal` to enable it."
        ),
    })


# ── list_media_models ───────────────────────────────────────────────

LIST_MEDIA_MODELS_SCHEMA: Dict[str, Any] = {
    "name": "list_media_models",
    "description": (
        "List the media generation models available through the portal, grouped "
        "by type (image/video/audio/3d) and ordered premium → economy. Use this "
        "to offer the user a real model choice before calling generate_image / "
        "generate_video / generate_audio / generate_3d, then pass the chosen "
        "`id` as the `model` argument. Read-only — does not spend credits."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "media_type": {
                "type": "string",
                "enum": ["image", "video", "audio", "3d"],
                "description": "Optional — return only one media type. Omit to return all four.",
            },
        },
    },
}


def _handle_list_media_models(args, **kw) -> str:
    media_type = (args.get("media_type") or "").strip() or None

    from tools.portal_tool_proxy import fetch_media_models

    data = fetch_media_models()
    if data is None:
        return tool_error(
            "Could not load the media model catalog from the portal. "
            "Confirm the gateway is running in portal provider mode."
        )

    if media_type:
        data = {media_type: data.get(media_type, [])}

    return json.dumps({"media_models": data}, ensure_ascii=False, default=str)


registry.register(
    name="generate_3d",
    toolset="image_gen",
    schema=GENERATE_3D_SCHEMA,
    handler=_handle_generate_3d,
    check_fn=check_portal_media_requirements,
    requires_env=[],
    is_async=False,
    emoji="🧊",
)

registry.register(
    name="list_media_models",
    toolset="image_gen",
    schema=LIST_MEDIA_MODELS_SCHEMA,
    handler=_handle_list_media_models,
    check_fn=check_portal_media_requirements,
    requires_env=[],
    is_async=False,
    emoji="📚",
)
