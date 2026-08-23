"""
What AiUtils calls actually cost, learned from running them (B15).

``/v1/pricing/estimate`` prices *catalog models*. It 404s on everything else —
portal tool slugs included — so ``check_spend_allowed`` degrades to a bare
balance check for those and reports ``exact=False``. The agent then cannot tell
the user what a tool will cost, and confirm-before-charge cannot fire, because
there is no number to compare against a threshold.

Yet the answer arrives with every response: the gateway stamps ``X-DT-Consumed``
on all of them. It was simply discarded — so the same tool was unpriceable on
the hundredth run as on the first, and the user paid to rediscover a fact the
server had already told us.

This is the self-improvement loop for AiUtils knowledge that B15 asks for, in
its most concrete form: **run something once, and know what it costs from then
on.** Not a heuristic — a record of what was actually charged.

Deliberately conservative about what it claims:

* A learned figure is never presented as a quote. It is what *this* user's
  previous calls cost, and cost varies with input size, so it is reported as an
  observation with its sample count and its spread.
* The median of recent samples, not the mean: one 8K-token outlier should not
  move the number a user sees for a typical call.
* It never *authorises* a spend. The wallet floor and the server's own 402
  remain the gates. This only fills in a number where there was none.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

COST_FILE = "aiutils-costs.json"

# Enough samples to see the spread, few enough that the file stays small and a
# genuine price change is reflected within a handful of calls.
MAX_SAMPLES = 20

# Below this, one observation is as likely to mislead as to help.
MIN_SAMPLES_FOR_ESTIMATE = 1


def _cost_file() -> Path:
    home = os.getenv("ELIDIA_HOME") or str(Path.home() / ".elidia")
    path = Path(home)
    path.mkdir(parents=True, exist_ok=True)
    return path / COST_FILE


def model_key(model: str) -> str:
    """Namespaced key for a catalog model."""
    return f"model:{(model or '').strip()}"


def tool_key(slug: str) -> str:
    """Namespaced key for a portal tool slug.

    Namespaced so a model and a tool that happen to share a name cannot pool
    their observations into one meaningless average.
    """
    return f"tool:{(slug or '').strip()}"


def _load() -> dict[str, Any]:
    try:
        path = _cost_file()
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        # A corrupt cache must never break a billed call. Losing the learned
        # costs only means falling back to "cost not known in advance", which
        # is where this started.
        logger.warning("Could not read the AiUtils cost memory: %s", exc)
        return {}


def _save(data: dict[str, Any]) -> None:
    try:
        path = _cost_file()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(path)
    except Exception as exc:
        logger.warning("Could not write the AiUtils cost memory: %s", exc)


def record(key: str, dt_consumed: Optional[int]) -> None:
    """Remember what a call actually cost.

    ``None`` is ignored — it means the response carried no ``X-DT-Consumed``
    header (an older gateway, or an unbilled endpoint), which is not the same as
    a call that was free. Recording it as 0 would teach the agent that a billed
    tool costs nothing.
    """
    logger.debug("Entered into record: key=%s dt=%s", key, dt_consumed)
    if not key or not isinstance(dt_consumed, int) or dt_consumed < 0:
        return

    try:
        # Re-read immediately before writing so a concurrent tool call's
        # observation is less likely to be lost. Not a transaction — this is a
        # local cache, and losing one sample costs nothing but a slightly
        # staler estimate.
        data = _load()
        entry = data.get(key)
        if not isinstance(entry, dict):
            entry = {"samples": [], "observations": 0}

        samples = [s for s in entry.get("samples", []) if isinstance(s, int)]
        samples.append(dt_consumed)
        entry["samples"] = samples[-MAX_SAMPLES:]
        entry["observations"] = int(entry.get("observations", 0)) + 1
        entry["last_dt"] = dt_consumed
        entry["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data[key] = entry
        _save(data)
    except Exception as exc:
        # This runs AFTER a call the user has already been billed for. A
        # read-only home, a full disk or any future bug in here must cost the
        # agent its learning, never the result the user paid for.
        logger.warning("Could not record the observed cost for %s: %s", key, exc)


def estimate(key: str) -> Optional[dict[str, Any]]:
    """What this key has cost before, or None when nothing has been observed.

    Returns ``{"dt": int, "samples": int, "low": int, "high": int,
    "observations": int}``. ``low``/``high`` are the observed range, so a caller
    can say "usually about N, seen between X and Y" instead of implying a
    precision the data does not support.
    """
    entry = _load().get(key)
    if not isinstance(entry, dict):
        return None
    samples = [s for s in entry.get("samples", []) if isinstance(s, int)]
    if len(samples) < MIN_SAMPLES_FOR_ESTIMATE:
        return None
    return {
        "dt": int(statistics.median(samples)),
        "samples": len(samples),
        "low": min(samples),
        "high": max(samples),
        "observations": int(entry.get("observations", len(samples))),
        "last_seen": entry.get("last_seen"),
    }


def describe(key: str) -> Optional[str]:
    """One line a person can read, or None when nothing is known yet."""
    est = estimate(key)
    if est is None:
        return None
    if est["low"] == est["high"]:
        return f"{est['dt']} DT (same on all {est['samples']} previous run(s))"
    return (
        f"about {est['dt']} DT, based on {est['samples']} previous run(s) "
        f"({est['low']}–{est['high']} DT)"
    )


def record_from_client(key: str, client) -> Optional[int]:
    """Record the cost of the call this client just made; return it.

    Reads ``client.last_dt_consumed``, which the SDK exposes from the gateway's
    ``X-DT-Consumed`` header. Older SDKs do not have it, so the attribute is
    fetched defensively — a stale SDK should cost the agent its learning, not
    the call.
    """
    try:
        dt = getattr(client, "last_dt_consumed", None)
    except Exception:
        return None
    if isinstance(dt, int):
        record(key, dt)
        return dt
    return None


def forget(key: str) -> bool:
    """Drop what was learned about one key (e.g. after a pricing change)."""
    data = _load()
    if key in data:
        del data[key]
        _save(data)
        return True
    return False


def all_known() -> dict[str, dict[str, Any]]:
    """Every key with a usable estimate — for `elidia` to show the user."""
    out: dict[str, dict[str, Any]] = {}
    for key in _load():
        est = estimate(key)
        if est is not None:
            out[key] = est
    return out
