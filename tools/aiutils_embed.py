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


def _learn_cost(client, key: str) -> None:
    """Record what the call that just ran actually cost.

    The gateway reports it on every response (X-DT-Consumed); without this it
    was read and dropped, so a tool the pricing catalog cannot quote stayed
    unpriceable forever no matter how many times the user paid for it.
    Best-effort by design: a bookkeeping failure must never turn a successful,
    already-billed call into an error.
    """
    try:
        from tools import aiutils_cost_memory

        aiutils_cost_memory.record_from_client(key, client)
    except Exception as exc:  # pragma: no cover - never load-bearing
        logger.debug("Could not record observed cost for %s: %s", key, exc)

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

    # Embeddings are billed on token usage. Guard before spending; when the
    # model carries catalog pricing this is an exact estimate, otherwise it
    # falls back to a balance check.
    guard = aiutils_client.check_spend_allowed(model, {"input": text})
    if not guard.get("ok"):
        return tool_error(guard.get("error", "Credit guard failed"))

    try:
        client = guard["client"]
        result = client.embeddings.create(model=model, input=text)
    except Exception as exc:
        logger.warning("aiutils_embed failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="embedding")
        return tool_error(handled or f"Embedding failed: {exc}")

    from tools.aiutils_cost_memory import model_key

    _learn_cost(client, model_key(model))

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
