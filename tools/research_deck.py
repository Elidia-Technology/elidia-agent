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
    "path. Local storage is permanent and works offline. On the portal "
    "(no write_file), call portal_deck_publish with the full HTML to get a "
    "downloadable link, and show that link to the user.",
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

    # Confidence progression per round — lets a chart show how evidence
    # quality improved (or not) as the loop iterated.
    confidence_by_round: List[Dict[str, Any]] = []
    for r in range(rounds + 1):
        rc = [c for c in claims if int(c.get("round") or 0) == r]
        if rc:
            rh = sum(1 for c in rc if (c.get("confidence") or "").lower() == "high")
            confidence_by_round.append({
                "round": r,
                "total": len(rc),
                "high": rh,
                "high_ratio": round(rh / len(rc), 3),
            })

    # Citation index — every source used, grouped and numbered, so the
    # deck can render a proper references section and inline citations.
    source_index: List[Dict[str, Any]] = []
    source_nums: Dict[str, int] = {}
    idx = 1
    for c in claims:
        src = (c.get("source") or "").strip()
        if src and src not in source_nums:
            source_nums[src] = idx
            source_index.append({"num": idx, "source": src, "origin": _source_label(src)})
            idx += 1

    # Claims grouped by sub-question for structured rendering.
    claims_by_sub: Dict[str, List[Dict[str, Any]]] = {}
    for c in claims:
        sq = (c.get("sub_question") or "").strip() or "(general)"
        claims_by_sub.setdefault(sq, []).append({
            "claim": c.get("claim"),
            "source": c.get("source"),
            "source_num": source_nums.get((c.get("source") or "").strip(), 0),
            "confidence": c.get("confidence", "medium"),
            "contested": c.get("contested", False),
            "as_of": c.get("as_of"),
            "basis": c.get("basis"),
        })

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
        "confidence_by_round": confidence_by_round,
        "claims_by_sub_question": claims_by_sub,
        "citation_index": source_index,
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


DESIGN_GUIDANCE = (
    "The deck is a SINGLE self-contained HTML5 document rendered in the "
    "user's chat and printable as a PDF. Build it to the standard of a "
    "premium SaaS analytics report.\n\n"

    "STRUCTURE:\n"
    "A complete HTML5 document — doctype, head, body. All CSS in a "
    "style element, all JS inline. NO external resources except Chart.js "
    "from CDN (cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js).\n"
    "Gradient header with research question, persona, mode, date.\n"
    "Executive Summary / KPI dashboard (claim count, source count, "
    "confidence ratio, coverage score) as prominent metric cards.\n"
    "Findings organised by sub-question, each claim showing its source "
    "number [1], confidence badge, and the claim text.\n"
    "Data visualisation section with Chart.js charts derived from the "
    "analytics (confidence_mix = doughnut, source_distribution = "
    "horizontal bar, coverage = grouped bar, claims_by_round = line).\n"
    "Contested Claims and Resolutions section (if any).\n"
    "Mode-specific sections (candidates for discovery, positions for "
    "simulation, options for planning, falsifier for market).\n"
    "Limitations section — always present, always a full section.\n"
    "References / Citation Index — numbered list from citation_index.\n\n"

    "VISUAL DESIGN:\n"
    "Modern, clean card-based layout with subtle shadows.\n"
    "System font stack: -apple-system, BlinkMacSystemFont, Segoe UI, "
    "Roboto, sans-serif.\n"
    "Accent colour derived from the persona domain. Left-coloured "
    "borders on section cards.\n"
    "Confidence badges: high=green, medium=amber, low=red, with "
    "pill-shaped styling.\n"
    "Responsive: works from 360px to 1920px. Tables scroll inside "
    "overflow-x:auto containers.\n"
    "Dark-mode support via prefers-color-scheme and data-theme.\n"
    "Print CSS: page breaks between sections, charts scale, no "
    "clipping.\n\n"

    "CHARTS (use Chart.js, inline the data as JSON):\n"
    "Doughnut: confidence_mix (high/medium/low shares).\n"
    "Horizontal bar: source_distribution (claims per origin).\n"
    "Grouped bar: coverage per sub-question (claims vs high-confidence).\n"
    "Line: claims_by_round showing evidence accumulation.\n"
    "Line (overlay): confidence_by_round showing quality progression.\n"
    "Radar: if 3+ sub-questions, coverage breadth as a radar.\n"
    "Additional mode-specific charts as chart_recommendations suggest.\n\n"

    "CITATION FORMAT:\n"
    "Inline: [N] after the claim text, where N is from citation_index.\n"
    "References section: numbered list matching citation_index, each "
    "showing the source URL/identifier and its origin label.\n"
    "Every claim must have a visible source — this is non-negotiable."
)


