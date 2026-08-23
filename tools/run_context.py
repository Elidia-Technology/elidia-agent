"""
Ambient description of the run in flight, for resumable pauses.

``spend_pause.record_pause`` can save what the agent was doing when the wallet
ran out, but only if something tells it. The pause fires deep inside a tool
handler — ``check_spend_allowed`` -> ``_pause_if_balance_spent`` — and that
handler knows the model and the price and nothing else. It cannot see the task,
the session, or the steps already finished. So the records it wrote were
technically valid and practically useless: a balance, a timestamp, and an empty
step list. "Paused: DT balance is 0" with no indication of *what* paused.

Threading task/session/steps down through ``registry.dispatch`` would change a
signature every tool passes through, for the benefit of the few that spend. So
this follows the same shape as :mod:`tools.confirm_context`: a ContextVar set
once per turn in ``run_conversation``, read only by the code that needs it.

**Steps are derived, never accumulated.** The context holds a reference to the
live ``messages`` list the conversation loop is already appending to, and reads
the completed steps out of it at pause time. A parallel counter maintained
alongside would be a second source of truth that drifts the first time someone
adds a dispatch path and forgets to increment it — and it would drift silently,
in exactly the situation where the record has to be trustworthy.

Holding a live reference works across the thread pool because
``propagate_context_to_thread`` copies the parent context: a worker sees the
*same* list object, so appends made by the loop are visible when the pause
reads it.
"""

from __future__ import annotations

import contextvars
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# A pause record is written to disk and may be read back weeks later. The task
# is the user's own prompt, so it is stored, but a pasted document should not
# become a megabyte of JSON in ~/.elidia.
MAX_TASK_CHARS = 2000

# Steps are for orientation ("where was I?"), not an audit log. The most recent
# ones are what a resume needs; an 800-call run does not need all 800 recorded.
MAX_STEPS = 50


@dataclass
class RunContext:
    """What the agent is working on right now.

    ``messages`` is the loop's live list, held by reference on purpose — see the
    module docstring.
    """

    session_id: Optional[str] = None
    task: Optional[str] = None
    # Where the answer is going: "cli", "telegram", "whatsapp", "feishu",
    # "api_server", "gateway", ... Read by the deep-link layer, which has to
    # render a portal handoff differently for a terminal than for a chat app.
    platform: Optional[str] = None
    task_id: Optional[str] = None
    turn_id: Optional[str] = None
    messages: Optional[list] = None
    started_at: float = field(default_factory=time.time)

    def completed_steps(self) -> list[dict[str, Any]]:
        """Tool calls that finished, oldest first, from the live message list.

        A ``role: "tool"`` message exists only once its call returned, so the
        presence of one *is* the completion record. Reading them back is
        therefore accurate by construction rather than by remembering to log.
        """
        if not self.messages:
            return []
        steps: list[dict[str, Any]] = []
        for message in self.messages:
            try:
                if isinstance(message, dict):
                    role = message.get("role")
                    name = message.get("name") or message.get("tool_name")
                else:  # provider SDK objects appear in this list too
                    role = getattr(message, "role", None)
                    name = getattr(message, "name", None)
                if role == "tool" and name:
                    steps.append({"tool": str(name)})
            except Exception:  # a malformed entry must not break the pause
                continue
        return steps[-MAX_STEPS:]

    def as_pause_context(self) -> dict[str, Any]:
        """Keyword arguments for :func:`tools.spend_pause.record_pause`."""
        task = self.task or None
        if task and len(task) > MAX_TASK_CHARS:
            task = task[:MAX_TASK_CHARS] + f"… [truncated, {len(self.task)} chars]"
        return {
            "session_id": self.session_id,
            "task": task,
            "completed_steps": self.completed_steps(),
            "extra": {
                "platform": self.platform,
                "task_id": self.task_id,
                "turn_id": self.turn_id,
                "elapsed_seconds": round(time.time() - self.started_at, 1),
            },
        }


_run_context: contextvars.ContextVar[Optional[RunContext]] = contextvars.ContextVar(
    "elidia_run_context", default=None
)


def set_run_context(context: Optional[RunContext]):
    """Install the run context for this turn; returns the reset token."""
    logger.debug(
        "Entered into set_run_context: session=%s task_id=%s",
        getattr(context, "session_id", None),
        getattr(context, "task_id", None),
    )
    return _run_context.set(context)


def get_run_context() -> Optional[RunContext]:
    """The run context for this turn, or None outside a conversation turn."""
    return _run_context.get()


def pause_context() -> dict[str, Any]:
    """Pause-record fields for the current run; ``{}`` when there is no run.

    Never raises. A pause is already a bad moment for the user, and losing the
    stop entirely because the description of it could not be assembled would be
    worse than a record with fewer fields.
    """
    context = _run_context.get()
    if context is None:
        return {}
    try:
        return context.as_pause_context()
    except Exception as exc:
        logger.warning("Could not build pause context: %s", exc)
        return {}
