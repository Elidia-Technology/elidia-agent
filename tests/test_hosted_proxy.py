"""Tests for the per-tenant HTTP/SSE proxy.

Runs an in-process aiohttp backend and proves the proxy forwards method,
path, body, and headers, and streams an SSE response end-to-end. (Process
isolation is the supervisor's concern and is covered separately.)
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.hosted.proxy import proxy_to_backend


def _build_backend() -> web.Application:
    async def health(request: web.Request) -> web.Response:
        return web.json_response(
            {"ok": True, "from": "backend", "path": request.path},
            headers={"X-Backend-Marker": "present"},
        )

    async def stream(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        await resp.write(b"event: tick\ndata: 1\n\n")
        await resp.write(b"event: tick\ndata: 2\n\n")
        await resp.write_eof()
        return resp

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/stream", stream)
    return app


def _build_proxy(backend_base: str) -> web.Application:
    async def handler(request: web.Request) -> web.StreamResponse:
        return await proxy_to_backend(request, backend_base)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    return app


async def _start(app: web.Application) -> TestClient:
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_proxy_forwards_status_body_and_headers():
    backend = await _start(_build_backend())
    proxy = await _start(_build_proxy(str(backend.make_url("/"))))
    try:
        resp = await proxy.get("/health")
        assert resp.status == 200
        body = await resp.json()
        assert body["from"] == "backend"
        assert body["path"] == "/health"
        assert resp.headers["X-Backend-Marker"] == "present"
    finally:
        await proxy.close()
        await backend.close()


@pytest.mark.asyncio
async def test_proxy_streams_sse_end_to_end():
    backend = await _start(_build_backend())
    proxy = await _start(_build_proxy(str(backend.make_url("/"))))
    try:
        resp = await proxy.get("/stream")
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "text/event-stream"
        text = await resp.text()
        assert "event: tick" in text
        assert "data: 1" in text
        assert "data: 2" in text
    finally:
        await proxy.close()
        await backend.close()


@pytest.mark.asyncio
async def test_proxy_preserves_method_and_body():
    async def echo(request: web.Request) -> web.Response:
        return web.json_response(
            {"method": request.method, "body": (await request.text())}
        )

    backend_app = web.Application()
    backend_app.router.add_post("/echo", echo)
    backend = await _start(backend_app)
    proxy = await _start(_build_proxy(str(backend.make_url("/"))))
    try:
        resp = await proxy.post("/echo", json={"hello": "world"})
        body = await resp.json()
        assert body["method"] == "POST"
        assert "hello" in body["body"]
    finally:
        await proxy.close()
        await backend.close()
