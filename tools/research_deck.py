#!/usr/bin/env python3
"""Deck analytics — the numbers a research report needs, computed from recorded state.

The deck itself is written by the agent. There is deliberately **no template**
here: no HTML, no fixed section order, no boilerplate to fill. A
regulatory-exposure investigation and a molecular-discovery run have different
shapes, different charts worth showing and different things to foreground, and
one mould forced over both is exactly what makes reports look generated.

What this module supplies is the part that must not be improvised: **arithmetic
over what the run actually recorded**, plus the mode's output contract and the
constraints the file has to satisfy. The agent composes the markup around it.

Why the analytics are computed rather than described
----------------------------------------------------
A model asked to summarise its own confidence will produce prose that sounds
calibrated. Counting is not a judgement call — "4 of 11 claims are high
confidence, drawn from 3 sources, and sub-question 2 has none" is checkable.
Every chart in the deck should answer *how solid is this?*, and it can only do
that if the numbers come from the record rather than from recollection.

Nothing here inspects wording. It counts structured fields the loop already
wrote through ``research_state``.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Constraints the deck file must satisfy. Stated as requirements, never as
# markup — see the module docstring.
DECK_CONSTRAINTS = [
    "ONE self-contained file. Inline the CSS and JS, embed the data as JSON. "
    "It must render with no network at all — a downloaded copy, an offline "
    "re-open and a print-to-PDF all have to work.",

    "Compose the layout for THIS run. There is no template and you should not "
    "invent one; choose the sections and charts this particular research "
    "actually warrants.",

    "Every claim renders with its source and confidence, so a reader can check "
    "the work rather than trust it.",

    "Charts come from the analytics below, not from prose. Each one should "
    "answer 'how solid is this?' — they are evidence about the research, not "
    "decoration.",

    "Limitations are a SECTION, not a footnote. Populate it from unmet gate "
    "criteria and open gaps. A report that hides what it does not know is "
    "worse than a shorter one that names it.",

    "Print CSS is part of the deliverable: page breaks that land sensibly, "
    "charts that scale, tables that do not clip.",

    "Write it to the user's filesystem with write_file, then tell them the "
    "path. Local storage is permanent and works offline.",
]


def _source_label(source: str) -> str:
    """Group sources by origin so the distribution chart is readable.

    A run citing eleven pages from one domain is a different piece of work from
    one citing eleven domains, and a raw URL list hides that.
    """
    s = (source or "").strip()
    if not s:
        return "(unknown)"
    if s.startswith("corpus://"):
        rest = s[len("corpus://"):]
        return f"corpus:{rest.split('/', 1)[0]}" if rest else "corpus"
    try:
        host = urlparse(s).netloc
        if host:
            return host[4:] if host.startswith("www.") else host
    except ValueError:
        pass
    return s[:60]


def compute_analytics(state: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the deck needs, derived from a run's recorded state."""
    logger.debug(f"Entered into compute_analytics: run_id={state.get('run_id')}")

    claims: List[Dict[str, Any]] = list(state.get("claims") or [])
    total = len(claims)

    confidence = Counter(
        (c.get("confidence") or "medium").strip().lower() for c in claims
    )
    confidence_mix = {
        level: {
            "count": confidence.get(level, 0),
            "share": round(confidence.get(level, 0) / total, 3) if total else 0.0,
        }
        for level in ("high", "medium", "low")
    }

    by_origin = Counter(_source_label(c.get("source", "")) for c in claims)
    source_distribution = [
        {"source": name, "claims": n, "share": round(n / total, 3) if total else 0.0}
        for name, n in by_origin.most_common()
    ]

    # Coverage per sub-question. A sub-question with no claims is the single
    # most important thing a reader can know about a research report, and it is
    # invisible unless counted.
    sub_questions: List[str] = list(state.get("sub_questions") or [])
    per_sub = Counter(
        (c.get("sub_question") or "").strip() for c in claims
    )
    coverage = []
    for sq in sub_questions:
        n = per_sub.get(sq, 0)
        sq_claims = [c for c in claims if (c.get("sub_question") or "").strip() == sq]
        high = sum(1 for c in sq_claims if (c.get("confidence") or "").lower() == "high")
        coverage.append({
            "sub_question": sq,
            "claims": n,
            "high_confidence": high,
            "sources": len({(c.get("source") or "") for c in sq_claims if c.get("source")}),
            "uncovered": n == 0,
        })
    unattributed = per_sub.get("", 0)

    contested = [c for c in claims if c.get("contested")]
    resolutions = list(state.get("resolutions") or [])
    resolved_texts = {(r.get("claim") or "").strip() for r in resolutions}

    candidates = list(state.get("candidates") or [])
    ranked = sorted(
        (c for c in candidates if c.get("score") is not None),
        key=lambda c: c["score"], reverse=True,
    )

    rounds = state.get("rounds_done", 0) or 0
    per_round = Counter(int(c.get("round") or 0) for c in claims)
    claims_by_round = [
        {"round": r, "claims": per_round.get(r, 0)} for r in range(rounds + 1)
    ]

    return {
        "run_id": state.get("run_id"),
        "question": state.get("question"),
        "mode": state.get("mode"),
        "persona": state.get("persona"),
        "totals": {
            "claims": total,
            "unique_sources": len({(c.get("source") or "") for c in claims if c.get("source")}),
            "distinct_origins": len(by_origin),
            "rounds": rounds,
            "candidates": len(candidates),
            "contested": len(contested),
        },
        "confidence_mix": confidence_mix,
        "source_distribution": source_distribution,
        "coverage": coverage,
        "uncovered_sub_questions": [c["sub_question"] for c in coverage if c["uncovered"]],
        "unattributed_claims": unattributed,
        "claims_by_round": claims_by_round,
        "contested": [
            {
                "claim": c.get("claim"),
                "source": c.get("source"),
                "resolved": (c.get("claim") or "").strip() in resolved_texts,
            }
            for c in contested
        ],
        "resolutions": resolutions,
        "candidates_ranked": [
            {"name": c.get("name"), "score": c.get("score"),
             "rationale": c.get("rationale", ""), "evaluated": bool(c.get("evaluated")),
             "evaluation": c.get("evaluation", "")}
            for c in ranked
        ],
        "open_gaps": list(state.get("open_gaps") or []),
        "notes": list(state.get("notes") or []),
    }


