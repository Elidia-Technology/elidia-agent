#!/usr/bin/env python3
"""
AiUtils portal-tool tools — list tool genres and execute a portal tool by slug
through the AiUtils Developer API.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

from tools import aiutils_client
from tools.registry import registry, tool_error

TOOL_GENRES_SCHEMA = {
    "name": "aiutils_tool_genres",
    "description": (
        "List the tool genres/categories available on the AiUtils Developer API."
    ),
    "parameters": {"type": "object", "properties": {}},
}

TOOL_EXECUTE_SCHEMA = {
    "name": "aiutils_tool_execute",
    "description": (
        "Execute a portal tool by its slug through the AiUtils Developer API. "
        "The Developer API surfaces portal tools (image/video/audio processing, "
        "text, etc.) behind a unified execute endpoint."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_slug": {
                "type": "string",
                "description": "The tool slug to execute.",
            },
            "inputs": {
                "type": "object",
                "description": "Input parameters for the tool.",
            },
        },
        "required": ["tool_slug"],
    },
}


OPEN_TOOL_SCHEMA = {
    "name": "aiutils_open_tool",
    "description": (
        "Hand the user off to an interactive AiUtils tool (image/video/audio/"
        "logo editors and studios) by opening its portal page. Use this for any "
        "editing or creative request that needs a canvas — layers, a timeline, "
        "drag-and-drop, live preview — instead of naming external software. "
        "Returns a link rendered for the surface the user is on."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_slug": {
                "type": "string",
                "description": (
                    "Slug of the tool to open, e.g. 'image-editor', "
                    "'video-studio', 'music-studio'. Use aiutils_tool_genres "
                    "to find one."
                ),
            },
        },
        "required": ["tool_slug"],
    },
}


def _handle_open_tool(args, **kw):
    slug = (args.get("tool_slug") or "").strip()
    if not slug:
        return tool_error("tool_slug is required")

    from tools import aiutils_redirect

    payload = aiutils_redirect.handoff_payload(slug)
    # No credit guard and no wallet read: opening a page costs nothing. Work
    # the user then does inside the studio is billed by the portal, on the
    # portal's own terms.
    return json.dumps(payload, ensure_ascii=False, default=str)


def _handle_genres(args, **kw):
    try:
        client = aiutils_client.get_client()
        result = client.tools.genres()
    except Exception as exc:
        logger.warning("aiutils_tool_genres failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="tool listing")
        return tool_error(handled or f"Could not list genres: {exc}")
    return json.dumps(result, ensure_ascii=False, default=str)


def _handle_execute(args, **kw):
    tool_slug = (args.get("tool_slug") or "").strip()
    if not tool_slug:
        return tool_error("tool_slug is required")
    inputs = args.get("inputs") or {}

    # Interactive studios (image-editor, video-studio, music-studio, ...) have
    # no headless execution — the Developer API marks them execution_mode
    # "redirect". Posting to /execute for one returns an opaque failure for a
    # tool the user owns and could have opened in a click, so hand off instead.
    #
    # Deliberately BEFORE the credit guard: reading the wallet for work that
    # cannot happen is a round trip spent to arrive at the same answer.
    try:
        from tools import aiutils_redirect

        if aiutils_redirect.is_redirect_tool(tool_slug):
            return json.dumps(
                aiutils_redirect.handoff_payload(tool_slug),
                ensure_ascii=False, default=str,
            )
    except Exception as exc:
        # An unreachable catalog must not block a call tool that was working.
        logger.debug("Redirect check skipped for %s: %s", tool_slug, exc)

    # Portal tool execution is billed — the gateway proxy for
    # /v1/tools/{slug}/execute states "Portal handles credit deduction". Tool
    # slugs are not catalog models, so they cannot be priced up-front; the
    # guard degrades to a balance check rather than being skipped.
    guard = aiutils_client.check_spend_allowed(client=None)
    if not guard.get("ok"):
        return tool_error(guard.get("error", "Credit guard failed"))

    try:
        client = guard["client"]
        result = client.tools.execute(tool_slug, **inputs)
    except Exception as exc:
        logger.warning("aiutils_tool_execute failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="tool execution")
        return tool_error(handled or f"Tool execution failed: {exc}")

    # Portal tool slugs 404 on /v1/pricing/estimate, so this is the ONLY way
    # their cost is ever known. Recording it is what lets the next run warn
    # before spending instead of after.
    try:
        from tools import aiutils_cost_memory

        aiutils_cost_memory.record_from_client(
            aiutils_cost_memory.tool_key(tool_slug), client,
        )
    except Exception as exc:  # pragma: no cover - never load-bearing
        logger.debug("Could not record observed cost for %s: %s", tool_slug, exc)

    return json.dumps(result, ensure_ascii=False, default=str)


registry.register(
    name="aiutils_tool_genres",
    toolset="aiutils",
    schema=TOOL_GENRES_SCHEMA,
    handler=_handle_genres,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🗂️",
)

registry.register(
    name="aiutils_tool_execute",
    toolset="aiutils",
    schema=TOOL_EXECUTE_SCHEMA,
    handler=_handle_execute,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🔧",
)

registry.register(
    name="aiutils_open_tool",
    toolset="aiutils",
    schema=OPEN_TOOL_SCHEMA,
    handler=_handle_open_tool,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🔗",
)
