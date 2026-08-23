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
# Where DT is bought. The DT wallet lives entirely on the Developer Console
# side and is SEPARATE from Portal credits — a user tops up here, never on a
# Portal billing page. Used only as a fallback: the 402 body carries its own
# top_up_url, which is authoritative.
TOP_UP_URL = "https://developer.aiutils.io/billing/top-up"
# Smallest balance a spend may start from when the cost cannot be estimated
# up-front. The gateway bills a minimum of 1 DT (`max(1, ceil(...))`).
MINIMUM_SPEND_DT = 1
# $1 = 1000 DT (the gateway computes ceil(usd * 1000)), so 1000 DT is one
# dollar. An earlier 25 DT default was two and a half CENTS — it would have
# prompted on almost every call, and prompt fatigue trains people to accept
# without reading, which defeats the guard on the spends that matter.
CONFIRM_THRESHOLD_DT = int(os.getenv("AIUTILS_CONFIRM_THRESHOLD_DT", "1000"))

# Balance at or below this pauses the run instead of starting new billed work.
# Zero by design: a spend already in flight is allowed to finish and may take
# the balance negative, which is settled on the next top-up. Only the NEXT
# spend is withheld.
PAUSE_FLOOR_DT = int(os.getenv("AIUTILS_PAUSE_FLOOR_DT", "0"))


def api_key() -> Optional[str]:
    """Return the configured AiUtils API key, or None.

    Checks the OS credential store first (macOS Keychain / Windows Credential
    Manager / Secret Service), then falls back to :data:`API_KEY_ENV_VARS` in
    priority order.

    The keyring is preferred because this agent runs terminal commands,
    execute_code sandboxes and MCP servers by design, and every one of those
    inherits the parent environment — a key in os.environ is handed to all of
    them. Reading it into a variable instead keeps it out of their reach.

    Falls back silently when there is no keyring: it is not a declared
    dependency, and a headless Linux box often has no Secret Service. Refusing
    to run over a missing keyring daemon would be worse than the exposure it
    prevents.
    """
    try:
        from elidia_cli import key_store

        return key_store.load()
    except Exception as exc:  # pragma: no cover - import guard
        logger.debug("Key store unavailable, using the environment: %s", exc)

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


def _pause_fields(explicit: dict, **overrides) -> dict:
    """Merge the ambient run description with caller-supplied pause fields.

    Without this, a pause record carried a balance and nothing else — no task,
    no session, no steps — because the guard fires inside a tool handler that
    knows only the price. :mod:`tools.run_context` publishes what the turn is
    doing; this folds it in underneath whatever the caller passed, so an
    explicit value always wins and ``extra`` accumulates instead of being
    overwritten by whichever side happened to set it last.
    """
    try:
        from tools import run_context

        fields = run_context.pause_context()
    except Exception as exc:  # bookkeeping must never prevent the pause
        logger.debug("No ambient run context for pause record: %s", exc)
        fields = {}

    extra = dict(fields.get("extra") or {})
    for source in (explicit, overrides):
        for key, value in (source or {}).items():
            if key == "extra":
                extra.update(value or {})
            elif value is not None:
                fields[key] = value
    fields["extra"] = extra
    return fields