def _publish(args: Dict[str, Any]) -> str:
    """Upload a written deck so it outlives the session that produced it.

    Tier A (local) is the default and always works: the agent writes the file
    and the user owns it. This is tier B — the same file kept server-side so it
    can be reopened from another machine, another session, or shared.

    Retention is reported from what the server actually did, never from what
    this tool expects. A deck is kept indefinitely for an account with a vault
    and deleted after 10 days without one, and the difference is the account's,
    not the caller's to predict. An artifact that silently disappears in ten
    days is worse than one that was never offered, so the answer says which
    happened in plain words.
    """
    import os

    from tools.registry import tool_error
    from tools import aiutils_client
    from tools.research_tools import _load

    run_id = str(args.get("run_id") or "").strip()
    path = os.path.expanduser(str(args.get("path") or "").strip())
    logger.debug(f"Entered into _publish: run_id={run_id}, path={path}")

    if not run_id:
        return tool_error("run_id is required")
    if not path:
        return tool_error(
            "path is required — write the deck with write_file first, then "
            "publish that file"
        )
    if not os.path.isfile(path):
        return tool_error(f"No such file: {path}")

    state = _load(run_id)
    if state is None:
        return tool_error(f"no research run {run_id!r}")

    # Recorded so an artifact listing is readable. A filename and a timestamp
    # cannot tell two investigations apart months later.
    metadata = {
        "run_id": run_id,
        "question": state.question,
        "mode": state.mode,
        "persona": state.persona,
        "claims": len(state.claims),
        "sources": len(state.sources),
        "rounds": state.rounds_done,
    }

    try:
        record = aiutils_client.get_client().files.upload(
            path, purpose="research_deck", metadata=metadata)
    except Exception as exc:
        logger.warning("deck publish failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="publish deck")
        return tool_error(
            handled or
            f"Could not publish the deck: {exc}. The local file at {path} is "
            f"unaffected and still readable."
        )

    vaulted = bool(record.get("vaulted"))
    return json.dumps({
        "id": record.get("id"),
        "run_id": run_id,
        "question": state.question,
        "local_path": path,
        "bytes": record.get("bytes_original"),
        "vaulted": vaulted,
        "expires_at": record.get("expires_at"),
        "encrypted": record.get("encrypted"),
        # Say it plainly. This is the sentence the user needs to hear.
        "retention": (
            "Kept indefinitely — this account has a vault."
            if vaulted else
            "This copy is deleted 10 days after upload. The local file at "
            f"{path} is permanent and unaffected."
        ),
        "reopen_with": "research_deck action='list' to find it again",
    }, indent=2, default=str)


def _list_published(args: Dict[str, Any]) -> str:
    """Decks published from this account, so an old one can be found again."""
    from tools.registry import tool_error
    from tools import aiutils_client

    logger.debug("Entered into _list_published")
    try:
        artifacts = aiutils_client.get_client().files.artifacts(
            limit=int(args.get("limit") or 50))
    except Exception as exc:
        logger.warning("artifact listing failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="list artifacts")
        return tool_error(handled or f"Could not list published decks: {exc}")

    if not artifacts:
        return tool_error(
            "No decks have been published from this account. Write one with "
            "write_file, then research_deck action='publish'."
        )

    return json.dumps({
        "count": len(artifacts),
        "artifacts": artifacts,
    }, indent=2, default=str)


def _handle(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error
    from tools.research_tools import _load, evaluate, mode_spec

    # Default is the analytics call, which is what every existing caller does.
    action = str(args.get("action") or "analytics").strip().lower()
    if action == "publish":
        return _publish(args)
    if action == "list":
        return _list_published(args)
    if action != "analytics":
        return tool_error(
            f"unknown action {action!r}. Valid: analytics, publish, list")

    run_id = str(args.get("run_id") or "").strip()
    logger.debug(f"Entered into research_deck._handle: run_id={run_id}")
    if not run_id:
        return tool_error("run_id is required")

    state = _load(run_id)
    if state is None:
        return tool_error(f"no research run {run_id!r} — use research_state action='list'")

    from dataclasses import asdict
    raw = asdict(state)
    gate = evaluate(state)
    spec = mode_spec(state.mode)

    # The limitations section is assembled here rather than left to the agent's
    # memory of what the gate said, so it cannot quietly shrink.
    limitations: List[str] = []
    if not gate["sufficient"]:
        limitations.extend(gate["unmet"])
    if gate.get("budget_exhausted_because"):
        limitations.extend(gate["budget_exhausted_because"])
    analytics = compute_analytics(raw)
    for sq in analytics["uncovered_sub_questions"]:
        limitations.append(f"No evidence was found for: {sq}")
    if analytics["unattributed_claims"]:
        limitations.append(
            f"{analytics['unattributed_claims']} claim(s) are not tied to any sub-question"
        )
    for c in analytics["contested"]:
        if not c["resolved"]:
            limitations.append(f"Contradiction left unresolved: {c['claim']}")

    # Mode-specific material, so the deck can render what the run actually
    # produced rather than the agent recalling it. Empty for modes that do not
    # use them — an investigation has no options, and pretending otherwise
    # would put an empty section in every report.
    mode_material = {}
    if raw.get("positions"):
        mode_material["positions"] = raw["positions"]
    if raw.get("options"):
        mode_material["options"] = raw["options"]
    if raw.get("falsifier"):
        mode_material["falsifier"] = raw["falsifier"]

    return json.dumps({
        "run_id": run_id,
        "mode": raw.get("mode"),
        "analytics": analytics,
        "mode_material": mode_material,
        "claims": raw.get("claims", []),
        "gate": {
            "sufficient": gate["sufficient"],
            "unmet": gate["unmet"],
            "stats": gate["stats"],
        },
        "output_contract": spec.get("output_sections", []),
        "limitations": limitations,
        "constraints": DECK_CONSTRAINTS,
    }, indent=2, default=str)


RESEARCH_DECK_SCHEMA = {
    "name": "research_deck",
    "description": (
        "Analytics for a research report, computed from what the run actually "
        "recorded: confidence mix, source distribution, coverage per "
        "sub-question, contested points and their resolutions, ranked "
        "candidates, and claims per round.\n\n"
        "Call this before writing the report. It also returns the mode's output "
        "contract, an assembled limitations list (unmet gate criteria, "
        "uncovered sub-questions, unresolved contradictions), and the "
        "constraints the file must satisfy.\n\n"
        "It does NOT return a template, and there is no template to ask for. "
        "You compose the deck for the run you actually did — a regulatory "
        "investigation and a molecular-discovery run warrant different sections "
        "and different charts. Use these numbers so every chart answers 'how "
        "solid is this?' rather than decorating the page.\n\n"
        "Then write a single self-contained HTML file with write_file and tell "
        "the user its path.\n\n"
        "action='publish' uploads that file so it outlives the session — "
        "reopenable from another machine or shared. The local file stays "
        "permanent and untouched either way. Tell the user what the response "
        "says about retention: without a vault the published copy is deleted "
        "after 10 days, and a copy that vanishes unannounced is worse than one "
        "never offered.\n\n"
        "action='list' finds decks published earlier, including from other "
        "sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["analytics", "publish", "list"],
                "description": (
                    "analytics (default): numbers for composing the report · "
                    "publish: upload a written deck · list: decks published before"
                ),
            },
            "run_id": {
                "type": "string",
                "description": "analytics/publish: the research run to report on.",
            },
            "path": {
                "type": "string",
                "description": "publish: the HTML file you wrote with write_file.",
            },
            "limit": {
                "type": "integer",
                "description": "list: maximum decks to return (default 50).",
            },
        },
        "required": [],
    },
}


def check_research_deck_requirements() -> Tuple[bool, str]:
    try:
        from tools.research_tools import _research_dir
        _research_dir().mkdir(parents=True, exist_ok=True)
        return True, ""
    except Exception as exc:
        return False, f"research state unavailable: {exc}"


from tools.registry import registry, tool_error  # noqa: E402

registry.register(
    name="research_deck",
    toolset="deep_research",
    schema=RESEARCH_DECK_SCHEMA,
    handler=_handle,
    check_fn=check_research_deck_requirements,
    emoji="📊",
)
