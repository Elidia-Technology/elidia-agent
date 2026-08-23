#!/usr/bin/env python3
"""
AiUtils RAG tools — ingest documents and search them (B6).

Gives the agent a durable memory of the user's own material. Anything ingested
stays searchable across sessions, which is the difference between an agent that
must be re-told context every time and one that can look it up.

Four tools, all in the opt-in ``aiutils`` toolset:

  aiutils_rag_ingest       store text in a collection
  aiutils_rag_search       retrieve the most relevant chunks
  aiutils_rag_collections  list collections with their sizes
  aiutils_rag_documents    list what has been ingested

All are UNBILLED and therefore deliberately skip the credit guard. Embeddings
run on AiUtils' own hardware, so no vendor is charged; guarding them would also
refuse retrieval on an empty wallet, which is exactly when a user most needs
their own notes. This is the same call made for the catalog tools in
aiutils_models.py: guard what spends, never what reads.

Search returns CHUNKS, never a written answer. The agent synthesises from them
with its own model call, and that call is where DT is charged — so there is no
path here that could bill twice for one question.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

from tools import aiutils_client
from tools.registry import registry, tool_error

# Long enough for a substantial document, short enough that one call cannot pin
# the embedder. The gateway enforces its own limit; this fails faster and names
# the reason.
MAX_INGEST_CHARS = 200_000
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
# Chunks are ~1200 chars; a handful already fills useful context. Truncating in
# the tool result keeps a broad search from flooding the window.
CHUNK_PREVIEW_CHARS = 1500


INGEST_SCHEMA = {
    "name": "aiutils_rag_ingest",
    "description": (
        "Store text in the user's RAG knowledge base so it can be retrieved in "
        "this and future sessions. Use for reference material the user wants "
        "remembered — documentation, notes, transcripts, specs. Free. Creates "
        "the collection if it does not exist; re-ingesting identical content is "
        "a no-op."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "collection": {
                "type": "string",
                "description": "Collection to store into, e.g. 'notes' or 'project-docs'.",
            },
            "content": {"type": "string", "description": "The text to store."},
            "title": {"type": "string", "description": "Short label for this document."},
            "source_ref": {
                "type": "string",
                "description": "Where it came from — a file path or URL.",
            },
        },
        "required": ["collection", "content"],
    },
}

SEARCH_SCHEMA = {
    "name": "aiutils_rag_search",
    "description": (
        "Search the user's RAG knowledge base and return the most relevant "
        "chunks. Use before answering questions about the user's own documents, "
        "notes or prior context. Returns source passages to reason from, not a "
        "written answer. Free."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for."},
            "collection": {
                "type": "string",
                "description": "Restrict to one collection. Omit to search all of them.",
            },
            "top_k": {
                "type": "integer",
                "description": f"How many chunks to return (default {DEFAULT_TOP_K}, max {MAX_TOP_K}).",
            },
            "rerank": {
                "type": "boolean",
                "description": "Reorder results with a cross-encoder — more accurate, slightly slower.",
            },
        },
        "required": ["query"],
    },
}

COLLECTIONS_SCHEMA = {
    "name": "aiutils_rag_collections",
    "description": (
        "List the user's RAG collections with document and chunk counts. Use to "
        "discover what knowledge bases exist before searching or ingesting."
    ),
    "parameters": {"type": "object", "properties": {}},
}

DOCUMENTS_SCHEMA = {
    "name": "aiutils_rag_documents",
    "description": (
        "List documents already ingested into the RAG knowledge base, optionally "
        "within one collection. Use to check whether something is already stored."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "collection": {"type": "string", "description": "Restrict to one collection."},
        },
    },
}


def _handle_ingest(args, **kw):
    collection = (args.get("collection") or "").strip()
    content = args.get("content") or ""
    if not collection:
        return tool_error("collection is required")
    if not content.strip():
        return tool_error("content is required")
    if len(content) > MAX_INGEST_CHARS:
        return tool_error(
            f"content is {len(content)} characters; the limit is {MAX_INGEST_CHARS}. "
            "Split it into several ingests."
        )

    try:
        client = aiutils_client.get_client()
        result = client.rag.ingest(
            collection=collection,
            content=content,
            title=args.get("title"),
            source_ref=args.get("source_ref"),
            source_type="text" if not args.get("source_ref") else "file",
        )
    except Exception as exc:
        logger.warning("aiutils_rag_ingest failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="ingest")
        return tool_error(handled or f"Ingest failed: {exc}")

    return json.dumps(
        {
            "document_id": str(getattr(result, "document_id", "")),
            "collection": getattr(result, "collection", collection),
            "chunks": getattr(result, "chunks", 0),
            "skipped": bool(getattr(result, "skipped", False)),
            "note": (
                "Identical content was already stored, so nothing was re-embedded."
                if getattr(result, "skipped", False)
                else "Stored and searchable."
            ),
        },
        ensure_ascii=False,
    )


def _handle_search(args, **kw):
    query = (args.get("query") or "").strip()
    if not query:
        return tool_error("query is required")

    try:
        top_k = int(args.get("top_k") or DEFAULT_TOP_K)
    except (TypeError, ValueError):
        top_k = DEFAULT_TOP_K
    top_k = max(1, min(top_k, MAX_TOP_K))

    try:
        client = aiutils_client.get_client()
        hits = client.rag.search(
            query=query,
            collection=(args.get("collection") or "").strip() or None,
            top_k=top_k,
            rerank=bool(args.get("rerank", False)),
        )
    except Exception as exc:
        logger.warning("aiutils_rag_search failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="search")
        return tool_error(handled or f"Search failed: {exc}")

    results = []
    for hit in hits:
        content = getattr(hit, "content", "") or ""
        truncated = len(content) > CHUNK_PREVIEW_CHARS
        results.append(
            {
                "content": content[:CHUNK_PREVIEW_CHARS] + ("…" if truncated else ""),
                "score": round(float(getattr(hit, "score", 0.0) or 0.0), 4),
                "collection": getattr(hit, "collection", None),
                "title": getattr(hit, "title", None),
                "source_ref": getattr(hit, "source_ref", None),
                "truncated": truncated,
            }
        )

    return json.dumps(
        {
            "query": query,
            "count": len(results),
            "results": results,
            "note": (
                "No matching content found. The knowledge base may be empty — "
                "aiutils_rag_collections shows what exists."
                if not results
                else "Source passages, not an answer — reason from them."
            ),
        },
        ensure_ascii=False,
    )


def _handle_collections(args, **kw):
    try:
        client = aiutils_client.get_client()
        collections = client.rag.list_collections()
    except Exception as exc:
        logger.warning("aiutils_rag_collections failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="collection listing")
        return tool_error(handled or f"Could not list collections: {exc}")

    return json.dumps(
        {
            "collections": [
                {
                    "name": getattr(c, "name", None),
                    "kind": getattr(c, "kind", "user"),
                    "documents": getattr(c, "document_count", 0),
                    "chunks": getattr(c, "chunk_count", 0),
                    "description": getattr(c, "description", None),
                }
                for c in collections
            ],
            "total": len(collections),
        },
        ensure_ascii=False,
    )


def _handle_documents(args, **kw):
    try:
        client = aiutils_client.get_client()
        documents = client.rag.list_documents(
            collection=(args.get("collection") or "").strip() or None
        )
    except Exception as exc:
        logger.warning("aiutils_rag_documents failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="document listing")
        return tool_error(handled or f"Could not list documents: {exc}")

    return json.dumps(
        {
            "documents": [
                {
                    "id": str(getattr(d, "id", "")),
                    "title": getattr(d, "title", None),
                    "collection": getattr(d, "collection", None),
                    "source_ref": getattr(d, "source_ref", None),
                    "chunks": getattr(d, "chunk_count", 0),
                }
                for d in documents
            ],
            "total": len(documents),
        },
        ensure_ascii=False,
    )


registry.register(
    name="aiutils_rag_ingest",
    toolset="aiutils",
    schema=INGEST_SCHEMA,
    handler=_handle_ingest,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="📥",
)

registry.register(
    name="aiutils_rag_search",
    toolset="aiutils",
    schema=SEARCH_SCHEMA,
    handler=_handle_search,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🔍",
)

registry.register(
    name="aiutils_rag_collections",
    toolset="aiutils",
    schema=COLLECTIONS_SCHEMA,
    handler=_handle_collections,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="🗂",
)

registry.register(
    name="aiutils_rag_documents",
    toolset="aiutils",
    schema=DOCUMENTS_SCHEMA,
    handler=_handle_documents,
    check_fn=aiutils_client.check_aiutils_requirements,
    emoji="📄",
)