def handle_sdk_error(exc: Exception, *, action: str, **pause_context) -> Optional[str]:
    """Turn an SDK exception into an agent-readable message, or None if unhandled.

    The Developer API is the authority on billing — it meters each call and
    answers HTTP 402 with required/available/shortfall when the wallet cannot
    cover it, which the SDK raises as InsufficientDTError. The client-side guard
    is an optimisation that saves a round trip and enables confirm-before-charge;
    it is not the gate. A balance can be spent by another session, or a call can
    cost more than its estimate, so the server's answer is the one that counts.

    Flattening that into "Generation failed: <str>" loses what the user needs:
    the shortfall, and that this is a top-up rather than a bug. So a 402 also
    writes a pause record here, giving the same resumable state as the
    client-side floor.
    """
    logger.debug("Entered into handle_sdk_error: action=%s type=%s", action, type(exc).__name__)
    try:
        from aiutils_sdk.exceptions import (
            AuthenticationError,
            ForbiddenError,
            InsufficientDTError,
            RateLimitError,
        )
    except ImportError:
        return None

    if isinstance(exc, InsufficientDTError):
        try:
            from tools import spend_pause

            # The server told us the balance in the 402 body; recording a
            # hardcoded 0 would put a number in the record that was never true.
            available = getattr(exc, "available_dt", None)
            record = spend_pause.record_pause(
                balance_dt=int(available) if isinstance(available, int) else 0,
                **_pause_fields(
                    pause_context,
                    pending_step=action,
                    extra={"server_detail": str(exc), "declined_by": "server"},
                ),
            )
            resume = spend_pause.format_pause_message(record)
        except Exception as pause_exc:  # never let bookkeeping mask the message
            logger.warning("Could not record pause for a 402: %s", pause_exc)
            resume = ""
        # Prefer the server's own top-up URL; it knows where its billing lives.
        top_up = getattr(exc, "top_up_url", None) or TOP_UP_URL
        shortfall = getattr(exc, "shortfall_dt", None)
        shortfall_line = (
            f"You are {shortfall} DT short.\n" if isinstance(shortfall, int) and shortfall > 0 else ""
        )
        return (
            f"Out of DT balance — the Developer API declined this {action}.\n"
            f"{exc}\n"
            f"{shortfall_line}"
            f"Top up your DT wallet at {top_up} to continue. "
            "(DT is bought in the Developer Console; it is separate from Portal credits.)"
            + (f"\n{resume}" if resume else "")
        )

    if isinstance(exc, AuthenticationError):
        return (
            f"Could not {action}: the AiUtils API key was rejected. Check "
            f"{API_KEY_ENV_VARS[0]} — this is not a balance problem."
        )
    if isinstance(exc, RateLimitError):
        return f"Rate limited while trying to {action}. {exc} This is temporary — retry shortly."
    if isinstance(exc, ForbiddenError):
        return f"Could not {action}: the API key lacks the required scope. {exc}"
    return None


def _pause_if_balance_spent(balance_dt: int, **context):
    """Withhold NEW billed work once the wallet is spent, saving resume state.

    Returns a refusal dict, or None to proceed.

    The check is deliberately on the balance *before* this spend, not on whether
    this spend fits. Cost is not knowable exactly until a call returns, so the
    last one may overshoot into a negative balance — that is recorded and
    settled on the next top-up rather than prevented, because preventing it
    would mean refusing work whose price cannot be known.

    Nothing already dispatched is affected: this runs before new work starts, so
    an in-flight generation or LLM call settles normally and its result is kept.
    """
    logger.debug(
        "Entered into _pause_if_balance_spent: balance_dt=%s floor=%s",
        balance_dt, PAUSE_FLOOR_DT,
    )
    if balance_dt > PAUSE_FLOOR_DT:
        return None

    try:
        from tools import spend_pause
    except Exception:  # pragma: no cover - import guard
        return {
            "ok": False,
            "error": f"DT balance exhausted ({balance_dt} DT). Top up to continue.",
            "balance_dt": balance_dt,
            "paused": True,
        }

    record = spend_pause.record_pause(balance_dt=balance_dt, **_pause_fields(context))
    return {
        "ok": False,
        "error": spend_pause.format_pause_message(record),
        "balance_dt": balance_dt,
        "paused": True,
        "pause_id": record.get("pause_id"),
        "state_file": record.get("state_file"),
    }


