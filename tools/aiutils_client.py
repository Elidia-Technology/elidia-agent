#!/usr/bin/env python3
"""
AiUtils Developer API client helper for the Elidia tool layer.

A thin, lazily-imported wrapper around the optional ``aiutils_sdk`` package.
The SDK is not a hard Elidia dependency: the AiUtils tools gate themselves off
via :func:`check_aiutils_requirements` (returning ``False``) when either the
SDK is not installed or no AiUtils Developer API key is set, so a stock Elidia
install is unaffected.

The Developer API bills in DT credits. Any tool that spends credits MUST run
:func:`check_credit_before_spend` first — it estimates the cost and fails
closed when the wallet balance cannot cover it, so a billed call can never
proceed past an insufficient balance without an explicit opt-in.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# The AiUtils Developer API key is exposed under three equivalent env-var names.
# All three are accepted, in priority order — mirroring the inference provider
# (plugins/model-providers/aiutils) so one key drives both layers.
API_KEY_ENV_VARS = ("ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY")
DEFAULT_BASE_URL = "https://developer-api.aiutils.io"


def api_key() -> Optional[str]:
    """Return the configured AiUtils API key, or None.

    Accepts any of :data:`API_KEY_ENV_VARS`, in priority order.
    """
    for var in API_KEY_ENV_VARS:
        value = os.environ.get(var)
        if value:
            return value
    return None


def _import_sdk():
    """Import the ``aiutils_sdk`` package, raising ImportError if absent."""
    import aiutils_sdk  # noqa: F401

    return aiutils_sdk


def check_aiutils_requirements() -> bool:
    """True only when both the API key and the SDK are present."""
    if not api_key():
        return False
    try:
        _import_sdk()
    except ImportError:
        return False
    return True


def get_client(base_url: Optional[str] = None):
    """Construct an AiUtils client from the environment.

    Raises a clear RuntimeError when the key or SDK is missing; callers should
    guard with :func:`check_aiutils_requirements` first.
    """
    key = api_key()
    if not key:
        raise RuntimeError(
            "No AiUtils Developer API key is set. Configure one of "
            f"{', '.join(API_KEY_ENV_VARS)} to use the AiUtils tools."
        )
    sdk = _import_sdk()
    return sdk.AiUtils(api_key=key, base_url=base_url or DEFAULT_BASE_URL)


def check_credit_before_spend(
    model: str,
    parameters: Optional[dict] = None,
    client=None,
) -> dict:
    """Estimate DT cost and verify the wallet can cover it.

    Returns ``{"ok": True, "estimated_dt": int, "balance_dt": int, "client": client}``
    on success, or ``{"ok": False, "error": str, ...}`` on failure. This is the
    fail-closed guard: a billed call must never proceed without ``ok=True``.
    """
    client = client or get_client()
    try:
        estimate = client.wallet.estimate_cost(model=model, parameters=parameters or {})
        balance = client.wallet.balance()
    except Exception as exc:  # auth / network / pricing errors → refuse
        logger.warning("AiUtils credit guard could not verify wallet: %s", exc)
        return {"ok": False, "error": f"Could not verify wallet balance: {exc}"}

    estimated_dt = int(getattr(estimate, "estimated_dt", 0) or 0)
    balance_dt = int(getattr(balance, "balance_dt", 0) or 0)

    if estimated_dt > balance_dt:
        return {
            "ok": False,
            "error": (
                f"Insufficient DT balance: this request is estimated at "
                f"{estimated_dt} DT but the wallet holds {balance_dt} DT."
            ),
            "estimated_dt": estimated_dt,
            "balance_dt": balance_dt,
        }

    return {
        "ok": True,
        "estimated_dt": estimated_dt,
        "balance_dt": balance_dt,
        "client": client,
    }
