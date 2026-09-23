"""Runnable entry point for the hosted multi-tenant gateway.

Composes the Portal OAuth router, the in-process WorkerPool, and the shared
APIServerAdapter into one aiohttp service that nginx can front as ``/agent-v2``.
A single process; per-tenant isolation is via ContextVars (no subprocesses).

Run::

    python -m gateway.hosted

Configuration (environment only — no secrets in code):

* ``HOSTED_GATEWAY_JWKS_URL``    (conditionally required) Portal OAuth JWKS URL
* ``HOSTED_GATEWAY_AUDIENCE``    (conditionally required) expected JWT ``aud`` claim
* ``HOSTED_GATEWAY_ISSUER``      (optional) expected JWT ``iss`` (empty = skip)
* ``HOSTED_GATEWAY_SCOPE``       (optional) required scope (default ``agent_dashboard:access``)
* ``HOSTED_GATEWAY_SHARED_SECRET`` (alternative to JWKS) static Bearer token for
  portal-internal auth. When set, JWT is skipped and the user id is read from
  the ``X-Portal-User-Id`` header. Use ONLY for localhost deployments.
* ``HOSTED_GATEWAY_HOST``        (optional) bind host (default ``127.0.0.1``)
* ``HOSTED_GATEWAY_PORT``        (optional) bind port (default ``47000``)
* ``HOSTED_GATEWAY_MAX_WORKERS`` (optional) ThreadPoolExecutor size (default ``8``)
* ``API_SERVER_MODEL_NAME``      (optional) model name passed to the api_server
* ``API_SERVER_CORS_ORIGINS``    (optional) CORS origins for the api_server
* ``HOSTED_GATEWAY_PROVISION_URL``  (optional) internal provision endpoint; enables
  per-tenant aiutils key provisioning (developer-wallet billing, plan §6.4)
* ``PROVISION_INTERNAL_TOKEN``      (optional) the ``X-Provision-Token`` secret for
  that endpoint; must be set iff ``HOSTED_GATEWAY_PROVISION_URL`` is set
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Mapping, Optional

from aiohttp import web

from gateway.config import PlatformConfig
from gateway.hosted.provisioning import KeyProvisioner, ProvisionerConfig
from gateway.hosted.router import JwtConfig, TenantResolver
from gateway.hosted.server import create_gateway_app
from gateway.hosted.worker_pool import WorkerPool, WorkerPoolConfig
from gateway.platforms.api_server import APIServerAdapter

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47000
DEFAULT_SCOPE = "agent_dashboard:access"
DEFAULT_MAX_WORKERS = 8


@dataclass
class HostedGatewayConfig:
    """Resolved runtime configuration for the hosted gateway."""

    jwks_url: str
    audience: str
    issuer: str = ""
    scope: str = DEFAULT_SCOPE
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    max_workers: int = DEFAULT_MAX_WORKERS
    model_name: str = ""
    cors_origins: str = ""
    provision_url: str = ""
    provision_token: str = ""
    shared_secret: str = ""


class ConfigError(ValueError):
    """Raised when required hosted-gateway configuration is missing/invalid."""


def _int_field(env: Mapping[str, str], name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def load_config(env: Optional[Mapping[str, str]] = None) -> HostedGatewayConfig:
    """Build a ``HostedGatewayConfig`` from environment variables."""
    env = os.environ if env is None else env

    shared_secret = (env.get("HOSTED_GATEWAY_SHARED_SECRET") or "").strip()

    if not shared_secret:
        missing = [
            name
            for name in ("HOSTED_GATEWAY_JWKS_URL", "HOSTED_GATEWAY_AUDIENCE")
            if not (env.get(name) or "").strip()
        ]
        if missing:
            raise ConfigError(
                "missing required hosted-gateway config: " + ", ".join(missing)
                + " (or set HOSTED_GATEWAY_SHARED_SECRET for portal-internal auth)"
            )

    provision_url = (env.get("HOSTED_GATEWAY_PROVISION_URL") or "").strip()
    provision_token = (env.get("PROVISION_INTERNAL_TOKEN") or "").strip()
    if bool(provision_url) != bool(provision_token):
        raise ConfigError(
            "HOSTED_GATEWAY_PROVISION_URL and PROVISION_INTERNAL_TOKEN must be "
            "set together (or both unset)"
        )

    scope = (env.get("HOSTED_GATEWAY_SCOPE") or DEFAULT_SCOPE).strip() or DEFAULT_SCOPE
    host = (env.get("HOSTED_GATEWAY_HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST

    return HostedGatewayConfig(
        jwks_url=(env.get("HOSTED_GATEWAY_JWKS_URL") or "").strip(),
        audience=(env.get("HOSTED_GATEWAY_AUDIENCE") or "").strip(),
        issuer=(env.get("HOSTED_GATEWAY_ISSUER") or "").strip(),
        scope=scope,
        host=host,
        port=_int_field(env, "HOSTED_GATEWAY_PORT", DEFAULT_PORT),
        max_workers=_int_field(env, "HOSTED_GATEWAY_MAX_WORKERS", DEFAULT_MAX_WORKERS),
        model_name=(env.get("API_SERVER_MODEL_NAME") or "").strip(),
        cors_origins=(env.get("API_SERVER_CORS_ORIGINS") or "").strip(),
        provision_url=provision_url,
        provision_token=provision_token,
        shared_secret=shared_secret,
    )


def build_app(config: HostedGatewayConfig) -> web.Application:
    """Build the hosted gateway aiohttp application from resolved config."""
    logger.debug("Entered into build_app")

    provisioner = KeyProvisioner(
        ProvisionerConfig(
            provision_url=config.provision_url,
            provision_token=config.provision_token,
        )
    )

    pool = WorkerPool(
        WorkerPoolConfig(
            max_workers=config.max_workers,
            provisioner=provisioner,
        )
    )

    resolver = None
    if config.jwks_url and config.audience and not config.shared_secret:
        resolver = TenantResolver(
            JwtConfig(
                jwks_url=config.jwks_url,
                audience=config.audience,
                issuer=config.issuer,
                required_scope=config.scope,
            )
        )
        logger.info("Auth mode: JWT (JWKS=%s)", config.jwks_url)
    elif config.shared_secret:
        logger.info("Auth mode: shared-secret (portal-internal, localhost only)")
    else:
        raise ConfigError(
            "No auth configured: set HOSTED_GATEWAY_JWKS_URL + AUDIENCE "
            "or HOSTED_GATEWAY_SHARED_SECRET"
        )

    api_config = PlatformConfig(
        enabled=True,
        extra={
            "model_name": config.model_name,
            "cors_origins": config.cors_origins,
        },
    )
    api_server = APIServerAdapter(api_config, gateway_trusted=True)

    return create_gateway_app(
        pool, resolver, api_server, shared_secret=config.shared_secret,
    )


def main() -> int:
    """Resolve config, build the app, run until interrupted.

    Returns the process exit code (2 on configuration error) so systemd can
    distinguish a bad config from a successful run.
    """
    try:
        config = load_config()
    except ConfigError as exc:
        logger.error("hosted gateway config error: %s", exc)
        print(f"hosted gateway: {exc}", file=sys.stderr)
        return 2

    app = build_app(config)

    # MCP tool discovery. The hosted gateway never did this — only the CLI
    # gateway (gateway/run.py) and the interactive CLI did — so configuring
    # `mcp_servers` in config.yaml had no effect on the web portal and its
    # users simply had no MCP tools (AIUT-3313).
    #
    # Discovery runs in a daemon thread: discover_mcp_tools() blocks for up to
    # 120s internally, and a slow or hung MCP server must never stop the
    # gateway from serving. The helper is idempotent, and returns immediately
    # when no servers are configured.
    try:
        from elidia_cli.mcp_startup import start_background_mcp_discovery

        start_background_mcp_discovery(
            logger=logger, thread_name="hosted-mcp-discovery",
        )
    except Exception:
        logger.debug("Background MCP discovery could not start", exc_info=True)

    auth_mode = "shared-secret" if config.shared_secret else f"JWT (jwks={config.jwks_url})"
    logger.info(
        "hosted gateway listening on http://%s:%d (auth=%s, workers=%d)",
        config.host,
        config.port,
        auth_mode,
        config.max_workers,
    )
    web.run_app(app, host=config.host, port=config.port, access_log=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
