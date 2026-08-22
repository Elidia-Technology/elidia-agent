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


def _handle_genres(args, **kw):
    try:
        client = aiutils_client.get_client()
        result = client.tools.genres()
    except Exception as exc:
        logger.warning("aiutils_tool_genres failed: %s", exc)
        return tool_error(f"Could not list genres: {exc}")
    return json.dumps(result, ensure_ascii=False, default=str)


def _handle_execute(args, **kw):
    tool_slug = (args.get("tool_slug") or "").strip()
    if not tool_slug:
        return tool_error("tool_slug is required")
    inputs = args.get("inputs") or {}
    try:
        client = aiutils_client.get_client()
        result = client.tools.execute(tool_slug, **inputs)
    except Exception as exc:
        logger.warning("aiutils_tool_execute failed: %s", exc)
        return tool_error(f"Tool execution failed: {exc}")
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
