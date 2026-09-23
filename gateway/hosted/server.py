"""Compose the hosted gateway: JWT router + WorkerPool + in-process api_server.

This is the HTTP entry point for ``/agent-v2``.  Each request is:
1. verified (Portal OAuth JWT → tenant id) by the router middleware,
2. dispatched with tenant ContextVars set by the middleware,
3. handled in-process by the shared ``APIServerAdapter`` (gateway_trusted=True).

The WorkerPool replaces the old Supervisor (process-per-tenant) and proxy.
Handlers run in the shared event loop; sync agent work inside them uses
``asyncio.to_thread`` which copies ContextVars into the worker thread.

AIUT-3078 Phase B5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from aiohttp import web

from gateway.hosted.router import JwtError, TenantResolver
from gateway.hosted.worker_pool import WorkerPool
from gateway.platforms.api_server import APIServerAdapter
from gateway.session_context import set_session_vars, clear_session_vars

logger = logging.getLogger(__name__)


def _build_tenant_middleware(resolver: Optional[TenantResolver], shared_secret: str = ""):
    """Build an aiohttp middleware that authenticates requests and sets tenant ContextVars.

    Supports two authentication modes:

    1. **JWT mode** (``resolver`` is set): verifies the Bearer token against the
       Portal OAuth JWKS and extracts the tenant id from the JWT claims.

    2. **Shared-secret mode** (``shared_secret`` is set, ``resolver`` is None):
       accepts a static Bearer token matching ``HOSTED_GATEWAY_SHARED_SECRET``.
       The portal has already authenticated the user via its own JWT; the shared
       secret proves the request came from the portal. The user id is read from
       the ``X-Portal-User-Id`` header, injected by the portal proxy.
       This mode is for localhost-only deployments where the gateway is fronted
       by the portal and never exposed to the internet.

    Non-authenticated routes (health checks) are passed through without
    any verification — the ``APIServerAdapter`` handles them with its
    ``gateway_trusted`` flag (``_check_auth`` returns ``None``).
    """

    _PUBLIC_PREFIXES = ("/health",)

    @web.middleware
    async def tenant_middleware(request: web.Request, handler):
        logger.debug("Entered into tenant_middleware: %s %s", request.method, request.path)

        if any(request.path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await handler(request)

        auth_header = request.headers.get("Authorization", "")

        if shared_secret and not resolver:
            token = ""
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1].strip()
            if not token or token != shared_secret:
                return web.json_response(
                    {"error": {"message": "invalid shared secret", "type": "unauthorized"}},
                    status=401,
                )
            tenant_id = request.headers.get("X-Portal-User-Id", "portal")
        elif resolver:
            try:
                tenant_id = resolver.resolve(auth_header)
            except JwtError as exc:
                return web.json_response(
                    {"error": {"message": str(exc), "type": "unauthorized"}},
                    status=401,
                )
        else:
            return web.json_response(
                {"error": {"message": "no authentication configured", "type": "server_error"}},
                status=500,
            )

        tokens = set_session_vars(session_key=tenant_id, user_id=tenant_id)
        try:
            return await handler(request)
        finally:
            clear_session_vars(tokens)

    return tenant_middleware


class HostedGateway:
    """AIOHTTP application tying JWT router → WorkerPool → APIServerAdapter."""

    def __init__(
        self,
        pool: WorkerPool,
        resolver: TenantResolver,
        api_server: APIServerAdapter,
    ):
        logger.debug("Entered into HostedGateway.__init__")
        self._pool = pool
        self._resolver = resolver
        self._api_server = api_server

    async def on_startup(self, app: web.Application) -> None:
        """Start background tasks after the event loop is running."""
        await self._api_server.start_background_tasks()

    async def on_cleanup(self, app: web.Application) -> None:
        """Shut down the worker pool on app teardown."""
        self._pool.shutdown()


def create_gateway_app(
    pool: WorkerPool,
    resolver: Optional[TenantResolver],
    api_server: APIServerAdapter,
    shared_secret: str = "",
) -> web.Application:
    """Build the hosted gateway aiohttp application.

    The app uses:
    - a tenant middleware (JWT or shared-secret) that authenticates requests,
    - the api_server's route handlers registered directly on the app,
    - the WorkerPool available via ``app["worker_pool"]`` for health probes.
    """
    logger.debug("Entered into create_gateway_app")
    gateway = HostedGateway(pool, resolver, api_server)

    tenant_mw = _build_tenant_middleware(resolver, shared_secret=shared_secret)
    app = web.Application(middlewares=[tenant_mw])

    api_server.register_routes(app)

    app["worker_pool"] = pool
    app["gateway"] = gateway
    app.on_startup.append(gateway.on_startup)
    app.on_cleanup.append(gateway.on_cleanup)
    return app
