"""HTTP/SSE reverse proxy to per-tenant backends.

Given an authenticated request whose tenant has already been resolved (by the
router), forward it to that tenant's backend and stream the response back.
Streaming is preserved so SSE endpoints (``chat/stream``, ``runs/.../events``)
work without buffering the whole run.
"""

from __future__ import annotations

from typing import Optional

from aiohttp import ClientSession, web

# Hop-by-hop headers that must not be forwarded verbatim (RFC 7230 §6.1).
# ``host`` is rebuilt by aiohttp from the target URL; ``content-length`` is
# recomputed by the library from the body we send.
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _forward_headers(headers: object) -> dict:
    """Return request headers safe to forward to the upstream backend."""
    result = {}
    for name, value in headers.items():
        if name.lower() in _HOP_BY_HOP:
            continue
        result[name] = value
    return result


def _response_headers(resp) -> dict:
    """Return response headers safe to relay to the client."""
    result = {}
    for name, value in resp.headers.items():
        if name.lower() in _HOP_BY_HOP:
            continue
        result[name] = value
    return result


async def proxy_to_backend(
    request: web.Request,
    base_url: str,
    session: Optional[ClientSession] = None,
) -> web.StreamResponse:
    """Forward ``request`` to ``base_url`` and stream the response back.

    ``base_url`` is the tenant backend origin (e.g. ``http://127.0.0.1:48001``);
    the incoming path + query string are appended verbatim.
    """
    target_url = base_url.rstrip("/") + request.path_qs
    headers = _forward_headers(request.headers)
    body = await request.read()

    own_session = session is None
    if own_session:
        session = ClientSession()

    try:
        async with session.request(
            request.method, target_url, headers=headers, data=body
        ) as upstream:
            response = web.StreamResponse(
                status=upstream.status,
                headers=_response_headers(upstream),
            )
            await response.prepare(request)
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
            await response.write_eof()
            return response
    finally:
        if own_session:
            await session.close()
