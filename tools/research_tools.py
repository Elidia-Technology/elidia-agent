#!/usr/bin/env python3
"""Research loop substrate — durable state and a sufficiency floor the model cannot argue past.

The deep-research loop itself is agent *behaviour*, taught by the
`deep-research` skill: the agent decomposes a question, gathers, reads,
notices gaps and goes again, with every tool available at each step. That is
deliberate — a loop hidden inside one tool is a black box that can search and
write but cannot read code or run an experiment mid-investigation.

The problem with putting a loop in a prompt is that it drifts. Under context
pressure a model quietly stops early, skips verification, and declares success.
So this module holds the two things that must NOT be prose:

  ``research_state``  durable, checkpointed state for a run — rounds, claims,
                      sources, gaps. Survives interruption and resumes.

  ``research_gate``   arithmetic over that state. Says whether the evidence
                      clears a hard floor. The agent may consult it at any
                      time; it may not proceed past a refusal.

Division of responsibility, stated once because it is the whole design:

    The loop is behaviour.  The floor is code.

Two properties fall out of keeping the floor here rather than in the skill:

* **Fabricated citations cannot survive.** A claim is accepted only if its
  source was previously recorded as actually retrieved. A model that invents a
  plausible-looking URL gets the claim rejected, not merely discouraged.
* **The floor outranks the model's own verdict.** When REFLECT says "evidence
  sufficient" and the gate says otherwise, the gate wins. This mirrors
  ``CompletionCriteria`` in the v1 platform engine, whose docstring records why
  it exists: *"The LLM's REFLECT step can be over-optimistic and say 'evidence
  sufficient' after a single round with 2 low-confidence claims."*

Nothing in this module inspects the wording of anything. The gate is arithmetic
over recorded structure; every judgement call — which sub-questions, which
sources, what a claim says, how confident it is — belongs to the LLM and is
recorded here as data.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Storage ────────────────────────────────────────────────────────────

def _research_dir() -> Path:
    """Directory holding run checkpoints. Honours ELIDIA_CONFIG_DIR."""
    base = os.environ.get("ELIDIA_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".elidia")
    return Path(base) / "research"


# ── Defaults (caps are enforced here, never requested in a prompt) ──────

DEFAULT_MAX_ROUNDS = 4
MAX_ROUNDS_CEILING = 12
DEFAULT_WALL_CLOCK_SECONDS = 1800
MAX_WALL_CLOCK_SECONDS = 14400

VALID_CONFIDENCE = ("high", "medium", "low")

# Research modes. The loop is the same; termination and output contract differ.
# The MODEL picks one from this enum — it is never inferred from user text.
RESEARCH_MODES = {
    "investigation": "Evidence chain for a factual question — legal exposure, due diligence, OSINT.",
    "discovery": "Generate, rank and evaluate candidates — bio, drug, materials.",
    "simulation": "Argue opposing positions to exhaustion — case simulation, red-team.",
    "planning": "Cost options and name risks — launch, GTM, strategy.",
    "market": "Positions supported by dated data — trading, stock, competitive.",
}


# Per-mode behaviour. RESEARCH_MODES above stays a plain name->contract map
# because seven call sites read it that way; this carries what each mode
# additionally requires before it may stop.
#
# The shared floor (claims, sources, confidence, gaps) is not enough on its own:
# "candidates generated, ranked and evaluated" is not the same finish line as
# "evidence chain complete, contradictions resolved". A mode that terminates on
# generic criteria produces a discovery run with no ranked candidates, which is
# not discovery.
MODE_SPECS: Dict[str, Dict[str, Any]] = {
    "investigation": {
        "requires_contested_resolved": True,
        "output_sections": [
            "Findings — each with its evidence chain",
            "Contradictions and how they were resolved",
            "Confidence per finding",
            "Limitations and open questions",
        ],
    },
    "discovery": {
        "min_candidates": 3,
        "min_candidates_evaluated": 1,
        "requires_all_candidates_scored": True,
        "output_sections": [
            "Ranked candidates with rationale",
            "Evaluation results for the top candidates",
            "Evidence supporting each ranking",
            "Limitations and what was not explored",
        ],
    },
    "simulation": {
        # Two sides minimum, or it is not a simulation. Each argued at its
        # strongest and with its own weaknesses named — the mode exists to
        # argue against itself, and a run that stops after stating both
        # positions weakly has produced a summary that splits the difference.
        "min_positions": 2,
        "requires_positions_argued": True,
        "output_sections": [
            "Each position argued at its strongest",
            "Likely outcome and why",
            "Weaknesses in each position",
            "Limitations",
        ],
    },
    "planning": {
        # An option with no cost is a wish; an option with no named risk is a
        # plan nobody has stress-tested. One option is not a choice.
        "min_options": 2,
        "requires_options_costed": True,
        "output_sections": [
            "Options, each costed",
            "Trade-offs",
            "The risk that would sink each option",
            "Recommendation",
            "Limitations",
        ],
    },
    "market": {
        # A market claim without a date is unreadable a month later, and a
        # projection presented as a measurement is the failure mode of the
        # whole genre. A thesis that nothing could falsify is not a finding.
        "requires_dated_claims": True,
        "requires_falsifier": True,
        "output_sections": [
            "Thesis with dated supporting data",
            "Risk",
            "What would falsify the thesis",
            "Limitations",
            "This is research synthesis, not investment advice",
        ],
    },
}


def mode_spec(mode: str) -> Dict[str, Any]:
    """Extra requirements for a mode. Empty dict when it adds none."""
    return MODE_SPECS.get(mode, {})


@dataclass
class Criteria:
    """The hard floor. Defaults are deliberately modest — they exist to stop a
    one-round two-claim answer being called research, not to force exhaustion."""
    min_total_claims: int = 5
    min_unique_sources: int = 3
    min_high_confidence_ratio: float = 0.3
    require_no_open_gaps: bool = True


@dataclass
class RunState:
    run_id: str
    question: str
    mode: str = "investigation"
    persona: str = ""
    sub_questions: List[str] = field(default_factory=list)
    open_gaps: List[str] = field(default_factory=list)
    # Sources actually retrieved this run. A claim may only cite one of these.
    sources: List[str] = field(default_factory=list)
    claims: List[Dict[str, Any]] = field(default_factory=list)
    # Discovery mode: the things being ranked and evaluated.
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    # Investigation mode: adjudications of claims flagged contested.
    resolutions: List[Dict[str, Any]] = field(default_factory=list)
    # Simulation mode: the sides being argued. Each must be put at its
    # strongest AND have its weaknesses named before the run can conclude.
    positions: List[Dict[str, Any]] = field(default_factory=list)
    # Planning mode: the courses of action, each costed with its risk named.
    options: List[Dict[str, Any]] = field(default_factory=list)
    # Market mode: what would prove the thesis wrong. A thesis nothing could
    # falsify is not a finding.
    falsifier: str = ""
    # Progressive RAG (plan 5B): what was queried where, and what came back.
    # Kept per round so a later round can see which origins earned their budget
    # and which were queried twice for nothing.
    retrievals: List[Dict[str, Any]] = field(default_factory=list)
    rounds_done: int = 0
    max_rounds: int = DEFAULT_MAX_ROUNDS
    started_at: float = 0.0
    wall_clock_seconds: int = DEFAULT_WALL_CLOCK_SECONDS
    criteria: Dict[str, Any] = field(default_factory=lambda: asdict(Criteria()))
    notes: List[str] = field(default_factory=list)
    finished: bool = False

    def criteria_obj(self) -> Criteria:
        c = Criteria()
        for k, v in (self.criteria or {}).items():
            if hasattr(c, k):
                setattr(c, k, v)
        return c


def _path_for(run_id: str) -> Path:
    return _research_dir() / f"{run_id}.json"


def _save(state: RunState) -> None:
    """Write a checkpoint atomically.

    tmp + os.replace, not a plain write: a process killed mid-write must never
    leave a truncated JSON file that makes the run unresumable. Losing the last
    round is recoverable; losing the whole run because the file will not parse
    is not.
    """
    logger.debug(f"Entered into _save: run_id={state.run_id}, rounds={state.rounds_done}")
    d = _research_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = _path_for(state.run_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load(run_id: str) -> Optional[RunState]:
    logger.debug(f"Entered into _load: run_id={run_id}")
    path = _path_for(run_id)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("research run %s is unreadable: %s", run_id, exc)
        return None
    known = {f for f in RunState.__dataclass_fields__}
    return RunState(**{k: v for k, v in raw.items() if k in known})


# ── Gate evaluation ────────────────────────────────────────────────────

def evaluate(state: RunState) -> Dict[str, Any]:
    """Arithmetic over recorded state. No text inspection anywhere.

    Returns the full picture rather than a bare boolean, because the agent needs
    to know *what* is missing in order to close it — "need 2 more sources" is
    actionable, "not yet" is not.
    """
    logger.debug(
        f"Entered into evaluate: run_id={state.run_id}, claims={len(state.claims)}, "
        f"rounds={state.rounds_done}"
    )
    c = state.criteria_obj()
    unmet: List[str] = []

    total = len(state.claims)
    if total < c.min_total_claims:
        unmet.append(f"need {c.min_total_claims} claims, have {total}")

    cited = {
        (claim.get("source") or "").strip()
        for claim in state.claims
        if (claim.get("source") or "").strip()
    }
    if len(cited) < c.min_unique_sources:
        unmet.append(f"need {c.min_unique_sources} unique sources, have {len(cited)}")

    high = sum(
        1 for claim in state.claims
        if (claim.get("confidence") or "").strip().lower() == "high"
    )
    ratio = (high / total) if total else 0.0
    if total and ratio < c.min_high_confidence_ratio:
        unmet.append(
            f"need {c.min_high_confidence_ratio:.0%} high-confidence claims, "
            f"have {ratio:.0%} ({high}/{total})"
        )

    if c.require_no_open_gaps and state.open_gaps:
        unmet.append(
            f"{len(state.open_gaps)} open gap(s): " + "; ".join(state.open_gaps[:3])
        )

    # ── Mode-specific requirements on top of the shared floor ──────────
    spec = mode_spec(state.mode)

    if spec.get("requires_contested_resolved"):
        # An investigation that leaves its contradictions hanging has not
        # finished; "sources disagree" is the beginning of the work, not a
        # finding. Every claim flagged contested needs an adjudication.
        contested = [c_ for c_ in state.claims if c_.get("contested")]
        resolved_for = {
            (r.get("claim") or "").strip()
            for r in state.resolutions
            if (r.get("claim") or "").strip()
        }
        unresolved = [
            c_ for c_ in contested
            if (c_.get("claim") or "").strip() not in resolved_for
        ]
        if unresolved:
            unmet.append(
                f"{len(unresolved)} contested claim(s) unresolved — investigation mode "
                "requires each contradiction adjudicated"
            )

    min_cand = spec.get("min_candidates")
    if min_cand:
        if len(state.candidates) < min_cand:
            unmet.append(
                f"need {min_cand} candidates, have {len(state.candidates)}"
            )
        if spec.get("requires_all_candidates_scored"):
            unscored = [
                cand for cand in state.candidates
                if cand.get("score") is None
            ]
            if unscored:
                unmet.append(
                    f"{len(unscored)} candidate(s) unranked — discovery mode requires "
                    "every candidate scored before it can stop"
                )
        min_eval = spec.get("min_candidates_evaluated", 0)
        evaluated = [cand for cand in state.candidates if cand.get("evaluated")]
        if min_eval and len(evaluated) < min_eval:
            unmet.append(
                f"need {min_eval} evaluated candidate(s), have {len(evaluated)} — "
                "generating and ranking is not evaluating"
            )

    min_pos = spec.get("min_positions")
    if min_pos:
        if len(state.positions) < min_pos:
            unmet.append(
                f"need {min_pos} positions, have {len(state.positions)} — "
                "a simulation with one side is not a simulation"
            )
        if spec.get("requires_positions_argued"):
            # The mode's whole purpose: argue each side at its strongest, then
            # name what is wrong with it. A position left unargued or
            # unchallenged means the run stopped at a summary that splits the
            # difference, which is the outcome this exists to prevent.
            unargued = [p for p in state.positions if not (p.get("argument") or "").strip()]
            if unargued:
                unmet.append(
                    f"{len(unargued)} position(s) not yet argued: "
                    + ", ".join(p["name"] for p in unargued[:3])
                    + " — each side must be put at its strongest before concluding"
                )
            unchallenged = [p for p in state.positions if not p.get("weaknesses")]
            if unchallenged:
                unmet.append(
                    f"{len(unchallenged)} position(s) with no weakness named: "
                    + ", ".join(p["name"] for p in unchallenged[:3])
                    + " — a position argued with no weaknesses has not been tested"
                )

    min_opt = spec.get("min_options")
    if min_opt:
        if len(state.options) < min_opt:
            unmet.append(
                f"need {min_opt} options, have {len(state.options)} — "
                "one option is not a choice"
            )
        if spec.get("requires_options_costed"):
            uncosted = [o for o in state.options if not (o.get("cost") or "").strip()]
            if uncosted:
                unmet.append(
                    f"{len(uncosted)} option(s) uncosted: "
                    + ", ".join(o["name"] for o in uncosted[:3])
                    + " — an option with no cost is a wish"
                )
            unrisked = [o for o in state.options if not (o.get("risk") or "").strip()]
            if unrisked:
                unmet.append(
                    f"{len(unrisked)} option(s) with no risk named: "
                    + ", ".join(o["name"] for o in unrisked[:3])
                    + " — planning mode requires the risk that would sink each"
                )

    if spec.get("requires_dated_claims"):
        # A market figure without a date is unreadable a month later, and a
        # projection presented as a measurement is the failure mode of the
        # entire genre. Both are structural facts about the record, so both
        # are checked here rather than hoped for in the prompt.
        undated = [
            claim for claim in state.claims
            if not (claim.get("as_of") or "").strip()
        ]
        if undated:
            unmet.append(
                f"{len(undated)} claim(s) carry no date — market mode requires "
                "every figure dated, so a reader can tell how stale it is"
            )
        unbased = [
            claim for claim in state.claims
            if (claim.get("basis") or "").strip().lower() not in ("measured", "projected")
        ]
        if unbased:
            unmet.append(
                f"{len(unbased)} claim(s) do not say whether they are measured or "
                "projected — presenting a projection as a measurement is the "
                "failure this mode exists to prevent"
            )

    if spec.get("requires_falsifier") and not (state.falsifier or "").strip():
        unmet.append(
            "no falsifier recorded — market mode requires stating what "
            "observation would prove the thesis wrong (action='set_falsifier')"
        )

    # Budgets are separate from sufficiency: they say whether the run MAY
    # continue, not whether it SHOULD stop. A run can be simultaneously
    # insufficient and out of budget — that is an honest, reportable outcome.
    elapsed = (time.time() - state.started_at) if state.started_at else 0.0
    rounds_left = max(0, state.max_rounds - state.rounds_done)
    time_left = max(0.0, state.wall_clock_seconds - elapsed)
    budget_exhausted = rounds_left <= 0 or time_left <= 0

    reasons_exhausted = []
    if rounds_left <= 0:
        reasons_exhausted.append(f"round cap reached ({state.max_rounds})")
    if time_left <= 0:
        reasons_exhausted.append(f"wall clock exceeded ({state.wall_clock_seconds}s)")

    sufficient = not unmet
    if sufficient:
        verdict = "sufficient — the floor is cleared; you may synthesize"
    elif budget_exhausted:
        verdict = (
            "insufficient AND out of budget — stop and synthesize what you have, "
            "stating the unmet criteria as limitations in the report"
        )
    else:
        verdict = "insufficient — continue the loop; close the gaps listed below"

    return {
        "run_id": state.run_id,
        "sufficient": sufficient,
        "may_continue": not budget_exhausted,
        "verdict": verdict,
        "unmet": unmet,
        "budget_exhausted_because": reasons_exhausted,
        "stats": {
            "claims": total,
            "unique_sources": len(cited),
            "high_confidence": high,
            "high_confidence_ratio": round(ratio, 3),
            "open_gaps": len(state.open_gaps),
            "rounds_done": state.rounds_done,
            "rounds_left": rounds_left,
            "seconds_left": int(time_left),
        },
        "criteria": asdict(c),
        "mode": state.mode,
        "mode_requirements": spec,
        "output_contract": spec.get("output_sections", []),
    }


# ── research_state handlers ────────────────────────────────────────────

def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def _start(args: Dict[str, Any]) -> Dict[str, Any]:
    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "question is required to start a run"}

    mode = str(args.get("mode") or "investigation").strip().lower()
    if mode not in RESEARCH_MODES:
        return {
            "error": f"unknown mode {mode!r}",
            "valid_modes": sorted(RESEARCH_MODES),
        }

    # Validate the persona against the real registry. Accepting any string
    # would silently store an invented lens — the same class of failure as
    # DomainSpec.rag_collections naming 30 collections that never existed
    # (AIUT-2985): declared, never checked, and invisible because nothing read
    # it back. An empty persona is allowed; a wrong one is not.
    persona = str(args.get("persona") or "").strip()
    if persona:
        try:
            from tools.research_personas import valid_persona_names
            valid = valid_persona_names()
        except Exception as exc:  # registry unavailable — do not block the run
            logger.warning("persona registry unavailable, skipping validation: %s", exc)
            valid = []
        if valid and persona not in valid:
            return {
                "error": f"unknown persona {persona!r}",
                "valid_personas": valid,
                "hint": "call research_personas(action='list') to see personas and their resource packs",
            }

    subs = [str(s).strip() for s in (args.get("sub_questions") or []) if str(s).strip()]
    state = RunState(
        run_id=uuid.uuid4().hex[:12],
        question=question,
        mode=mode,
        persona=persona,
        sub_questions=subs,
        open_gaps=list(subs),
        started_at=time.time(),
        max_rounds=_clamp(args.get("max_rounds"), 1, MAX_ROUNDS_CEILING, DEFAULT_MAX_ROUNDS),
        wall_clock_seconds=_clamp(
            args.get("wall_clock_seconds"), 60, MAX_WALL_CLOCK_SECONDS, DEFAULT_WALL_CLOCK_SECONDS
        ),
    )
    _save(state)
    logger.info("research run %s started (mode=%s)", state.run_id, mode)
    return {
        "run_id": state.run_id,
        "mode": state.mode,
        "mode_contract": RESEARCH_MODES[state.mode],
        "sub_questions": state.sub_questions,
        "max_rounds": state.max_rounds,
        "wall_clock_seconds": state.wall_clock_seconds,
    }


def _record_sources(state: RunState, args: Dict[str, Any]) -> Dict[str, Any]:
    incoming = [str(s).strip() for s in (args.get("sources") or []) if str(s).strip()]
    added = [s for s in incoming if s not in state.sources]
    state.sources.extend(added)
    _save(state)
    return {"run_id": state.run_id, "added": len(added), "total_sources": len(state.sources)}


def _record_retrieval(state: RunState, args: Dict[str, Any]) -> Dict[str, Any]:
    """Record one retrieval: where it was queried, with what, and what came back.

    Progressive RAG needs the negative results as much as the positive ones. A
    corpus that returned nothing in round 1 is the reason round 2 does not
    spend its budget there, and that is only knowable if the miss was written
    down. ``returned_nothing`` is therefore a first-class outcome, not the
    absence of a record.

    Source identifiers produced here are registered as retrieved, so a claim
    may cite them. That is deliberate: retrieval and "this source exists" are
    the same event, and making the model call ``record_sources`` separately
    invites claims rejected for citing something it genuinely did fetch.
    """
    logger.debug(f"Entered into _record_retrieval: run_id={state.run_id}")
    origin = str(args.get("origin") or "").strip()
    query = str(args.get("query") or "").strip()
    if not origin:
        return {"error": "origin is required — the corpus, source or tool queried"}
    if not query:
        return {"error": "query is required — what was actually asked"}

    produced = [str(x).strip() for x in (args.get("sources") or []) if str(x).strip()]
    added = [x for x in produced if x not in state.sources]
    state.sources.extend(added)

    state.retrievals.append({
        "round": state.rounds_done,
        "origin": origin,
        "query": query,
        "produced": produced,
        "returned_nothing": not produced,
        "failed": bool(args.get("failed")),
    })
    _save(state)
    return {
        "run_id": state.run_id,
        "origin": origin,
        "round": state.rounds_done,
        "produced": len(produced),
        "newly_citable": len(added),
        "returned_nothing": not produced,
    }


def _retrieval_report(state: RunState) -> Dict[str, Any]:
    """What each origin has actually earned, so the next round can be aimed.

    Productivity is measured in **accepted claims**, not passages returned. An
    origin can return fifty passages that survive no scrutiny while another
    returns two that carry the answer; counting hits would send the next round
    to the noisy one.

    This reports and does not decide. Which origins to drop, and how to reword
    a query in the vocabulary the evidence actually used, are judgements — the
    arithmetic here just makes them answerable instead of guessed.
    """
    logger.debug(f"Entered into _retrieval_report: run_id={state.run_id}")
    # Which origin produced each source identifier.
    origin_of: Dict[str, str] = {}
    for entry in state.retrievals:
        for source in entry.get("produced", []):
            origin_of.setdefault(source, entry["origin"])

    claims_by_origin: Dict[str, int] = {}
    for claim in state.claims:
        origin = origin_of.get(claim.get("source", ""))
        if origin:
            claims_by_origin[origin] = claims_by_origin.get(origin, 0) + 1

    stats: Dict[str, Dict[str, Any]] = {}
    for entry in state.retrievals:
        origin = entry["origin"]
        row = stats.setdefault(origin, {
            "origin": origin, "times_queried": 0, "passages": 0,
            "empty_results": 0, "failures": 0, "claims_supported": 0,
            "queries_tried": [],
        })
        row["times_queried"] += 1
        row["passages"] += len(entry.get("produced", []))
        row["empty_results"] += 1 if entry.get("returned_nothing") else 0
        row["failures"] += 1 if entry.get("failed") else 0
        if entry["query"] not in row["queries_tried"]:
            row["queries_tried"].append(entry["query"])

    for origin, row in stats.items():
        row["claims_supported"] = claims_by_origin.get(origin, 0)

    ranked = sorted(stats.values(),
                    key=lambda r: (r["claims_supported"], r["passages"]),
                    reverse=True)
    unproductive = [r["origin"] for r in ranked
                    if r["claims_supported"] == 0 and r["times_queried"] >= 1]

    return {
        "run_id": state.run_id,
        "round": state.rounds_done,
        "origins": ranked,
        # Named as candidates, not as a decision. An origin can be right and
        # still have produced nothing yet because the query used the question's
        # wording rather than the corpus's.
        "no_claims_yet": unproductive,
        "guidance": (
            "Origins are ranked by accepted claims, not passages returned. "
            "Before dropping one in `no_claims_yet`, consider re-asking it in "
            "the vocabulary the accepted passages actually used — a corpus "
            "rarely phrases a thing the way the question does. `queries_tried` "
            "shows what has already been asked of each, so a round does not "
            "repeat itself."
        ),
    }


def _add_claims(state: RunState, args: Dict[str, Any]) -> Dict[str, Any]:
    """Record claims, rejecting any that cite a source never retrieved.

    This is the anti-fabrication check, and it lives in code because a prompt
    instruction not to invent citations is advice, whereas this is a wall. A
    model that produces a plausible URL it never fetched loses the claim.
    """
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, str]] = []
    known = set(state.sources)

    for raw in (args.get("claims") or []):
        if not isinstance(raw, dict):
            rejected.append({"reason": "not an object", "claim": str(raw)[:120]})
            continue
        text = str(raw.get("claim") or "").strip()
        source = str(raw.get("source") or "").strip()
        if not text:
            rejected.append({"reason": "empty claim", "source": source[:120]})
            continue
        if not source:
            rejected.append({"reason": "claim has no source", "claim": text[:120]})
            continue
        if source not in known:
            rejected.append({
                "reason": "source was never recorded as retrieved — record it with "
                          "action='record_sources' first, or drop the claim",
                "claim": text[:120],
                "source": source[:200],
            })
            continue
        confidence = str(raw.get("confidence") or "medium").strip().lower()
        if confidence not in VALID_CONFIDENCE:
            confidence = "medium"
        entry = {
            "claim": text,
            "source": source,
            "confidence": confidence,
            "sub_question": str(raw.get("sub_question") or "").strip(),
            "contested": bool(raw.get("contested")),
            "round": state.rounds_done,
        }
        # Market mode requires these; every other mode ignores them. Stored
        # whenever supplied so a run that changes mode does not lose them.
        as_of = str(raw.get("as_of") or "").strip()
        if as_of:
            entry["as_of"] = as_of
        basis = str(raw.get("basis") or "").strip().lower()
        if basis in ("measured", "projected"):
            entry["basis"] = basis
        accepted.append(entry)

    state.claims.extend(accepted)
    if rejected:
        state.notes.append(
            f"round {state.rounds_done}: rejected {len(rejected)} claim(s) citing unretrieved sources"
        )
    _save(state)
    logger.info(
        "research run %s: %d claims accepted, %d rejected",
        state.run_id, len(accepted), len(rejected),
    )
    return {
        "run_id": state.run_id,
        "accepted": len(accepted),
        "rejected": rejected,
        "total_claims": len(state.claims),
    }


def _add_candidates(state: RunState, args: Dict[str, Any]) -> Dict[str, Any]:
    """Record or update discovery candidates.

    Candidates are keyed by name so a later round can score or evaluate one
    already generated, rather than duplicating it — ranking is usually a
    separate pass from generation.
    """
    logger.debug(f"Entered into _add_candidates: run_id={state.run_id}")
    by_name = {c.get("name"): c for c in state.candidates}
    added, updated, rejected = 0, 0, []

    for raw in (args.get("candidates") or []):
        if not isinstance(raw, dict):
            rejected.append({"reason": "not an object", "value": str(raw)[:120]})
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            rejected.append({"reason": "candidate has no name"})
            continue

        score = raw.get("score")
        if score is not None:
            try:
                score = float(score)
            except (TypeError, ValueError):
                rejected.append({"reason": "score is not a number", "name": name})
                continue

        entry = by_name.get(name)
        if entry is None:
            entry = {"name": name, "score": None, "evaluated": False,
                     "rationale": "", "round": state.rounds_done}
            state.candidates.append(entry)
            by_name[name] = entry
            added += 1
        else:
            updated += 1

        if score is not None:
            entry["score"] = score
        if raw.get("rationale"):
            entry["rationale"] = str(raw["rationale"]).strip()
        if "evaluated" in raw:
            entry["evaluated"] = bool(raw["evaluated"])
        if raw.get("evaluation"):
            entry["evaluation"] = str(raw["evaluation"]).strip()

    _save(state)
    ranked = sorted(
        (c for c in state.candidates if c.get("score") is not None),
        key=lambda c: c["score"], reverse=True,
    )
    return {
        "run_id": state.run_id,
        "added": added,
        "updated": updated,
        "rejected": rejected,
        "total_candidates": len(state.candidates),
        "scored": len(ranked),
        "evaluated": sum(1 for c in state.candidates if c.get("evaluated")),
        "ranking": [{"name": c["name"], "score": c["score"]} for c in ranked[:10]],
    }


def _add_positions(state: RunState, args: Dict[str, Any]) -> Dict[str, Any]:
    """Record or update the sides being argued in a simulation.

    Keyed by name so a later round can strengthen an argument or add a
    weakness to a position already on the table, rather than duplicating it —
    arguing a side well is usually a separate pass from naming it.

    Nothing here judges the *quality* of an argument; that is not something
    arithmetic can see. What it does enforce is that a position cannot be
    quietly left unargued: the gate counts positions missing an argument or a
    weakness, and refuses to let the run stop while any remain.
    """
    logger.debug(f"Entered into _add_positions: run_id={state.run_id}")
    by_name = {p.get("name"): p for p in state.positions}
    added, updated, rejected = 0, 0, []

    for raw in (args.get("positions") or []):
        if not isinstance(raw, dict):
            rejected.append({"reason": "not an object", "value": str(raw)[:120]})
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            rejected.append({"reason": "position has no name"})
            continue

        entry = by_name.get(name)
        if entry is None:
            entry = {"name": name, "argument": "", "weaknesses": [],
                     "round": state.rounds_done}
            state.positions.append(entry)
            by_name[name] = entry
            added += 1
        else:
            updated += 1

        if raw.get("argument"):
            entry["argument"] = str(raw["argument"]).strip()
        incoming = raw.get("weaknesses") or []
        if isinstance(incoming, str):
            incoming = [incoming]
        for weakness in incoming:
            text_ = str(weakness).strip()
            if text_ and text_ not in entry["weaknesses"]:
                entry["weaknesses"].append(text_)

    _save(state)
    unargued = [p["name"] for p in state.positions if not p.get("argument")]
    unchallenged = [p["name"] for p in state.positions if not p.get("weaknesses")]
    return {
        "run_id": state.run_id,
        "added": added, "updated": updated, "rejected": rejected,
        "total_positions": len(state.positions),
        "missing_argument": unargued,
        "missing_weaknesses": unchallenged,
    }


def _add_options(state: RunState, args: Dict[str, Any]) -> Dict[str, Any]:
    """Record or update the options in a planning run.

    Cost and risk are separate fields rather than free prose because the gate
    has to be able to tell whether they are present. An option costed "TBD" is
    still uncosted, and the model can see that in the response.
    """
    logger.debug(f"Entered into _add_options: run_id={state.run_id}")
    by_name = {o.get("name"): o for o in state.options}
    added, updated, rejected = 0, 0, []

    for raw in (args.get("options") or []):
        if not isinstance(raw, dict):
            rejected.append({"reason": "not an object", "value": str(raw)[:120]})
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            rejected.append({"reason": "option has no name"})
            continue

        entry = by_name.get(name)
        if entry is None:
            entry = {"name": name, "cost": "", "risk": "", "trade_offs": "",
                     "round": state.rounds_done}
            state.options.append(entry)
            by_name[name] = entry
            added += 1
        else:
            updated += 1

        for field_name in ("cost", "risk", "trade_offs"):
            if raw.get(field_name):
                entry[field_name] = str(raw[field_name]).strip()

    _save(state)
    return {
        "run_id": state.run_id,
        "added": added, "updated": updated, "rejected": rejected,
        "total_options": len(state.options),
        "missing_cost": [o["name"] for o in state.options if not o.get("cost")],
        "missing_risk": [o["name"] for o in state.options if not o.get("risk")],
    }


def _set_falsifier(state: RunState, args: Dict[str, Any]) -> Dict[str, Any]:
    """Record what would prove the thesis wrong.

    Required before a market run can conclude. A thesis with no stated
    falsifier cannot be checked by the reader, and cannot be checked by the
    author either — which is how a projection becomes a conviction.
    """
    logger.debug(f"Entered into _set_falsifier: run_id={state.run_id}")
    falsifier = str(args.get("falsifier") or "").strip()
    if not falsifier:
        return {"error": "falsifier is required — what observation would prove "
                         "this thesis wrong?"}
    state.falsifier = falsifier
    _save(state)
    return {"run_id": state.run_id, "falsifier": falsifier}


def _resolve_contested(state: RunState, args: Dict[str, Any]) -> Dict[str, Any]:
    """Record how a contradiction was adjudicated.

    ``claim`` must match a claim already marked contested — an adjudication of
    something that was never in dispute is not a resolution, and would let an
    investigation clear its gate without addressing the real conflict.
    """
    logger.debug(f"Entered into _resolve_contested: run_id={state.run_id}")
    contested = {
        (c.get("claim") or "").strip()
        for c in state.claims if c.get("contested")
    }
    accepted, rejected = 0, []

    for raw in (args.get("resolutions") or []):
        if not isinstance(raw, dict):
            rejected.append({"reason": "not an object"})
            continue
        claim = str(raw.get("claim") or "").strip()
        assessment = str(raw.get("assessment") or "").strip()
        if not claim or not assessment:
            rejected.append({"reason": "resolution needs both claim and assessment"})
            continue
        if claim not in contested:
            rejected.append({
                "reason": "no contested claim matches this text — resolutions must "
                          "address a claim recorded with contested=true",
                "claim": claim[:120],
            })
            continue
        state.resolutions.append({
            "claim": claim,
            "assessment": assessment,
            "resolved": bool(raw.get("resolved", True)),
            "round": state.rounds_done,
        })
        accepted += 1

    _save(state)
    return {
        "run_id": state.run_id,
        "accepted": accepted,
        "rejected": rejected,
        "contested_total": len(contested),
        "resolutions_total": len(state.resolutions),
    }


def _set_gaps(state: RunState, args: Dict[str, Any]) -> Dict[str, Any]:
    state.open_gaps = [str(g).strip() for g in (args.get("gaps") or []) if str(g).strip()]
    _save(state)
    return {"run_id": state.run_id, "open_gaps": state.open_gaps}


def _next_round(state: RunState) -> Dict[str, Any]:
    state.rounds_done += 1
    _save(state)
    return {
        "run_id": state.run_id,
        "rounds_done": state.rounds_done,
        "rounds_left": max(0, state.max_rounds - state.rounds_done),
    }


def _finish(state: RunState) -> Dict[str, Any]:
    state.finished = True
    _save(state)
    return {"run_id": state.run_id, "finished": True, "gate": evaluate(state)}


def _get(state: RunState) -> Dict[str, Any]:
    d = asdict(state)
    # Full claim text can be very large; the agent asks for claims explicitly.
    d["claims_count"] = len(state.claims)
    d["claims"] = state.claims[-30:]
    d["candidates_ranked"] = sorted(
        (c for c in state.candidates if c.get("score") is not None),
        key=lambda c: c["score"], reverse=True,
    )
    d["gate"] = evaluate(state)
    return d


def _list_runs() -> Dict[str, Any]:
    d = _research_dir()
    if not d.exists():
        return {"runs": []}
    runs = []
    for path in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:25]:
        st = _load(path.stem)
        if st:
            runs.append({
                "run_id": st.run_id,
                "question": st.question[:120],
                "mode": st.mode,
                "rounds_done": st.rounds_done,
                "claims": len(st.claims),
                "finished": st.finished,
            })
    return {"runs": runs}


def handle_research_state(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error

    action = str(args.get("action") or "").strip().lower()
    logger.debug(f"Entered into handle_research_state: action={action}")

    if action == "start":
        return json.dumps(_start(args), indent=2)
    if action == "list":
        return json.dumps(_list_runs(), indent=2)

    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return tool_error(f"run_id is required for action={action!r}")
    state = _load(run_id)
    if state is None:
        return tool_error(f"no research run {run_id!r} — use action='list' to see runs")

    dispatch = {
        "record_sources": lambda: _record_sources(state, args),
        "record_retrieval": lambda: _record_retrieval(state, args),
        "retrieval_report": lambda: _retrieval_report(state),
        "add_claims": lambda: _add_claims(state, args),
        "set_gaps": lambda: _set_gaps(state, args),
        "add_candidates": lambda: _add_candidates(state, args),
        "add_positions": lambda: _add_positions(state, args),
        "add_options": lambda: _add_options(state, args),
        "set_falsifier": lambda: _set_falsifier(state, args),
        "resolve_contested": lambda: _resolve_contested(state, args),
        "next_round": lambda: _next_round(state),
        "finish": lambda: _finish(state),
        "get": lambda: _get(state),
    }
    fn = dispatch.get(action)
    if fn is None:
        return tool_error(
            f"unknown action {action!r}. Valid: start, record_sources, add_claims, "
            "set_gaps, add_candidates, resolve_contested, next_round, get, finish, list"
        )
    return json.dumps(fn(), indent=2, default=str)


def handle_research_gate(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error

    run_id = str(args.get("run_id") or "").strip()
    logger.debug(f"Entered into handle_research_gate: run_id={run_id}")
    if not run_id:
        return tool_error("run_id is required")
    state = _load(run_id)
    if state is None:
        return tool_error(f"no research run {run_id!r} — use research_state action='list'")
    return json.dumps(evaluate(state), indent=2)


# ── Schemas ────────────────────────────────────────────────────────────

RESEARCH_STATE_SCHEMA = {
    "name": "research_state",
    "description": (
        "Durable state for a deep-research run: sub-questions, retrieved sources, "
        "sourced claims, open gaps and round count. Checkpointed after every "
        "change, so a run interrupted at round 3 resumes instead of restarting.\n\n"
        "Use it as the memory of the research loop taught by the deep-research "
        "skill. Start a run, record sources as you retrieve them, add claims as "
        "you read, update gaps as you reflect, advance the round, then finish.\n\n"
        "IMPORTANT: a claim is only accepted if its source was already recorded "
        "via action='record_sources'. Claims citing a source that was never "
        "retrieved are rejected and returned to you — record the source first or "
        "drop the claim. This makes a fabricated citation impossible to store."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "record_sources", "record_retrieval",
                         "retrieval_report", "add_claims", "set_gaps",
                         "add_candidates", "add_positions",
                         "add_options", "set_falsifier", "resolve_contested",
                         "next_round", "get", "finish", "list"],
                "description": (
                    "start: begin a run (returns run_id) · record_retrieval: log "
                    "where you searched, with what query, and what came back — "
                    "including nothing · retrieval_report: which origins have "
                    "earned their budget, measured in accepted claims · "
                    "add_positions: simulation — the "
                    "sides being argued, each at its strongest with its own "
                    "weaknesses named · add_options: planning — each option "
                    "with its cost and the risk that would sink it · "
                    "set_falsifier: market — what observation would prove the "
                    "thesis wrong · record_sources: note what you "
                    "actually retrieved · add_claims: store sourced findings · set_gaps: "
                    "replace the open-gap list after reflecting · add_candidates: "
                    "generate/score/evaluate candidates (DISCOVERY mode) · resolve_contested: "
                    "adjudicate a contradiction (INVESTIGATION mode) · next_round: advance the "
                    "counter · get: read state + gate · finish: mark complete · list: recent runs"
                ),
            },
            "run_id": {"type": "string", "description": "Run to act on. Required for every action except start and list."},
            "question": {"type": "string", "description": "start: the research question."},
            "mode": {
                "type": "string",
                "enum": sorted(RESEARCH_MODES),
                "description": (
                    "start: the shape of the job, which sets what 'done' means. "
                    "investigation = evidence chain · discovery = ranked candidates · "
                    "simulation = opposing positions · planning = costed options · "
                    "market = dated positions with falsification condition."
                ),
            },
            "persona": {"type": "string", "description": "start: expert lens for the run (e.g. legal, medical, trader)."},
            "sub_questions": {
                "type": "array", "items": {"type": "string"},
                "description": "start: decomposition of the question. Each becomes an open gap.",
            },
            "max_rounds": {"type": "integer", "description": f"start: round cap (1-{MAX_ROUNDS_CEILING}, default {DEFAULT_MAX_ROUNDS})."},
            "wall_clock_seconds": {"type": "integer", "description": f"start: time budget (60-{MAX_WALL_CLOCK_SECONDS}, default {DEFAULT_WALL_CLOCK_SECONDS})."},
            "positions": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "add_positions (simulation): [{name, argument, weaknesses:[...]}]. "
                    "The gate refuses to let the run stop while any position "
                    "lacks an argument or a named weakness."
                ),
            },
            "options": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "add_options (planning): [{name, cost, risk, trade_offs}]. "
                    "cost and risk are required by the gate — an option with "
                    "no cost is a wish."
                ),
            },
            "falsifier": {
                "type": "string",
                "description": (
                    "set_falsifier (market): the observation that would prove "
                    "the thesis wrong."
                ),
            },
            "origin": {
                "type": "string",
                "description": (
                    "record_retrieval: what was queried — a corpus name, a "
                    "source like pubmed, or a tool. Productivity is tracked "
                    "per origin."
                ),
            },
            "failed": {
                "type": "boolean",
                "description": (
                    "record_retrieval: the origin could not be reached. "
                    "Different from returning nothing — a failure says nothing "
                    "about whether the evidence exists."
                ),
            },
            "sources": {
                "type": "array", "items": {"type": "string"},
                "description": (
                    "record_sources: identifiers (URLs, corpus refs) you actually "
                    "retrieved · record_retrieval: the identifiers this query "
                    "produced (omit or leave empty when it returned nothing — "
                    "that is a result worth recording)."
                ),
            },
            "claims": {
                "type": "array",
                "description": "add_claims: findings, each carrying the source it came from.",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string", "description": "What the source establishes."},
                        "source": {"type": "string", "description": "Must match a previously recorded source exactly."},
                        "confidence": {"type": "string", "enum": list(VALID_CONFIDENCE),
                                        "description": "high only when a source states it directly and unambiguously."},
                        "sub_question": {"type": "string", "description": "Which sub-question this answers."},
                        "contested": {"type": "boolean", "description": "True when sources disagree."},
                    },
                    "required": ["claim", "source"],
                },
            },
            "gaps": {
                "type": "array", "items": {"type": "string"},
                "description": "set_gaps: what remains unanswered. Replaces the current list.",
            },
            "candidates": {
                "type": "array",
                "description": (
                    "add_candidates (discovery mode): the things being ranked. Call again "
                    "with the same name to score or evaluate one already generated — "
                    "generation and ranking are usually separate passes."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Identifier. Reused to update an existing candidate."},
                        "score": {"type": "number", "description": "Ranking score. Higher is better. Discovery cannot finish while any candidate is unscored."},
                        "rationale": {"type": "string", "description": "Why this candidate, and why this score."},
                        "evaluated": {"type": "boolean", "description": "True once actually tested — not merely ranked."},
                        "evaluation": {"type": "string", "description": "What the evaluation found."},
                    },
                    "required": ["name"],
                },
            },
            "resolutions": {
                "type": "array",
                "description": (
                    "resolve_contested (investigation mode): how a contradiction was "
                    "adjudicated. `claim` must match a claim recorded with contested=true."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string", "description": "Exact text of the contested claim."},
                        "assessment": {"type": "string", "description": "What the sources disagree about and which position the evidence better supports."},
                        "resolved": {"type": "boolean", "description": "False when the conflict genuinely cannot be settled on available evidence."},
                    },
                    "required": ["claim", "assessment"],
                },
            },
        },
        "required": ["action"],
    },
}

RESEARCH_GATE_SCHEMA = {
    "name": "research_gate",
    "description": (
        "Check whether a research run has gathered enough evidence to stop. "
        "Returns a verdict plus exactly what is missing.\n\n"
        "This is the sufficiency floor, and it is arithmetic over recorded state "
        "— not an opinion. Consult it before you synthesize. If it says "
        "insufficient while you believe the evidence is adequate, the gate is "
        "right and you continue: judging your own coverage after one round is "
        "the failure mode it exists to catch.\n\n"
        "It also reports budget separately from sufficiency. A run can be both "
        "insufficient and out of rounds/time — in that case stop, synthesize "
        "what you have, and state the unmet criteria as limitations rather than "
        "presenting the answer as complete."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "The run to evaluate."},
        },
        "required": ["run_id"],
    },
}


def check_research_requirements() -> Tuple[bool, str]:
    """Available whenever the checkpoint directory can be created."""
    try:
        _research_dir().mkdir(parents=True, exist_ok=True)
        return True, ""
    except OSError as exc:
        return False, f"cannot create research state directory: {exc}"


from tools.registry import registry, tool_error  # noqa: E402

registry.register(
    name="research_state",
    toolset="deep_research",
    schema=RESEARCH_STATE_SCHEMA,
    handler=handle_research_state,
    check_fn=check_research_requirements,
    emoji="🔬",
)

registry.register(
    name="research_gate",
    toolset="deep_research",
    schema=RESEARCH_GATE_SCHEMA,
    handler=handle_research_gate,
    check_fn=check_research_requirements,
    emoji="🚦",
)