def _confirm_if_expensive(
    estimated_dt: int,
    balance_dt: int,
    model: Optional[str],
    learned: Optional[dict] = None,
):
    """Ask before a large spend. Returns a refusal dict, or None to proceed.

    Only reached when the cost is known: confirming an unpriced call would ask
    the user to approve an unknown amount, which is not meaningful consent.

    ``learned`` marks a figure that came from OBSERVING previous runs rather
    than from the pricing catalog. It is worded differently in the prompt on
    purpose — "usually about N, based on 4 previous runs" is an honest
    description of that data; "costs N DT" would imply a quote the server never
    gave.

    When no prompt is available (gateway, messaging, cron, scripted runs) this
    PROCEEDS. Owner directive 2026-08-23: automated runs spend freely and their
    ceiling is the user's wallet, not the presence of a human — failing closed
    here stranded unattended jobs the user had already funded. The run pauses
    when the balance is spent.
    """
    logger.debug(
        "Entered into _confirm_if_expensive: estimated_dt=%s threshold=%s",
        estimated_dt, CONFIRM_THRESHOLD_DT,
    )
    if estimated_dt < CONFIRM_THRESHOLD_DT:
        return None

    try:
        from tools import confirm_context
    except Exception:  # pragma: no cover - import guard
        return None

    if not confirm_context.is_interactive():
        # Automated callers — gateway, messaging, cron, scripted runs — proceed.
        # Their ceiling is the wallet, not a prompt: work is billed to the user
        # who invoked it, and the run pauses when the balance is spent (see
        # check_balance_or_pause). Refusing here would strand unattended jobs
        # that the user has already paid for.
        logger.debug(
            "Non-interactive spend of %s DT proceeding (balance %s DT)",
            estimated_dt, balance_dt,
        )
        return None

    overshoot = ""
    if estimated_dt > balance_dt:
        # Allowed, but never silently: the user should see it before agreeing.
        overshoot = (
            f" This exceeds your balance by {estimated_dt - balance_dt} DT and "
            "will be settled on your next top-up."
        )
    if learned is not None:
        spread = (
            "" if learned["low"] == learned["high"]
            else f" (seen between {learned['low']} and {learned['high']} DT)"
        )
        cost_phrase = (
            f"usually costs about {estimated_dt} DT{spread}, based on "
            f"{learned['samples']} previous run(s)"
        )
    else:
        cost_phrase = f"costs about {estimated_dt} DT"

    approved = confirm_context.confirm(
        f"{model or 'This request'} {cost_phrase} "
        f"(balance {balance_dt} DT).{overshoot} Proceed?"
    )
    if not approved:
        return {
            "ok": False,
            "error": f"Declined: the {estimated_dt} DT charge was not approved.",
            "estimated_dt": estimated_dt,
            "balance_dt": balance_dt,
            "declined": True,
        }
    return None


