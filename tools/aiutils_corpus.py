#!/usr/bin/env python3
"""AiUtils platform corpora — 68 curated corpora, 4.4M embedded passages.

What this reaches
-----------------
Curated bodies of text the platform has already embedded: Indian law knowledge
and case law, IPC sections, contract clauses, medical Q&A and exam banks, arXiv
abstracts, S&P 500 company profiles, CVE records, job descriptions, and more.
Roughly 4.4 million passages across 68 corpora, searched by meaning rather than
by keyword.

This is distinct from ``aiutils_rag_*``, which reaches collections *you*
ingested. Nothing here is yours and nothing here can be written to.

Choosing corpora is your judgement
----------------------------------
``action="list"`` returns what exists — name, family, size, and with
``samples=true`` a real excerpt from each. Read it and decide which corpora can
answer the question in front of you.

There is no topic-to-corpus mapping in the system and none is coming. A rule
that sent "drug interaction" to a medical corpus would send "what did the court
say about the drug schedule" there too, and miss the legal corpus that actually
holds the answer. You can tell the difference; a substring cannot.

Two habits that make retrieval much better:

**Ask in the corpus's language.** A first round in the user's phrasing shows
you the vocabulary the corpus actually uses — statute numbers, drug
nomenclature, docket formats. Re-ask using those terms.

**Keep the misses.** The response names corpora that returned nothing. That is
a result: drop them from the next round and spend the budget on the ones that
produced usable passages.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# Enough passages to cross-check a claim without flooding the context. A
# research round wants several corroborating sources, not fifty near-duplicates.
DEFAULT_TOP_K = 8

# Below this, bge-m3 hits are usually topically adjacent rather than relevant.
# Not a hard filter — the caller can lower it — but a sane floor stops weak
# matches being cited as evidence.
DEFAULT_MIN_SIMILARITY = 0.45


def _client():
    from tools import aiutils_client
    return aiutils_client.get_client()


def _handle_list(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error
    from tools import aiutils_client

    family = (args.get("family") or "").strip() or None
    samples = bool(args.get("samples"))
    logger.debug(f"Entered into _handle_list: family={family}, samples={samples}")

    try:
        corpora = _client().rag.corpora(family=family, samples=samples)
    except Exception as exc:
        logger.warning("corpus listing failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="list corpora")
        return tool_error(handled or f"Could not list corpora: {exc}")

    if not corpora:
        return tool_error(
            f"No corpora found{f' in family {family!r}' if family else ''}. "
            f"Call this without a family filter to see every family available."
        )

    return json.dumps({
        "count": len(corpora),
        "families": sorted({c.get("family", "") for c in corpora}),
        "corpora": corpora,
        "note": (
            "Row counts are approximate. Pick the corpora that fit the "
            "question, then search with action='search'."
        ),
    }, indent=2, default=str)


def _handle_search(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error
    from tools import aiutils_client

    query = str(args.get("query") or "").strip()
    corpora = args.get("corpora") or []
    logger.debug(f"Entered into _handle_search: corpora={corpora}")

    if not query:
        return tool_error("query is required")
    if isinstance(corpora, str):
        # A single name is a reasonable thing to pass; accept it rather than
        # failing on a shape the caller could not have known was wrong.
        corpora = [corpora]
    if not corpora:
        return tool_error(
            "corpora is required — name at least one. Use action='list' to see "
            "what exists; which ones can answer this question is your call."
        )

    try:
        result = _client().rag.search_corpora(
            query, list(corpora),
            top_k=int(args.get("top_k") or DEFAULT_TOP_K),
            min_similarity=float(
                args.get("min_similarity", DEFAULT_MIN_SIMILARITY)),
        )
    except Exception as exc:
        logger.warning("corpus search failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="search corpora")
        return tool_error(handled or f"Could not search corpora: {exc}")

    hits = result.get("hits", [])
    empty = result.get("returned_nothing", [])

    if not hits:
        return tool_error(
            f"No passage above the similarity floor in {', '.join(result.get('searched', []))}. "
            f"Either these corpora do not cover it, or the wording is far from "
            f"how the corpus phrases it — try the corpus's own vocabulary, or "
            f"action='list' to pick differently."
        )

    return json.dumps({
        "query": result.get("query"),
        "searched": result.get("searched", []),
        "count": len(hits),
        "hits": hits,
        # Surfaced deliberately: a corpus that returned nothing is information
        # for the next round, not noise to hide.
        "returned_nothing": empty,
        "failed": result.get("failed", []),
    }, indent=2, default=str)


def handle_aiutils_corpus(args: Dict[str, Any], **kw) -> str:
    from tools.registry import tool_error

    action = str(args.get("action") or "list").strip().lower()
    logger.debug(f"Entered into handle_aiutils_corpus: action={action}")

    dispatch = {"list": _handle_list, "search": _handle_search}
    handler = dispatch.get(action)
    if handler is None:
        return tool_error(f"unknown action {action!r}. Valid: list, search")
    return handler(args, **kw)


AIUTILS_CORPUS_SCHEMA = {
    "name": "aiutils_corpus",
    "description": (
        "Search the AiUtils platform's curated corpora — about 4.4 million "
        "embedded passages across 68 corpora covering law (Indian law "
        "knowledge, case law, IPC sections, contract clauses), medicine "
        "(clinical Q&A, exam banks), research (arXiv abstracts), finance "
        "(company profiles), security (CVE records), careers and media.\n\n"
        "Use it whenever a question touches one of those areas: these are "
        "curated bodies of text, so they ground an answer far better than a web "
        "search, and they cost nothing to query.\n\n"
        "Start with action='list' (samples=true) to see what exists, then "
        "choose the corpora that fit and action='search'. Which corpora can "
        "answer a question is a judgement — there is no topic-to-corpus "
        "mapping, because the corpus a question belongs to often is not the one "
        "its wording suggests.\n\n"
        "Results include corpora that returned nothing; use that to drop them "
        "from a follow-up search and re-ask in the vocabulary the passages you "
        "did get actually use."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "search"],
                "description": "list: what corpora exist · search: query chosen corpora",
            },
            "query": {
                "type": "string",
                "description": "search: what to look for, in natural language.",
            },
            "corpora": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "search: corpus names from action='list'. At most 8."
                ),
            },
            "family": {
                "type": "string",
                "description": (
                    "list: narrow to one family, e.g. legal, medical, research, "
                    "finance, career, media, enterprise."
                ),
            },
            "samples": {
                "type": "boolean",
                "description": (
                    "list: include a real excerpt from each corpus. Worth it "
                    "when choosing — a name does not reveal what is inside."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": f"search: passages per corpus (default {DEFAULT_TOP_K}).",
            },
            "min_similarity": {
                "type": "number",
                "description": (
                    f"search: cosine floor, default {DEFAULT_MIN_SIMILARITY}. "
                    f"Lower it if a search returns nothing and you believe the "
                    f"corpus covers the topic."
                ),
            },
        },
        "required": ["action"],
    },
}


def check_aiutils_corpus_requirements() -> bool:
    """Available when the AiUtils Developer API is configured.

    A plain bool — the registry tests truthiness, and a `(False, "reason")`
    tuple is truthy, which would advertise this tool as available when the
    check had in fact failed.
    """
    logger.debug("Entered into check_aiutils_corpus_requirements")
    try:
        from tools import aiutils_client
        return bool(aiutils_client.check_aiutils_requirements())
    except Exception as exc:
        logger.warning("AiUtils platform corpora unavailable: %s", exc)
        return False


from tools.registry import registry, tool_error  # noqa: E402

registry.register(
    name="aiutils_corpus",
    toolset="aiutils",
    schema=AIUTILS_CORPUS_SCHEMA,
    handler=handle_aiutils_corpus,
    check_fn=check_aiutils_corpus_requirements,
    emoji="📚",
)
