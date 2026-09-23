"""Hosted multi-tenant gateway (process-per-tenant).

Spawns one ``api_server.py`` subprocess per portal user with an isolated
``ELIDIA_HOME`` and per-tenant ``API_SERVER_KEY``, so the single-user agent
core ships unchanged while each tenant gets OS-level isolation.
"""

from gateway.hosted.proxy import proxy_to_backend
from gateway.hosted.router import JwtConfig, JwtError, TenantResolver
from gateway.hosted.server import HostedGateway, create_gateway_app
from gateway.hosted.supervisor import (
    Supervisor,
    SupervisorConfig,
    TenantBackend,
)

__all__ = [
    "Supervisor",
    "SupervisorConfig",
    "TenantBackend",
    "proxy_to_backend",
    "JwtConfig",
    "JwtError",
    "TenantResolver",
    "HostedGateway",
    "create_gateway_app",
]
