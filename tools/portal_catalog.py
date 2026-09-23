"""
Portal tool catalog — discover, recommend, and open AiUtils portal tools.

Calls the portal backend at localhost:8000 directly (no Developer API key
needed). The gateway runs on the same machine as the portal, so this is a
local HTTP call. Used by the elidia-web-portal toolset to give the v2 agent
awareness of all 100+ portal AI tools.

Three tools:
  portal_tool_catalog   — list tools, optionally filtered by genre/search
  portal_tool_open      — redirect the user to a specific tool page
  portal_tool_search    — semantic search across tools by natural language
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from tools.registry import registry, tool_error

PORTAL_BACKEND_URL = os.environ.get(
    "PORTAL_API_BASE_URL", "http://127.0.0.1:8000"
).rstrip("/")

PORTAL_WEB_URL = os.environ.get(
    "AIUTILS_PORTAL_URL", "https://aiutils.io"
).rstrip("/")

_CATALOG_TTL = 600
_catalog_cache: Dict[str, Any] = {"fetched_at": 0.0, "tools": [], "genres": {}}


def _fetch_catalog(force: bool = False) -> Dict[str, Any]:
    logger.debug("Entered into _fetch_catalog: force=%s", force)
    now = time.time()
    if not force and _catalog_cache["tools"] and (now - _catalog_cache["fetched_at"]) < _CATALOG_TTL:
        return _catalog_cache

    import httpx

    try:
        with httpx.Client(timeout=10.0) as client:
            all_tools: List[Dict[str, Any]] = []
            page = 1
            while True:
                tools_resp = client.get(
                    f"{PORTAL_BACKEND_URL}/api/v1/tools/",
                    params={"page_size": 100, "page": page},
                )
                tools_resp.raise_for_status()
                tools_data = tools_resp.json()
                batch = tools_data.get("tools", [])
                all_tools.extend(batch)
                if page >= tools_data.get("total_pages", 1) or not batch:
                    break
                page += 1

            genres_resp = client.get(f"{PORTAL_BACKEND_URL}/api/v1/tools/genres")
            genres_resp.raise_for_status()
            genres_data = genres_resp.json()

        _catalog_cache["tools"] = all_tools
        _catalog_cache["genres"] = genres_data.get("genres", {})
        _catalog_cache["fetched_at"] = now
        logger.info("Portal catalog loaded: %d tools, %d genres",
                     len(_catalog_cache["tools"]), len(_catalog_cache["genres"]))
    except Exception as exc:
        logger.warning("Failed to fetch portal catalog: %s", exc)
        if not _catalog_cache["tools"]:
            raise

    return _catalog_cache


def _compact_tool(t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": t.get("name", ""),
        "slug": t.get("slug", ""),
        "description": (t.get("description") or "")[:200],
        "genre": t.get("genre", ""),
        "credit_cost": t.get("credit_cost"),
        "execution_type": t.get("execution_type"),
        "url": f"{PORTAL_WEB_URL}/tools/{t.get('slug', '')}",
    }


CATALOG_SCHEMA = {
    "name": "portal_tool_catalog",
    "description": (
        "List all AiUtils portal AI tools the user can access. Optionally "
        "filter by genre (e.g. 'image_media', 'video_media', 'law_tools', "
        "'enterprise_ai') or search by name/keyword. Returns tool name, slug, "
        "description, credit cost, and a direct URL. Use this to discover "
        "what tools are available before recommending one."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "genre": {
                "type": "string",
                "description": (
                    "Filter by genre key, e.g. 'image_media', 'video_media', "
                    "'law_tools', 'enterprise_ai', 'writing', 'audio_media', "
                    "'medical', 'seo', 'communication', 'data_utility', "
                    "'fashion_design', '3d', 'career', 'entertainment', "
                    "'shopping', 'digital_marketing', 'safety', 'n8n_workflow', "
                    "'chat_ai'."
                ),
            },
            "search": {
                "type": "string",
                "description": "Free-text search over tool names and descriptions.",
            },
            "limit": {
                "type": "integer",
                "description": "Max tools to return (default 20, max 50).",
            },
        },
    },
}

OPEN_TOOL_SCHEMA = {
    "name": "portal_tool_open",
    "description": (
        "Recommend and open a specific AiUtils portal tool for the user. "
        "Returns the tool's name, URL, and a message the user can click to "
        "open it. Use this when the user's request matches a portal tool "
        "better than what the agent can do directly — e.g. image editing, "
        "video studio, music production, logo design, legal analysis, "
        "enterprise reports. Always call portal_tool_catalog first to find "
        "the right slug."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_slug": {
                "type": "string",
                "description": "The tool slug to open, e.g. 'image-editor', 'video-factory'.",
            },
        },
        "required": ["tool_slug"],
    },
}


def _handle_catalog(args, **kw):
    logger.debug("Entered into _handle_catalog: args=%s", args)
    try:
        catalog = _fetch_catalog()
    except Exception as exc:
        return tool_error(f"Could not load tool catalog: {exc}")

    tools = catalog["tools"]
    genre_filter = (args.get("genre") or "").strip().lower()
    search_query = (args.get("search") or "").strip().lower()
    limit = min(max(int(args.get("limit") or 20), 1), 50)

    if genre_filter:
        tools = [t for t in tools if (t.get("genre") or "").lower() == genre_filter]

    if search_query:
        scored: List[tuple] = []
        for t in tools:
            name = (t.get("name") or "").lower()
            desc = (t.get("description") or "").lower()
            slug = (t.get("slug") or "").lower()
            if search_query in name:
                scored.append((0, t))
            elif search_query in slug:
                scored.append((1, t))
            elif search_query in desc:
                scored.append((2, t))
        scored.sort(key=lambda x: x[0])
        tools = [s[1] for s in scored]

    compact = [_compact_tool(t) for t in tools[:limit]]
    genres_info = {k: v.get("label", k) for k, v in catalog.get("genres", {}).items()}

    return json.dumps({
        "tools": compact,
        "count": len(compact),
        "total_available": len(catalog["tools"]),
        "genres": genres_info,
        "note": (
            "Use portal_tool_open with a tool's slug to recommend it to the user."
            if compact else
            "No tools matched your filter. Try a broader search or list all tools."
        ),
    }, ensure_ascii=False, default=str)


def _handle_open_tool(args, **kw):
    logger.debug("Entered into _handle_open_tool: args=%s", args)
    slug = (args.get("tool_slug") or "").strip()
    if not slug:
        return tool_error("tool_slug is required")

    try:
        catalog = _fetch_catalog()
    except Exception:
        pass

    tool_entry = None
    for t in _catalog_cache.get("tools", []):
        if t.get("slug") == slug:
            tool_entry = t
            break

    name = (tool_entry or {}).get("name", slug)
    url = f"{PORTAL_WEB_URL}/tools/{slug}"
    description = (tool_entry or {}).get("description", "")

    return json.dumps({
        "action": "open_url",
        "tool_slug": slug,
        "name": name,
        "url": url,
        "description": description[:200] if description else "",
        "credit_cost": (tool_entry or {}).get("credit_cost"),
        "message": (
            f"I'd suggest **{name}** for this.\n\n"
            f"Open it here: {url}"
            + (f"\n\n{description[:200]}" if description else "")
        ),
    }, ensure_ascii=False, default=str)


RAG_SEARCH_SCHEMA = {
    "name": "portal_rag_search",
    "description": (
        "Search the AiUtils portal knowledge base (RAG) for relevant "
        "documents and facts. Uses hybrid semantic + keyword search across "
        "the user's ingested knowledge. Use this to ground your answers in "
        "portal-specific knowledge when the user asks about topics covered "
        "by the portal's AI tools, documentation, or domain knowledge."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query (natural language).",
            },
            "top_k": {
                "type": "integer",
                "description": "Max results to return (default 5, max 20).",
            },
        },
        "required": ["query"],
    },
}


def _handle_rag_search(args, **kw):
    logger.debug("Entered into _handle_rag_search: args=%s", args)
    query = (args.get("query") or "").strip()
    if not query:
        return tool_error("query is required")

    top_k = min(max(int(args.get("top_k") or 5), 1), 20)

    gateway_token = os.environ.get("GATEWAY_INTERNAL_TOKEN") or os.environ.get("HOSTED_GATEWAY_SHARED_SECRET")
    if not gateway_token:
        return tool_error("No gateway token configured — cannot access portal RAG")

    user_id = None
    try:
        from gateway.session_context import get_session_env
        user_id = get_session_env("ELIDIA_SESSION_USER_ID", "")
    except ImportError:
        pass

    import httpx

    try:
        with httpx.Client(timeout=15.0) as client:
            headers = {
                "Content-Type": "application/json",
                "X-Gateway-Token": gateway_token,
            }
            if user_id:
                headers["X-Portal-User-Id"] = str(user_id)

            resp = client.post(
                f"{PORTAL_BACKEND_URL}/agent-v2/v1/rag/search",
                headers=headers,
                json={"query": query, "top_k": top_k},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Portal RAG search failed: %s", exc)
        return tool_error(f"RAG search failed: {exc}")

    results = data.get("results", [])
    return json.dumps({
        "query": query,
        "results": [
            {
                "key": r.get("key", ""),
                "value": r.get("value", ""),
                "score": r.get("hybrid_score", 0.0),
            }
            for r in results
        ],
        "total": data.get("total", len(results)),
        "note": "Use these knowledge base results to ground your response." if results else "No results found in the knowledge base.",
    }, ensure_ascii=False, default=str)


def _check_portal_available() -> bool:
    return True


registry.register(
    name="portal_tool_catalog",
    toolset="portal",
    schema=CATALOG_SCHEMA,
    handler=_handle_catalog,
    check_fn=_check_portal_available,
    emoji="\U0001f5c2️",
)

registry.register(
    name="portal_tool_open",
    toolset="portal",
    schema=OPEN_TOOL_SCHEMA,
    handler=_handle_open_tool,
    check_fn=_check_portal_available,
    emoji="\U0001f517",
)

registry.register(
    name="portal_rag_search",
    toolset="portal",
    schema=RAG_SEARCH_SCHEMA,
    handler=_handle_rag_search,
    check_fn=_check_portal_available,
    emoji="\U0001f50d",
)


DECK_SCHEMA = {
    "name": "portal_deck_publish",
    "description": (
        "Publish a completed research deck to the portal so the user gets a "
        "downloadable link. Pass the FULL self-contained HTML document as the "
        "``html`` argument — inline the CSS and JS, embed the data as JSON. "
        "No external resources except Chart.js from CDN. Returns a stable "
        "download URL the user can open or save.\n\n"
        "Use this on the portal (no local write_file): compose the whole HTML "
        "deck in one string and pass it here. This is free (deck storage is "
        "not billed)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "html": {
                "type": "string",
                "description": (
                    "The complete self-contained HTML deck as a single string: "
                    "doctype, <html>, <head> with inline <style>, <body> with "
                    "all sections, charts, claims and references. Inline all "
                    "CSS/JS and JSON data."
                ),
            },
            "filename": {
                "type": "string",
                "description": "Deck filename, e.g. 'legal-analysis-deck.html'.",
            },
            "run_id": {
                "type": "string",
                "description": "The research run id, if one was recorded.",
            },
            "question": {
                "type": "string",
                "description": "The research question the deck answers.",
            },
            "mode": {
                "type": "string",
                "description": "The research mode (investigation/discovery/…).",
            },
        },
        "required": ["html"],
    },
}


def _handle_deck_publish(args, **kw):
    logger.debug("Entered into _handle_deck_publish: args_keys=%s", list(args.keys()))
    html = (args.get("html") or "").strip()
    if not html:
        return tool_error("html is required — pass the full self-contained HTML deck")

    filename = (args.get("filename") or "research-deck.html").strip()
    run_id = (args.get("run_id") or "").strip() or None
    question = (args.get("question") or "").strip() or None
    mode = (args.get("mode") or "").strip() or None

    gateway_token = os.environ.get("GATEWAY_INTERNAL_TOKEN") or os.environ.get("HOSTED_GATEWAY_SHARED_SECRET")
    if not gateway_token:
        return tool_error("No gateway token configured — cannot publish deck to portal")

    user_id = None
    try:
        from gateway.session_context import get_session_env
        user_id = get_session_env("ELIDIA_SESSION_USER_ID", "")
    except ImportError:
        pass

    import httpx

    try:
        with httpx.Client(timeout=30.0) as client:
            headers = {
                "Content-Type": "application/json",
                "X-Gateway-Token": gateway_token,
            }
            if user_id:
                headers["X-Portal-User-Id"] = str(user_id)

            resp = client.post(
                f"{PORTAL_BACKEND_URL}/agent-v2/v1/deck",
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
        logger.warning("Portal deck publish failed: %s", exc)
        return tool_error(f"Deck publish failed: {exc}")

    url = data.get("url") or ""
    return json.dumps({
        "id": data.get("id"),
        "url": url,
        "download_url": url,
        "filename": data.get("filename", filename),
        "size_bytes": data.get("size_bytes"),
        "message": (
            f"Deck published. Download link: {url}"
            if url else
            "Deck published, but no URL was returned."
        ),
    }, ensure_ascii=False, default=str)


registry.register(
    name="portal_deck_publish",
    toolset="portal",
    schema=DECK_SCHEMA,
    handler=_handle_deck_publish,
    check_fn=_check_portal_available,
    emoji="\U0001f4c4",
)
