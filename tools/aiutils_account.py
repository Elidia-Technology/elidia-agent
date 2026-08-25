#!/usr/bin/env python3
"""Who the signed-in AiUtils user is.

Every AiUtils developer signs in through the portal and then creates an API
key, so the key in use identifies a real person: a name, an email, sometimes a
phone and an avatar. This is how you find out who you are talking to.

Use it when addressing the user by name would help, when a document or report
should be attributed, or when something needs their email or location. Do not
call it on every turn — the answer does not change during a conversation.

Every field can be null. Most accounts have a name; very few have a phone or an
avatar. Say what is there and do not invent the rest: guessing someone's name
is worse than not using one.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


def _client():
    from tools import aiutils_client
    return aiutils_client.get_client()


def handle_aiutils_account(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error
    from tools import aiutils_client

    logger.debug("Entered into handle_aiutils_account")
    try:
        profile = _client().account.profile()
    except Exception as exc:
        logger.warning("account profile lookup failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="read account profile")
        return tool_error(handled or f"Could not read the account profile: {exc}")

    present = {k: v for k, v in profile.items() if v not in (None, "")}
    missing = [k for k in ("full_name", "email", "phone", "avatar_url")
               if not profile.get(k)]

    return json.dumps({
        "account": present,
        # Named explicitly so an absent field reads as absent rather than as
        # something the lookup failed to return.
        "not_set": missing,
        "note": (
            "Fields in not_set are genuinely empty on this account — the user "
            "has not filled them in. Do not guess them."
            if missing else None
        ),
    }, indent=2, default=str)


AIUTILS_ACCOUNT_SCHEMA = {
    "name": "aiutils_account",
    "description": (
        "The signed-in AiUtils user: name, email, phone, avatar, location and "
        "account status.\n\n"
        "Use it to address the user by name, attribute a document or report to "
        "them, or when you genuinely need their email or location. The answer "
        "does not change mid-conversation, so call it once, not per turn.\n\n"
        "Fields can be null and the response lists which are unset. Most "
        "accounts have a name; few have a phone or avatar. Use what is there "
        "and never invent the rest."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


def check_aiutils_account_requirements() -> bool:
    """Available when the AiUtils Developer API is configured.

    A plain bool — the registry tests truthiness, and a `(False, "reason")`
    tuple is truthy, which would advertise this tool as available when the
    check had in fact failed.
    """
    logger.debug("Entered into check_aiutils_account_requirements")
    try:
        from tools import aiutils_client
        return bool(aiutils_client.check_aiutils_requirements())
    except Exception as exc:
        logger.warning("AiUtils account lookup unavailable: %s", exc)
        return False


from tools.registry import registry, tool_error  # noqa: E402

registry.register(
    name="aiutils_account",
    toolset="aiutils",
    schema=AIUTILS_ACCOUNT_SCHEMA,
    handler=handle_aiutils_account,
    check_fn=check_aiutils_account_requirements,
    emoji="👤",
)
