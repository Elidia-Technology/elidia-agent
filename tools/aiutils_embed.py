#!/usr/bin/env python3
"""
AiUtils embeddings tool — generate text embeddings via the Developer API.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

from tools import aiutils_client
from tools.registry import registry, tool_error

EMBED_SCHEMA = {
    "name": "aiutils_embed",
    "description": (
        "Generate a text embedding vector via the AiUtils Developer API. "
        "Returns the model, vector dimensions, and number of vectors produced."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Embedding model, e.g. 'text-embedding-3-small'.",
            },
            "input": {
                "type": "string",
                "description": "Text to embed.",
            },
        },
        "required": ["input"],
    },
}


def _handle_embed(args, **kw):
    text = args.get("input", "")
    if not text:
        return tool_error("input is required")
    model = args.get("model") or "text-embedding-3-small"
    try:
        client = aiutils_client.get_client()
        result = client.embeddings.create(model=model, input=text)
    except Exception as exc:
        logger.warning("aiutils_embed failed: %s", exc)
        return tool_error(f"Embedding failed: {exc}")

    data = getattr(result, "data", []) or []
    dim = len(getattr(data[0], "embedding", []) or []) if data else 0
    return json.dumps(
        {
            "model": getattr(result, "model", model),
            "dimensions": dim,
            "vectors": len(data),
        },
        ensure_ascii=False,
    )


registry.register(
    name="aiutils_embed",
    toolset="aiutils",
    schema=EMBED_SCHEMA,
    handler=_handle_embed,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🧬",
)
