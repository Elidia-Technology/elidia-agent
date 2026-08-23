#!/usr/bin/env python3
"""
Hand a user off to an interactive AiUtils portal tool (B9).

Not every portal tool can be driven headlessly. The Developer API divides them
into two execution modes:

* ``call`` — the agent collects parameters, invokes the endpoint, shows the
  result. This is what ``aiutils_tool_execute`` does.
* ``redirect`` — a studio or editor built around a human at a canvas: layers,
  timelines, drag-and-drop, live preview. ``image-editor``, ``video-studio``,
  ``music-studio``, ``logo-designer`` and ~30 others. There is no headless
  equivalent to run.

Before this module, ``aiutils_tool_execute`` treated both the same: it checked
the wallet and POSTed to ``/v1/tools/<slug>/execute`` for a studio that cannot
produce a result that way. The user got an opaque failure for a tool they own
and could have opened in a browser in one click.

So a redirect tool now short-circuits into a link — and the check runs *before*
the spend guard, because reading a balance for work that cannot happen is a
round trip spent to reach the same refusal.

**Channel-aware** means the link is rendered for wherever the answer is going.
A terminal, a Telegram thread, and an API client each need a different shape,
and the agent knows which it is from ``run_context.platform``.

The URL itself comes from the server whenever the catalog supplies a
``handoff_url``. Constructing ``/tools/<slug>`` here as well is a fallback for
older gateways, not the primary path — a route pattern duplicated into every
client is one redesign away from every client being wrong.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Where the portal front end lives. Overridable so a staging build can point at
# staging rather than sending testers to production.
PORTAL_WEB_URL_ENV = "AIUTILS_PORTAL_URL"
DEFAULT_PORTAL_WEB_URL = "https://aiutils.io"

# Verified against the portal front end (frontend/src/routes.tsx defines
# "/tools/:slug"). Only used when the catalog does not carry handoff_url.
TOOL_PATH_TEMPLATE = "/tools/{slug}"

MODE_CALL = "call"
MODE_REDIRECT = "redirect"

# Surfaces where the user is sitting at the machine the agent runs on, so the
# link opens in a browser they already have in front of them.
#
# An allowlist of LOCAL surfaces rather than one of chat platforms, on purpose.
# gateway/platforms/ ships eighteen and grows: bluebubbles, dingtalk, email,
# feishu, homeassistant, matrix, msgraph_webhook, qqbot, signal, slack, sms,
# telegram, wecom, weixin, whatsapp, yuanbao... An enumerated chat list is stale
# the day someone adds the nineteenth, and it fails in the wrong direction —
# a new platform would silently get terminal wording. This set changes almost
# never, and anything not in it is treated as remote, which is the safe default.
_LOCAL_PLATFORMS = frozenset({"cli", "tui", "desktop", "vscode", "terminal", ""})

# Programmatic callers. They get the link as data, not prose.
_PROGRAMMATIC_PLATFORMS = frozenset({"api_server", "gateway", "curator", "webhook"})

# The catalog is a few hundred KB and changes when tools ship, not per turn.
_CATALOG_TTL_SECONDS = 900
_catalog_cache: dict[str, Any] = {"fetched_at": 0.0, "tools": {}}


def portal_web_url() -> str:
    """Origin of the portal front end, without a trailing slash."""
    return (os.getenv(PORTAL_WEB_URL_ENV) or DEFAULT_PORTAL_WEB_URL).rstrip("/")


def _absolute(url: str) -> str:
    """Make a catalog-supplied path absolute; leave a full URL alone.

    The catalog historically carried a site-relative path (``/tools/x``), which
    is meaningless once it leaves the browser — an agent may be printing it into
    a terminal or a Telegram message, where there is no origin to resolve it
    against.
    """
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return f"{portal_web_url()}/{url.lstrip('/')}"


def tool_url(slug: str, handoff_url: Optional[str] = None) -> str:
    """Absolute URL for a portal tool page."""
    if handoff_url:
        return _absolute(handoff_url)
    return f"{portal_web_url()}{TOOL_PATH_TEMPLATE.format(slug=slug)}"


def _iter_catalog_tools(payload: Any):
    """Yield tool dicts from a ``/v1/tools/genres`` response.

    Shape: ``{"genres": {<key>: {"tools": [...]}}}``. Tolerant of the parts it
    does not recognise so a catalog gaining a field cannot break a handoff.
    """
    genres = (payload or {}).get("genres") if isinstance(payload, dict) else None
    if not isinstance(genres, dict):
        return
    for genre in genres.values():
        if not isinstance(genre, dict):
            continue
        for tool in genre.get("tools") or []:
            if isinstance(tool, dict) and tool.get("slug"):
                yield tool


def load_catalog(client=None, *, force: bool = False) -> dict[str, dict]:
    """Slug → tool metadata, cached.

    Returns ``{}`` when the catalog cannot be fetched. A caller must treat that
    as "unknown", never as "this tool is a call tool" — guessing wrong sends a
    studio through headless execution, which is the failure this module exists
    to prevent.
    """
    logger.debug("Entered into load_catalog: force=%s", force)
    fresh = (time.time() - _catalog_cache["fetched_at"]) < _CATALOG_TTL_SECONDS
    if _catalog_cache["tools"] and fresh and not force:
        return _catalog_cache["tools"]

    try:
        from tools import aiutils_client

        client = client or aiutils_client.get_client()
        payload = client.tools.genres()
    except Exception as exc:
        logger.warning("Could not load the AiUtils tool catalog: %s", exc)
        return _catalog_cache["tools"] if _catalog_cache["tools"] else {}

    tools = {t["slug"]: t for t in _iter_catalog_tools(payload)}
    if tools:
        _catalog_cache["tools"] = tools
        _catalog_cache["fetched_at"] = time.time()
    return tools


def lookup(slug: str, client=None) -> Optional[dict]:
    """Catalog entry for *slug*, or None when unknown or unavailable."""
    return load_catalog(client=client).get((slug or "").strip())


def is_redirect_tool(slug: str, client=None) -> bool:
    """True only when the catalog says this tool needs a human at a UI.

    False for a call tool *and* for an unknown one: an unreachable catalog must
    not start blocking execution of tools that were working.
    """
    entry = lookup(slug, client=client)
    return bool(entry) and entry.get("execution_mode") == MODE_REDIRECT


def _current_platform() -> str:
    try:
        from tools import run_context

        ctx = run_context.get_run_context()
        return (getattr(ctx, "platform", None) or "").strip().lower()
    except Exception:
        return ""


def format_handoff(
    slug: str,
    *,
    name: Optional[str] = None,
    url: Optional[str] = None,
    description: Optional[str] = None,
    platform: Optional[str] = None,
) -> str:
    """Render the handoff for the surface this answer is going to.

    Plain URLs throughout, deliberately. OSC 8 terminal hyperlinks would need
    capability detection this codebase does not have, and a terminal that lacks
    it prints the escape sequence as visible noise; every modern terminal
    linkifies a bare URL anyway. Chat clients and API consumers cannot use the
    escapes at all.
    """
    label = name or slug
    link = url or tool_url(slug)
    channel = (platform or _current_platform() or "cli").lower()

    if channel in _PROGRAMMATIC_PLATFORMS:
        # One line, trivially parseable, no decoration for a machine to strip.
        return f"OPEN_TOOL {slug} {link}"

    detail = f" — {description.strip()}" if description else ""
    if channel in _LOCAL_PLATFORMS:
        return (
            f"{label} is an interactive editor — it needs the canvas, so I "
            f"cannot run it headlessly.\n\n  Open it here: {link}\n{detail}"
        ).rstrip()

    # Remote surface: the user is reading this on another device, so say the
    # link opens somewhere rather than implying it is already in front of them.
    return (
        f"{label} is an interactive studio, so it opens in your browser rather "
        f"than running here:\n{link}{detail}"
    )


def handoff_payload(slug: str, client=None, platform: Optional[str] = None) -> dict:
    """Everything a caller needs to hand the user off to *slug*.

    Includes the raw ``url`` alongside the rendered ``message`` so a GUI variant
    (desktop, VS Code, mobile) can attach it to a button instead of printing it.
    """
    logger.debug("Entered into handoff_payload: slug=%s", slug)
    entry = lookup(slug, client=client) or {}
    url = tool_url(slug, entry.get("handoff_url"))
    return {
        "action": "open_url",
        "tool_slug": slug,
        "name": entry.get("name") or slug,
        "url": url,
        "execution_mode": entry.get("execution_mode") or MODE_REDIRECT,
        "output_type": entry.get("output_type"),
        "message": format_handoff(
            slug,
            name=entry.get("name"),
            url=url,
            description=entry.get("description"),
            platform=platform,
        ),
    }