def check_spend_allowed(
    model: Optional[str] = None,
    parameters: Optional[dict] = None,
    client=None,
) -> dict:
    """Fail-closed guard for **every** DT-spending call.

    :func:`check_credit_before_spend` can only guard spends whose cost is
    knowable up-front, because ``/v1/pricing/estimate`` prices *catalog models*:
    it 404s on anything else, portal tool slugs included. Applying it directly
    to ``aiutils_tool_execute`` would therefore refuse every tool call.

    This guard closes that gap without that regression:

    * The wallet balance is fetched **always**. If it cannot be read the spend
      is refused — an unreadable wallet is never treated as a spendable one.
    * When ``model`` is priceable, the exact estimate is compared against the
      balance, exactly as before.
    * When it is not priceable (tool slugs, or a model with no catalog pricing),
      the guard degrades to *balance-only*: it refuses an empty wallet and
      reports ``exact=False`` so the caller can say the cost was not known in
      advance. This is weaker than an estimate, but it is a real ceiling —
      unlike no guard at all.

    Returns ``{"ok": True, "exact": bool, "estimated_dt": int|None,
    "balance_dt": int, "client": client}`` or ``{"ok": False, "error": str, ...}``.
    """
    client = client or get_client()

    try:
        balance = client.wallet.balance()
    except Exception as exc:  # auth / network → refuse, never assume funds
        logger.warning("AiUtils spend guard could not read wallet balance: %s", exc)
        return {"ok": False, "error": f"Could not verify wallet balance: {exc}"}

    balance_dt = int(getattr(balance, "balance_dt", 0) or 0)

    # Exhausted wallet stops the run before any new billed work, priceable or
    # not, and writes resume state.
    paused = _pause_if_balance_spent(
        balance_dt,
        # What the run was about to do. Named here because the guard is the
        # only frame that knows it — by the time record_pause runs, the model
        # is out of scope.
        pending_step=f"billed call to {model}" if model else "a billed call",
    )
    if paused is not None:
        return paused

    estimated_dt = None
    learned = None
    if model:
        try:
            estimate = client.wallet.estimate_cost(model=model, parameters=parameters or {})
            estimated_dt = int(getattr(estimate, "estimated_dt", 0) or 0)
        except Exception as exc:
            # Not priceable (404 for tool slugs / unknown models) — fall through
            # to the balance-only check rather than refusing a valid call.
            logger.debug("AiUtils spend guard could not price %r: %s", model, exc)

    if estimated_dt is None or estimated_dt <= 0:
        # The catalog cannot price this, but we may have RUN it before. The
        # gateway reports the real cost on every response; tools/aiutils_cost_memory
        # keeps those observations. Using one here is what lets
        # confirm-before-charge fire on a portal tool slug at all — without it
        # there is no number to compare against the threshold, so an expensive
        # tool ran silently no matter what it cost.
        try:
            from tools import aiutils_cost_memory

            learned = aiutils_cost_memory.estimate(
                aiutils_cost_memory.model_key(model) if model else ""
            ) or aiutils_cost_memory.estimate(
                aiutils_cost_memory.tool_key(model) if model else ""
            )
        except Exception as exc:  # learning is never load-bearing
            logger.debug("Could not read learned cost for %r: %s", model, exc)

    if estimated_dt is not None and estimated_dt > 0:
        # NOTE: an estimate larger than the balance is NOT refused here.
        # Owner directive 2026-08-23: work runs while the wallet has anything in
        # it, the final call may overshoot into a negative balance, and that
        # overshoot settles on the next top-up. Refusing on estimate > balance
        # would stop a job the user has funded merely because the last step
        # happens to be the expensive one. The wallet floor above is what stops
        # a run; this is only where the user is told what it will cost.
        refusal = _confirm_if_expensive(estimated_dt, balance_dt, model)
        if refusal is not None:
            return refusal

        return {
            "ok": True,
            "exact": True,
            "estimated_dt": estimated_dt,
            "balance_dt": balance_dt,
            "client": client,
        }

    if learned is not None:
        # Observed, not quoted: cost varies with input size, so this is
        # reported as what previous runs cost, never as a price. It fills the
        # gap where there was no number at all; it does not authorise anything
        # — the wallet floor above and the server's own 402 remain the gates.
        refusal = _confirm_if_expensive(
            learned["dt"], balance_dt, model, learned=learned,
        )
        if refusal is not None:
            return refusal
        return {
            "ok": True,
            "exact": False,
            "estimated_dt": learned["dt"],
            "learned": learned,
            "balance_dt": balance_dt,
            "client": client,
        }

    # Balance-only path: the cost is not knowable up-front. Refuse an empty
    # wallet so a billed call can never start with nothing to draw against.
    if balance_dt < MINIMUM_SPEND_DT:
        return {
            "ok": False,
            "error": (
                f"Insufficient DT balance: the wallet holds {balance_dt} DT. "
                "This request's cost could not be estimated in advance, so it "
                "needs a non-empty balance before it can run."
            ),
            "estimated_dt": None,
            "balance_dt": balance_dt,
        }

    return {
        "ok": True,
        "exact": False,
        "estimated_dt": None,
        "balance_dt": balance_dt,
        "client": client,
    }
