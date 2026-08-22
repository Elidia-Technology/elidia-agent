#!/usr/bin/env python3
"""
AiUtils generation tools — submit image/video/audio/3D generations through
the AiUtils Developer API and pre-estimate their DT cost.

``aiutils_estimate`` is non-billed: it returns the estimated cost plus the
current wallet balance so the agent can confirm with the user before spending.
``aiutils_generate`` is billed: it re-runs the credit guard and refuses to
submit when the wallet cannot cover the estimate. Both submit asynchronously
(``wait_for_completion=False``) so a sync tool handler never blocks the event
loop for the full generation; ``aiutils_generation_get`` polls a submitted id.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

from tools import aiutils_client
from tools.registry import registry, tool_error

GENERATE_SCHEMA = {
    "name": "aiutils_generate",
    "description": (
        "Submit an image, video, audio, or 3D generation through the AiUtils "
        "Developer API. Billed in DT credits; this tool refuses to run when "
        "the wallet balance cannot cover the estimated cost. Submits "
        "asynchronously and returns the generation id + status; poll with "
        "aiutils_generation_get."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Model ID from the AiUtils catalog, e.g. 'elidia-2:flux/dev'.",
            },
            "parameters": {
                "type": "object",
                "description": "Model-specific input parameters (see the model schema).",
            },
        },
        "required": ["model"],
    },
}

ESTIMATE_SCHEMA = {
    "name": "aiutils_estimate",
    "description": (
        "Estimate the DT cost of an AiUtils generation or chat request WITHOUT "
        "charging anything. Returns estimated_dt and the current wallet balance "
        "so you can confirm with the user before any billed call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "Model ID from the AiUtils catalog.",
            },
            "parameters": {
                "type": "object",
                "description": "Model-specific input parameters (see the model schema).",
            },
        },
        "required": ["model"],
    },
}

GENERATION_GET_SCHEMA = {
    "name": "aiutils_generation_get",
    "description": "Poll an AiUtils generation by id and return its current status.",
    "parameters": {
        "type": "object",
        "properties": {
            "generation_id": {
                "type": "string",
                "description": "The generation id returned by aiutils_generate.",
            },
        },
        "required": ["generation_id"],
    },
}


def _handle_generate(args, **kw):
    model = (args.get("model") or "").strip()
    if not model:
        return tool_error("model is required")
    parameters = args.get("parameters") or {}

    guard = aiutils_client.check_credit_before_spend(model, parameters)
    if not guard.get("ok"):
        return tool_error(guard.get("error", "Credit guard failed"))

    client = guard["client"]
    try:
        result = client.generations.create(
            model=model,
            parameters=parameters,
            wait_for_completion=False,
        )
    except Exception as exc:
        logger.warning("aiutils_generate failed: %s", exc)
        return tool_error(f"Generation failed: {exc}")

    return json.dumps(
        {
            "id": getattr(result, "id", None),
            "status": getattr(result, "status", None),
            "model": getattr(result, "model", None),
            "download_urls": getattr(result, "download_urls", []),
            "dt_consumed": getattr(result, "dt_consumed", None),
            "dt_reserved": getattr(result, "dt_reserved", None),
            "error": getattr(result, "error", None),
        },
        ensure_ascii=False,
    )


def _handle_estimate(args, **kw):
    model = (args.get("model") or "").strip()
    if not model:
        return tool_error("model is required")
    parameters = args.get("parameters") or {}
    try:
        client = aiutils_client.get_client()
        estimate = client.wallet.estimate_cost(model=model, parameters=parameters)
        balance = client.wallet.balance()
    except Exception as exc:
        logger.warning("aiutils_estimate failed: %s", exc)
        return tool_error(f"Estimate failed: {exc}")

    return json.dumps(
        {
            "model": model,
            "estimated_dt": getattr(estimate, "estimated_dt", 0),
            "estimated_usd": getattr(estimate, "estimated_usd", 0.0),
            "balance_dt": getattr(balance, "balance_dt", 0),
        },
        ensure_ascii=False,
    )


def _handle_generation_get(args, **kw):
    generation_id = (args.get("generation_id") or "").strip()
    if not generation_id:
        return tool_error("generation_id is required")
    try:
        client = aiutils_client.get_client()
        result = client.generations.get(generation_id)
    except Exception as exc:
        logger.warning("aiutils_generation_get failed: %s", exc)
        return tool_error(f"Could not fetch generation: {exc}")

    return json.dumps(
        {
            "id": getattr(result, "id", None),
            "status": getattr(result, "status", None),
            "model": getattr(result, "model", None),
            "download_urls": getattr(result, "download_urls", []),
            "dt_consumed": getattr(result, "dt_consumed", None),
            "error": getattr(result, "error", None),
        },
        ensure_ascii=False,
    )


registry.register(
    name="aiutils_generate",
    toolset="aiutils",
    schema=GENERATE_SCHEMA,
    handler=_handle_generate,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🎨",
)

registry.register(
    name="aiutils_estimate",
    toolset="aiutils",
    schema=ESTIMATE_SCHEMA,
    handler=_handle_estimate,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🧾",
)

registry.register(
    name="aiutils_generation_get",
    toolset="aiutils",
    schema=GENERATION_GET_SCHEMA,
    handler=_handle_generation_get,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="📡",
)
