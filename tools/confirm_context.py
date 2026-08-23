"""
Ambient confirm callback for tools that spend money (B5).

The problem this solves: tool handlers are dispatched through
``model_tools.handle_function_call`` -> ``registry.dispatch``, and neither
receives the agent. ``agent.clarify_callback`` — the interactive prompt the CLI
already implements — is reachable only inside ``agent/tool_executor.py``, and
there only for ``function_name == "clarify"``. So a billed tool had no way to
ask "this costs 7 DT, proceed?" before spending.

Threading a new parameter through that chain would change a signature every tool
in the process flows through, for the benefit of a handful. A context variable
carries it ambiently instead: set once where the agent is constructed, read by
the few tools that need it, invisible to everything else.

``contextvars`` rather than a module global on purpose — the value stays correct
across async tasks and threads, so two concurrent sessions cannot end up sharing
one session's prompt.

Absent a callback (non-interactive runs, gateway, messaging, tests), the guard
degrades to fail-closed: it refuses spends above the threshold rather than
prompting into a void or assuming consent.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

# (question, choices) -> chosen string. Same shape as agent.clarify_callback,
# so the CLI's existing interactive prompt can be reused unchanged.
ConfirmCallback = Callable[[str, Optional[Sequence[str]]], str]

_confirm_callback: contextvars.ContextVar[Optional[ConfirmCallback]] = contextvars.ContextVar(
    "elidia_confirm_callback", default=None
)

YES = "yes"
NO = "no"


def set_confirm_callback(callback: Optional[ConfirmCallback]):
    """Install the interactive confirm callback for this context.

    Returns the token from ``ContextVar.set`` so a caller can restore the
    previous value; most callers set it once at agent construction and never
    reset it.
    """
    logger.debug("Entered into set_confirm_callback: present=%s", callback is not None)
    return _confirm_callback.set(callback)


def get_confirm_callback() -> Optional[ConfirmCallback]:
    """Return the callback for this context, or None when non-interactive."""
    return _confirm_callback.get()


def is_interactive() -> bool:
    """True when a spend can actually be confirmed with a human."""
    return _confirm_callback.get() is not None


def confirm(question: str) -> bool:
    """Ask the user to approve something, returning True only on an explicit yes.

    Anything that is not a clear yes is treated as no. A timeout, a dismissed
    prompt, or an unparseable answer must not read as consent — the whole point
    is that money does not move without one.
    """
    logger.debug("Entered into confirm: question=%.60s", question)
    callback = _confirm_callback.get()
    if callback is None:
        # No human to ask. Caller decides what to do; this never invents assent.
        return False
    try:
        answer = callback(question, [YES, NO])
    except Exception as exc:
        # A broken prompt is not approval.
        logger.warning("Confirm callback failed, treating as declined: %s", exc)
        return False
    return str(answer or "").strip().lower() in {YES, "y", "true", "confirm", "proceed"}
