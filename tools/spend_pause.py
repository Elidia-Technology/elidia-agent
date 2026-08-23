"""
Balance-exhaustion pause and resume for billed work.

Automated runs — gateway, messaging, cron, scripted jobs — must be able to spend
without a human at the keyboard. Their ceiling is the user's wallet, not a
prompt. When it runs out, the run has to stop in a way the user can pick up
again, rather than failing halfway through with nothing recorded.

Three properties this is built around, in order of importance:

**Work already in flight is never killed.** The check runs *before* starting new
billed work, so a generation, LLM call or tool run that has already been
dispatched settles normally and its result is kept. Aborting mid-flight would
mean paying for something and throwing it away.

**A negative balance is acceptable.** The exact cost of a call is not knowable
before it returns, so the last spend may overshoot. That overshoot is recorded
and settled against the next top-up rather than being prevented — preventing it
would require refusing work whose price we cannot know, which stops far more
than it saves.

**The pause is resumable.** State is written before stopping, so the same job can
continue from where it left off once the wallet is funded.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# One file per paused job under ELIDIA_HOME, so a resume can find it without a
# database and a user can inspect or delete it by hand.
PAUSE_DIRNAME = "paused-jobs"


class SpendPaused(RuntimeError):
    """Raised when the wallet is spent and the run must stop.

    Carries the pause record so a caller can report the shortfall and tell the
    user how to resume, rather than surfacing a bare failure.
    """

    def __init__(self, message: str, record: dict[str, Any]):
        super().__init__(message)
        self.record = record


def _pause_dir() -> Path:
    """Directory holding paused-job records."""
    home = os.getenv("ELIDIA_HOME") or str(Path.home() / ".elidia")
    path = Path(home) / PAUSE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_pause(
    *,
    balance_dt: int,
    session_id: Optional[str] = None,
    task: Optional[str] = None,
    completed_steps: Optional[list] = None,
    pending_step: Optional[str] = None,
    spent_this_run_dt: int = 0,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Persist enough state to resume this job later, and return the record.

    Deliberately stores *what was being done*, not an internal execution
    snapshot: a serialised interpreter state would break on the next release,
    whereas the task, the steps already finished, and the step that was next
    remain meaningful and let either the agent or the user pick the work back up.
    """
    logger.debug(
        "Entered into record_pause: balance_dt=%s spent=%s session=%s",
        balance_dt, spent_this_run_dt, session_id,
    )
    record = {
        "pause_id": str(uuid.uuid4()),
        "paused_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reason": "balance_exhausted",
        "balance_dt": balance_dt,
        "spent_this_run_dt": spent_this_run_dt,
        "session_id": session_id,
        "task": task,
        "completed_steps": completed_steps or [],
        "pending_step": pending_step,
        "extra": extra or {},
    }

    path = _pause_dir() / f"{record['pause_id']}.json"
    try:
        # Write then rename: a half-written record is worse than none, because
        # a resume would read it and act on a truncated task.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        tmp.replace(path)
        record["state_file"] = str(path)
        logger.info("Run paused on exhausted balance; state saved to %s", path)
    except Exception as exc:
        # Never let a persistence failure mask the pause itself — the run still
        # has to stop, the user just loses the resume record.
        logger.error("Could not write pause record: %s", exc)
        record["state_file"] = None
        record["persist_error"] = str(exc)
    return record


def list_paused_jobs() -> list[dict[str, Any]]:
    """Return saved pause records, newest first."""
    logger.debug("Entered into list_paused_jobs")
    records: list[dict[str, Any]] = []
    try:
        for path in _pause_dir().glob("*.json"):
            try:
                records.append(json.loads(path.read_text()))
            except Exception as exc:
                # One corrupt record must not hide the rest.
                logger.warning("Skipping unreadable pause record %s: %s", path, exc)
    except Exception as exc:
        logger.warning("Could not list paused jobs: %s", exc)
    return sorted(records, key=lambda r: r.get("paused_at", ""), reverse=True)


def clear_paused_job(pause_id: str) -> bool:
    """Delete a pause record once its job has been resumed or abandoned."""
    logger.debug("Entered into clear_paused_job: pause_id=%s", pause_id)
    path = _pause_dir() / f"{pause_id}.json"
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception as exc:
        logger.warning("Could not clear pause record %s: %s", pause_id, exc)
    return False


def format_pause_message(record: dict[str, Any]) -> str:
    """Human-readable explanation of why the run stopped and how to continue."""
    balance = record.get("balance_dt", 0)
    spent = record.get("spent_this_run_dt", 0)
    lines = [
        f"Paused: DT balance is {balance} (spent {spent} DT this run).",
    ]
    if balance < 0:
        # Expected, not an error — say so, or it reads like a billing bug.
        lines.append(
            f"  The final call overshot by {abs(balance)} DT. That is settled "
            "against your next top-up."
        )
    if record.get("pending_step"):
        lines.append(f"  Stopped before: {record['pending_step']}")
    done = record.get("completed_steps") or []
    if done:
        lines.append(f"  Completed {len(done)} step(s); work so far is kept.")
    if record.get("state_file"):
        lines.append(f"  Saved to: {record['state_file']}")
        lines.append("  Top up your balance, then resume this job to continue.")
    else:
        lines.append(
            "  WARNING: the resume record could not be written, so this job "
            "cannot be continued automatically."
        )
    return "\n".join(lines)
