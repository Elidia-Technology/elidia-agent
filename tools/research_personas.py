#!/usr/bin/env python3
"""Persona and mode selection for a research run — expert lens, resource pack, announcement.

A lawyer and a pharmacologist do not read the same way. Which expert lens a
research run adopts changes what counts as authority, what confidence means,
and which sources are worth opening at all. This module lets a run adopt the
right lens without the user naming it.

Reuses the existing personas
----------------------------
``elidia_cli.personas.BUILTIN_PERSONALITIES`` already defines ten (legal,
medical, business, trader, research_scientist, engineering, creative, writer,
student, musician). This module reads that registry rather than defining a
parallel one — an earlier draft of this work invented a second ten-persona set,
which is duplication that would drift.

Honouring the ambient-chat rule
-------------------------------
``personas.py`` records a deliberate decision:

    Selection stays with the user. [...] an agent that silently reframes itself
    as a legal counsel because a message mentioned a contract is worse than one
    that waits to be asked. Nothing here inspects user text.

That rule is right and is **not** overridden here. It governs ambient chat,
where reframing is silent, session-wide and untriggered. A research run differs
on all three counts: the user explicitly started one, the lens applies to that
run only, and the choice is announced and overridable. Ambient ``/personality``
behaviour is untouched by this module.

Selection is the model's, from a fixed enum
-------------------------------------------
This module does not classify the user's question. It lists what exists and
validates what the model chose. There is no keyword, substring or regex match
against user text anywhere here — that would be exactly the cue-list routing
the platform forbids, and it fails on the questions that matter most.

Resource packs are discovered, not asserted
-------------------------------------------
Each persona names candidate skills. Whether a skill is actually installed is
checked against the filesystem at resolve time, and anything missing is
reported rather than silently dropped. Naming resources that do not exist is
the ``DomainSpec.rag_collections`` failure (AIUT-2985), where 30 collections
were declared, none existed, and nothing noticed because nothing read the field.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Candidate skills per persona. Presence is verified at resolve time — this is
# a list of what would help, not a claim that any of it is installed.
DOMAIN_PACKS: Dict[str, List[str]] = {
    "legal": ["osint-investigation", "searxng-search", "domain-intel"],
    "medical": ["arxiv", "bioinformatics", "drug-discovery"],
    "research_scientist": ["arxiv", "bioinformatics", "huggingface-hub", "research-paper-writing"],
    "business": ["searxng-search", "polymarket"],
    "trader": ["polymarket", "searxng-search"],
    "engineering": ["gitnexus-explorer", "arxiv"],
    "creative": [],
    "writer": ["research-paper-writing"],
    "student": ["arxiv"],
    "musician": [],
}

# Where a persona's work is grounded beyond the open web. Descriptive, so the
# model can weigh a lens against the question; it grants no access by itself.
PACK_NOTES: Dict[str, str] = {
    "legal": "US case law via CourtListener (8M+ opinions, federal and state courts), "
             "federal regulations via Federal Register API, SEC EDGAR for corporate filings, "
             "scholarly legal research via OpenAlex/Crossref. Use the 'legal' research_sources pack.",
    "medical": "PubMed and Europe PMC (biomedical literature), ClinicalTrials.gov "
               "(registered studies with status/phase), OpenFDA (drug labels, adverse events), "
               "ChEMBL (drug-target interactions, compound data), UniProt (proteins), "
               "RCSB PDB (3D structures). Use the 'biomedical', 'pharmacology', or "
               "'molecular' research_sources packs depending on the question.",
    "research_scientist": "Full scholarly graph via Crossref and OpenAlex (citations, DOIs, venues), "
                          "PubMed/Europe PMC (life sciences), arXiv (preprints), US patents "
                          "via PatentsView, and all domain-specific sources. Use the 'scholarly' "
                          "research_sources pack as a starting point.",
    "business": "SEC EDGAR (10-K, 10-Q, 8-K corporate filings), US patents via PatentsView, "
                "scholarly business research via OpenAlex. Use the 'business' research_sources pack.",
    "trader": "Market and prediction-market sources. SEC EDGAR for filings. "
              "Research synthesis only, never advisory.",
    "engineering": "US patents via PatentsView (all tech domains — electronics, semiconductors, "
                   "mechanical, aerospace, drones, robotics, materials), scholarly engineering "
                   "research via OpenAlex/Crossref, arXiv for preprints. Use the 'engineering' "
                   "research_sources pack.",
    "creative": "Open web and scholarly sources (OpenAlex/Crossref) for design research, "
                "art history, and creative industry analysis.",
    "writer": "Open web, scholarly sources, and academic writing structure.",
    "student": "Open web, arXiv, and all scholarly sources (OpenAlex/Crossref).",
    "musician": "Open web and scholarly sources for musicology and audio research.",
}


def _skill_installed(name: str) -> bool:
    """True when a skill directory with a SKILL.md exists in the repo tree.

    Checked, not assumed. Optional skills in particular are not activated by
    default, so a persona naming one is expressing a preference, not a fact.
    """
    for base in ("skills", "optional-skills"):
        root = _REPO_ROOT / base
        if not root.is_dir():
            continue
        for path in root.rglob(name):
            if path.is_dir() and (path / "SKILL.md").is_file():
                return True
    return False


def _personas() -> Dict[str, Dict[str, Any]]:
    """The canonical persona registry. Never a local copy."""
    from elidia_cli.personas import BUILTIN_PERSONALITIES
    return BUILTIN_PERSONALITIES


def valid_persona_names() -> List[str]:
    return sorted(_personas())


def _list_payload() -> Dict[str, Any]:
    """Everything the model needs to choose a lens — and nothing it must guess."""
    logger.debug("Entered into _list_payload")
    from tools.research_tools import RESEARCH_MODES

    personas = []
    for key, spec in sorted(_personas().items()):
        candidates = DOMAIN_PACKS.get(key, [])
        available = [s for s in candidates if _skill_installed(s)]
        personas.append({
            "persona": key,
            "description": spec.get("description", ""),
            "resource_pack": available,
            "resource_pack_unavailable": [s for s in candidates if s not in available],
            "grounding": PACK_NOTES.get(key, ""),
        })
    return {
        "personas": personas,
        "modes": [{"mode": m, "contract": c} for m, c in sorted(RESEARCH_MODES.items())],
        "how_to_choose": (
            "Pick the lens whose way of reading evidence fits the question, and the mode "
            "whose termination contract matches the job. Use 'general' reasoning under any "
            "persona when none is a clean fit — a wrong lens is worse than a neutral one."
        ),
    }


def _resolve(persona: str, mode: str) -> Dict[str, Any]:
    """Validate a chosen lens and return what a run needs to adopt it."""
    logger.debug(f"Entered into _resolve: persona={persona!r}, mode={mode!r}")
    from tools.research_tools import RESEARCH_MODES

    registry = _personas()
    if persona not in registry:
        return {
            "error": f"unknown persona {persona!r}",
            "valid_personas": valid_persona_names(),
        }
    if mode not in RESEARCH_MODES:
        return {
            "error": f"unknown mode {mode!r}",
            "valid_modes": sorted(RESEARCH_MODES),
        }

    spec = registry[persona]
    candidates = DOMAIN_PACKS.get(persona, [])
    available = [s for s in candidates if _skill_installed(s)]
    missing = [s for s in candidates if s not in available]

    announcement = (
        f"Researching as {persona} in {mode} mode"
        + (f" — using {', '.join(available)}." if available else ".")
    )

    return {
        "persona": persona,
        "mode": mode,
        "system_prompt": spec.get("system_prompt", ""),
        "tone": spec.get("tone", ""),
        "description": spec.get("description", ""),
        "mode_contract": RESEARCH_MODES[mode],
        "resource_pack": available,
        "resource_pack_unavailable": missing,
        "grounding": PACK_NOTES.get(persona, ""),
        "announcement": announcement,
        "next_step": (
            "Tell the user the announcement above before starting, and honour an override. "
            "Then call research_state(action='start', persona=..., mode=...)."
        ),
    }


def handle_research_personas(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error

    action = str(args.get("action") or "list").strip().lower()
    logger.debug(f"Entered into handle_research_personas: action={action}")

    if action == "list":
        return json.dumps(_list_payload(), indent=2)
    if action == "resolve":
        persona = str(args.get("persona") or "").strip()
        mode = str(args.get("mode") or "").strip().lower()
        if not persona:
            return tool_error("persona is required for action='resolve'")
        if not mode:
            return tool_error("mode is required for action='resolve'")
        return json.dumps(_resolve(persona, mode), indent=2)
    return tool_error(f"unknown action {action!r}. Valid: list, resolve")


RESEARCH_PERSONAS_SCHEMA = {
    "name": "research_personas",
    "description": (
        "Expert lenses and research modes available for a deep-research run, and "
        "what each one is grounded in.\n\n"
        "Call action='list' BEFORE starting a run to see the personas that exist, "
        "the modes and their termination contracts, and which domain skills are "
        "actually installed for each persona. Then choose the lens whose way of "
        "reading evidence fits the question — a research lawyer reasons from "
        "binding authority and jurisdiction, a clinical researcher weighs "
        "evidence by study design.\n\n"
        "Call action='resolve' with your choice to get the persona's system "
        "prompt, its resource pack, and an announcement line. Tell the user which "
        "lens you are using before you begin, and honour an override — the choice "
        "should never be silent.\n\n"
        "This tool reports what exists; it does not classify the question for "
        "you. The choice is yours."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "resolve"],
                "description": "list: personas, modes and installed packs. resolve: validate a choice and get its prompt + announcement.",
            },
            "persona": {
                "type": "string",
                "description": "resolve: the persona key, exactly as returned by action='list'.",
            },
            "mode": {
                "type": "string",
                "description": "resolve: the research mode, exactly as returned by action='list'.",
            },
        },
        "required": ["action"],
    },
}


def check_research_personas_requirements() -> Tuple[bool, str]:
    """Available whenever the persona registry imports."""
    try:
        if not _personas():
            return False, "no personas are defined"
        return True, ""
    except Exception as exc:
        return False, f"persona registry unavailable: {exc}"


from tools.registry import registry, tool_error  # noqa: E402

registry.register(
    name="research_personas",
    toolset="deep_research",
    schema=RESEARCH_PERSONAS_SCHEMA,
    handler=handle_research_personas,
    check_fn=check_research_personas_requirements,
    emoji="🎭",
)