def _chart_recommendations(
    mode: str,
    analytics: Dict[str, Any],
    mode_material: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Mode-aware chart recommendations based on what the run produced."""
    logger.debug(f"Entered into _chart_recommendations: mode={mode}")
    recs: List[Dict[str, str]] = []

    totals = analytics.get("totals", {})

    if totals.get("claims", 0) > 0:
        recs.append({
            "chart": "doughnut",
            "data_key": "confidence_mix",
            "label": "Evidence Confidence Distribution",
            "rationale": "Shows how solid the evidence base is at a glance.",
        })

    if len(analytics.get("source_distribution", [])) > 1:
        recs.append({
            "chart": "horizontal_bar",
            "data_key": "source_distribution",
            "label": "Claims by Source",
            "rationale": "Shows whether evidence is concentrated or diversified.",
        })

    if len(analytics.get("coverage", [])) > 1:
        recs.append({
            "chart": "grouped_bar",
            "data_key": "coverage",
            "label": "Coverage per Sub-Question",
            "rationale": "Shows which parts of the question have strong vs weak evidence.",
        })

    if totals.get("rounds", 0) > 0:
        recs.append({
            "chart": "line",
            "data_key": "claims_by_round",
            "label": "Evidence Accumulation",
            "rationale": "Shows how claims built up across rounds.",
        })

    if analytics.get("confidence_by_round"):
        recs.append({
            "chart": "line",
            "data_key": "confidence_by_round",
            "label": "Confidence Progression",
            "rationale": "Shows whether later rounds improved evidence quality.",
        })

    if mode == "discovery" and analytics.get("candidates_ranked"):
        recs.append({
            "chart": "horizontal_bar",
            "data_key": "candidates_ranked",
            "label": "Candidate Ranking",
            "rationale": "The primary output of a discovery run.",
        })

    if mode == "simulation" and mode_material.get("positions"):
        recs.append({
            "chart": "comparison_table",
            "data_key": "positions",
            "label": "Position Strength Comparison",
            "rationale": "Side-by-side comparison of arguments and weaknesses.",
        })

    if mode == "planning" and mode_material.get("options"):
        recs.append({
            "chart": "comparison_table",
            "data_key": "options",
            "label": "Options: Cost, Risk, Trade-offs",
            "rationale": "The decision matrix for a planning run.",
        })

    if mode == "market":
        recs.append({
            "chart": "timeline_table",
            "data_key": "claims",
            "label": "Dated Evidence Timeline",
            "rationale": "Market claims must show when each figure was true.",
        })

    if totals.get("contested", 0) > 0:
        recs.append({
            "chart": "status_table",
            "data_key": "contested",
            "label": "Contested Claims & Resolutions",
            "rationale": "Contradictions are findings — show them explicitly.",
        })

    return recs


def _compute_report(state):
    """Shared analytics + limitations assembly for ``analytics`` and ``build``.

    Kept in one place so the deterministic builder and the guidance payload can
    never disagree about what the run actually recorded.
    """
    from dataclasses import asdict
    from tools.research_tools import evaluate, mode_spec

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
    return raw, gate, spec, analytics, limitations


def _build_and_publish(state, run_id: str, raw: dict, analytics: dict,
                       limitations: List[str]) -> str:
    """Deterministically build the deck and publish it straight to the portal.

    The HTML is generated here (not by the agent) and POSTed directly to the
    portal deck endpoint, so the full document reaches the CDN without being
    truncated or simplified by the model. Returns the download URL.
    """
    from tools.registry import tool_error
    from tools.deck_builder import build_deck_html, _slug

    question = (raw.get("question") or "").strip() or "Research report"
    mode = (raw.get("mode") or "").strip() or "investigation"
    persona = (raw.get("persona") or "").strip() or "general analyst"
    filename = f"{_slug(question)}.html"

    html = build_deck_html(
        analytics=analytics,
        limitations=limitations,
        question=question,
        mode=mode,
        persona=persona,
        run_id=run_id,
    )

    import os
    import httpx

    gateway_token = (
        os.environ.get("GATEWAY_INTERNAL_TOKEN")
        or os.environ.get("HOSTED_GATEWAY_SHARED_SECRET")
    )
    if not gateway_token:
        return tool_error("No gateway token configured — cannot publish deck to portal")

    user_id = None
    try:
        from gateway.session_context import get_session_env
        user_id = get_session_env("ELIDIA_SESSION_USER_ID", "")
    except ImportError:
        pass

    portal_backend_url = os.environ.get(
        "PORTAL_API_BASE_URL", "http://127.0.0.1:8000"
    ).rstrip("/")

    try:
        with httpx.Client(timeout=30.0) as client:
            headers = {"Content-Type": "application/json", "X-Gateway-Token": gateway_token}
            if user_id:
                headers["X-Portal-User-Id"] = str(user_id)
            resp = client.post(
                f"{portal_backend_url}/agent-v2/v1/deck",
                headers=headers,
                json={
                    "html": html,
                    "filename": filename,
                    "run_id": run_id,
                    "question": question,
                    "mode": mode,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Deck build+publish failed: %s", exc)
        return tool_error(f"Deck build+publish failed: {exc}")

    url = data.get("url") or ""
    return json.dumps({
        "id": data.get("id"),
        "url": url,
        "download_url": url,
        "filename": data.get("filename", filename),
        "size_bytes": data.get("size_bytes"),
        "claims": analytics.get("totals", {}).get("claims", 0),
        "message": (
            f"Professional HTML deck built and published. Download link: {url}"
            if url else
            "Deck built and published, but no URL was returned."
        ),
    }, ensure_ascii=False, default=str)


def _handle(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error
    from tools.research_tools import _load

    # Default is the analytics call, which is what every existing caller does.
    action = str(args.get("action") or "analytics").strip().lower()
    if action == "publish":
        return _publish(args)
    if action == "list":
        return _list_published(args)
    if action not in ("analytics", "build"):
        return tool_error(
            f"unknown action {action!r}. Valid: analytics, build, publish, list")

    run_id = str(args.get("run_id") or "").strip()
    logger.debug(f"Entered into research_deck._handle: run_id={run_id}, action={action}")
    if not run_id:
        return tool_error("run_id is required")

    state = _load(run_id)
    if state is None:
        return tool_error(f"no research run {run_id!r} — use research_state action='list'")

    raw, gate, spec, analytics, limitations = _compute_report(state)

    if action == "build":
        return _build_and_publish(state, run_id, raw, analytics, limitations)

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

    # Chart recommendations based on what the run actually produced. Each
    # names a chart type and the analytics key it renders. The agent picks
    # the ones that serve THIS run — a discovery report foregrounds
    # candidate ranking, not source distribution.
    chart_recs = _chart_recommendations(raw.get("mode", ""), analytics, mode_material)

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
        "chart_recommendations": chart_recs,
        "design_guidance": DESIGN_GUIDANCE,
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
        "the user its path. On the portal (where write_file is not available), "
        "call this tool with action='build' — it deterministically renders the "
        "full professional HTML deck from the analytics and publishes it "
        "directly, returning a downloadable link the user can open. Do NOT "
        "compose the HTML yourself and do NOT pass HTML to portal_deck_publish; "
        "the model-composed markup is unreliable and gets truncated.\n\n"
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
                "enum": ["analytics", "build", "publish", "list"],
                "description": (
                    "analytics (default): numbers for composing the report · "
                    "build: deterministically render + publish the full HTML deck "
                    "(use this on the portal) · publish: upload a written deck · "
                    "list: decks published before"
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
