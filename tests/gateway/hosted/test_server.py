"""Tests for the hosted gateway server wiring (AIUT-3078 B5).

Verifies: JWT middleware tenant isolation, route registration,
health endpoint passthrough, and gateway app composition.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from gateway.hosted.router import JwtError, TenantResolver
from gateway.hosted.server import HostedGateway, create_gateway_app, _build_tenant_middleware
from gateway.hosted.worker_pool import WorkerPool, WorkerPoolConfig


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════


def _mock_resolver(tenant_map=None, fail_with=None):
    """Build a mock TenantResolver.

    ``tenant_map``: dict of auth_header → tenant_id
    ``fail_with``: raise this JwtError for any unmatched header
    """
    resolver = MagicMock(spec=TenantResolver)

    def _resolve(auth_header):
        if fail_with is not None and (tenant_map is None or auth_header not in tenant_map):
            raise fail_with
        if tenant_map and auth_header in tenant_map:
            return tenant_map[auth_header]
        raise JwtError("no matching token")

    resolver.resolve = _resolve
    return resolver


def _make_api_server(gateway_trusted=True):
    """Build a real APIServerAdapter in gateway_trusted mode."""
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    config = PlatformConfig(enabled=True, extra={"model_name": "test-model"})
    return APIServerAdapter(config, gateway_trusted=gateway_trusted)


# ═══════════════════════════════════════════════════════════════════════
# Tenant middleware
# ═══════════════════════════════════════════════════════════════════════


class TestTenantMiddleware:

    @pytest.mark.asyncio
    async def test_public_path_skips_jwt(self):
        """Health endpoints must not require JWT."""
        resolver = _mock_resolver(fail_with=JwtError("should not be called"))
        mw = _build_tenant_middleware(resolver)

        handler_called = False

        async def handler(request):
            nonlocal handler_called
            handler_called = True
            return web.Response(text="ok")

        app = web.Application(middlewares=[mw])
        app.router.add_get("/health", handler)

        from aiohttp.test_utils import TestServer, TestClient

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            assert handler_called

    @pytest.mark.asyncio
    async def test_missing_jwt_returns_401(self):
        resolver = _mock_resolver(fail_with=JwtError("token required"))
        mw = _build_tenant_middleware(resolver)

        async def handler(request):
            return web.Response(text="should not reach")

        app = web.Application(middlewares=[mw])
        app.router.add_get("/v1/models", handler)

        from aiohttp.test_utils import TestServer, TestClient

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/v1/models")
            assert resp.status == 401
            body = await resp.json()
            assert body["error"]["type"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_valid_jwt_sets_context_vars(self):
        """Middleware should set ELIDIA_SESSION_KEY ContextVar to tenant_id."""
        resolver = _mock_resolver(tenant_map={"Bearer good-token": "tenant-42"})
        mw = _build_tenant_middleware(resolver)

        captured_key = None

        async def handler(request):
            nonlocal captured_key
            from gateway.session_context import get_session_env
            captured_key = get_session_env("ELIDIA_SESSION_KEY")
            return web.Response(text="ok")

        app = web.Application(middlewares=[mw])
        app.router.add_get("/v1/models", handler)

        from aiohttp.test_utils import TestServer, TestClient

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/v1/models", headers={"Authorization": "Bearer good-token"})
            assert resp.status == 200
            assert captured_key == "tenant-42"

    @pytest.mark.asyncio
    async def test_context_vars_cleared_after_handler(self):
        """ContextVars should be cleared after the request handler returns."""
        resolver = _mock_resolver(tenant_map={"Bearer tok": "tenant-99"})
        mw = _build_tenant_middleware(resolver)

        async def handler(request):
            return web.Response(text="ok")

        app = web.Application(middlewares=[mw])
        app.router.add_get("/test", handler)

        from aiohttp.test_utils import TestServer, TestClient

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/test", headers={"Authorization": "Bearer tok"})
            assert resp.status == 200

        from gateway.session_context import get_session_env
        val = get_session_env("ELIDIA_SESSION_KEY")
        assert val in ("", None) or val != "tenant-99"


# ═══════════════════════════════════════════════════════════════════════
# Gateway app composition
# ═══════════════════════════════════════════════════════════════════════


class TestCreateGatewayApp:

    def test_app_has_worker_pool(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        resolver = _mock_resolver()
        api_server = _make_api_server()
        try:
            app = create_gateway_app(pool, resolver, api_server)
            assert app["worker_pool"] is pool
        finally:
            pool.shutdown()

    def test_app_has_gateway(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        resolver = _mock_resolver()
        api_server = _make_api_server()
        try:
            app = create_gateway_app(pool, resolver, api_server)
            assert isinstance(app["gateway"], HostedGateway)
        finally:
            pool.shutdown()

    def test_routes_registered(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        resolver = _mock_resolver()
        api_server = _make_api_server()
        try:
            app = create_gateway_app(pool, resolver, api_server)
            route_paths = {r.resource.canonical for r in app.router.routes() if hasattr(r, 'resource') and r.resource}
            assert "/health" in route_paths
            assert "/v1/models" in route_paths
            assert "/v1/chat/completions" in route_paths
            assert "/api/sessions" in route_paths
        finally:
            pool.shutdown()

    def test_api_server_adapter_stored_on_app(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        resolver = _mock_resolver()
        api_server = _make_api_server()
        try:
            app = create_gateway_app(pool, resolver, api_server)
            assert app["api_server_adapter"] is api_server
        finally:
            pool.shutdown()


# ═══════════════════════════════════════════════════════════════════════
# Integration: health endpoint works without JWT
# ═══════════════════════════════════════════════════════════════════════


class TestHealthEndpoint:

    @pytest.mark.asyncio
    async def test_health_no_jwt_required(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        resolver = _mock_resolver(fail_with=JwtError("should not fire"))
        api_server = _make_api_server()
        try:
            app = create_gateway_app(pool, resolver, api_server)
            from aiohttp.test_utils import TestServer, TestClient

            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/health")
                assert resp.status == 200
                body = await resp.json()
                assert body.get("status") == "ok"
        finally:
            pool.shutdown()
