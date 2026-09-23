"""Process-per-tenant supervisor for the hosted Elidia gateway.

The hosted gateway is single-tenant in its current form: ``api_server.py``
authenticates with one shared ``API_SERVER_KEY`` and keeps all state under a
single ``ELIDIA_HOME``. This supervisor adds multi-tenancy **outside** that
process by spawning one backend process per portal user, each with:

  * its own ``ELIDIA_HOME`` (workspace, ``state.db``, memory, cron, MCP, creds),
  * a freshly-generated per-tenant ``API_SERVER_KEY``,
  * a dedicated TCP port,
  * a generated ``config.yaml`` that enables only the ``api_server`` platform.

Isolation is OS-level (separate process + separate home directory), so the
single-user agent core ships unchanged. The supervisor's job is lifecycle:
spawn on first request, health-check, and reap idle backends.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from gateway.hosted.provisioning import KeyProvisioner

logger = logging.getLogger(__name__)

# Repository root (three levels above gateway/hosted/supervisor.py), used to
# resolve the default backend command without relying on the caller's CWD.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Tenant ids are portal ``sub`` claims. Restrict to a safe charset and length
# so a crafted id cannot traverse the filesystem or pollute the environment.
_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT_RANGE = (48000, 49000)
DEFAULT_HEALTH_TIMEOUT = 30.0
DEFAULT_HEALTH_INTERVAL = 0.2
DEFAULT_IDLE_TTL = 3600.0  # reap a backend after 1h without activity
_SPAWN_ATTEMPTS = 3


@dataclass
class TenantBackend:
    """A running per-tenant backend process and its isolation parameters."""

    tenant_id: str
    port: int
    api_key: str
    home: Path
    process: subprocess.Popen
    started_at: float
    last_active: float


@dataclass
class SupervisorConfig:
    """Configuration for the per-tenant supervisor."""

    tenants_dir: Path
    host: str = DEFAULT_HOST
    port_range: tuple = DEFAULT_PORT_RANGE
    model_name: str = ""
    backend_cmd: Optional[List[str]] = None
    health_timeout: float = DEFAULT_HEALTH_TIMEOUT
    health_interval: float = DEFAULT_HEALTH_INTERVAL
    idle_ttl: float = DEFAULT_IDLE_TTL
    provisioner: Optional[KeyProvisioner] = None


class Supervisor:
    """Manage a pool of per-tenant ``api_server.py`` backend processes."""

    def __init__(self, config: SupervisorConfig):
        self._config = config
        self._tenants_dir = Path(config.tenants_dir)
        self._lock = threading.Lock()
        self._backends: Dict[str, TenantBackend] = {}
        self._used_ports: set[int] = set()
        # Provisioned aiutils keys, cached server-side per tenant so a backend
        # respawn does not mint a fresh credential (the key can never be read
        # back from the portal, so the supervisor holds it for the process's
        # lifetime; a supervisor restart re-provisions).
        self._tenant_keys: Dict[str, str] = {}
        self._tenants_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self, tenant_id: str) -> TenantBackend:
        """Return the running backend for ``tenant_id``, spawning it if needed.

        Thread-safe. Refreshes ``last_active`` on each call. Raises
        ``ValueError`` for an unsafe tenant id, and ``RuntimeError`` if the
        backend cannot be started within ``_SPAWN_ATTEMPTS`` tries.
        """
        self._validate_tenant_id(tenant_id)
        with self._lock:
            existing = self._backends.get(tenant_id)
            if existing is not None and self._is_alive(existing):
                existing.last_active = time.monotonic()
                return existing
            # Stale process (dead or port freed) — drop it before respawn.
            if existing is not None:
                self._backends.pop(tenant_id, None)
                self._used_ports.discard(existing.port)
            backend = self._spawn(tenant_id)
            self._backends[tenant_id] = backend
            return backend

    def get(self, tenant_id: str) -> Optional[TenantBackend]:
        """Return the backend for ``tenant_id`` without spawning, if alive."""
        with self._lock:
            backend = self._backends.get(tenant_id)
            if backend is not None and self._is_alive(backend):
                return backend
            return None

    def touch(self, tenant_id: str) -> None:
        """Refresh the idle timer for an existing backend."""
        with self._lock:
            backend = self._backends.get(tenant_id)
            if backend is not None:
                backend.last_active = time.monotonic()

    def release(self, tenant_id: str) -> None:
        """Terminate and forget the backend for ``tenant_id`` (if any)."""
        with self._lock:
            backend = self._backends.pop(tenant_id, None)
            if backend is None:
                return
            self._used_ports.discard(backend.port)
        self._terminate(backend)

    def reap_idle(self) -> List[str]:
        """Terminate backends idle longer than ``idle_ttl``; return their ids.

        The tenant's home directory is kept on disk for session continuity;
        only the process is stopped.
        """
        now = time.monotonic()
        to_terminate: List[TenantBackend] = []
        with self._lock:
            for tenant_id, backend in list(self._backends.items()):
                if now - backend.last_active >= self._config.idle_ttl:
                    self._backends.pop(tenant_id, None)
                    self._used_ports.discard(backend.port)
                    to_terminate.append(backend)
        for backend in to_terminate:
            self._terminate(backend)
        return [b.tenant_id for b in to_terminate]

    def shutdown(self) -> None:
        """Terminate all backends. Idempotent."""
        with self._lock:
            backends = list(self._backends.values())
            self._backends.clear()
            self._used_ports.clear()
        for backend in backends:
            self._terminate(backend)

    def tenant_home(self, tenant_id: str) -> Path:
        """Return the (dedicated) home directory for ``tenant_id``."""
        self._validate_tenant_id(tenant_id)
        return self._tenants_dir / tenant_id

    def backend_origin(self, backend: TenantBackend) -> str:
        """Return the origin URL for a running backend."""
        return f"http://{self._config.host}:{backend.port}"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        if not isinstance(tenant_id, str) or not _TENANT_ID_RE.match(tenant_id):
            raise ValueError(f"unsafe tenant id: {tenant_id!r}")

    def _spawn(self, tenant_id: str) -> TenantBackend:
        # Provision the aiutils key once per spawn, before the retry loop — a
        # provision failure is a configuration/trust error, not a transient
        # process-start failure, so it is not retried (and surfaces as 503 via
        # server.py's RuntimeError handling).
        aiutils_key = self._provision_key(tenant_id)
        last_error: Optional[Exception] = None
        for attempt in range(1, _SPAWN_ATTEMPTS + 1):
            port = self._allocate_port()
            api_key = secrets.token_urlsafe(32)
            home = self._tenants_dir / tenant_id
            home.mkdir(parents=True, exist_ok=True)
            self._write_tenant_config(home)
            env = self._build_env(tenant_id, home, port, api_key, aiutils_key)
            try:
                process = subprocess.Popen(
                    self._backend_command(),
                    env=env,
                    cwd=str(_REPO_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:  # e.g. interpreter/backend not found
                self._used_ports.discard(port)
                last_error = exc
                continue

            backend = TenantBackend(
                tenant_id=tenant_id,
                port=port,
                api_key=api_key,
                home=home,
                process=process,
                started_at=time.monotonic(),
                last_active=time.monotonic(),
            )
            if self._wait_healthy(backend):
                logger.info(
                    "hosted: tenant %r backend up on http://%s:%d",
                    tenant_id, self._config.host, port,
                )
                return backend

            logger.warning(
                "hosted: tenant %r backend on port %d failed health check "
                "(attempt %d); terminating",
                tenant_id, port, attempt,
            )
            self._terminate(backend)
            self._used_ports.discard(port)
            last_error = RuntimeError(f"backend did not become healthy on port {port}")
        raise RuntimeError(
            f"failed to start backend for tenant {tenant_id!r} after "
            f"{_SPAWN_ATTEMPTS} attempts"
        ) from last_error

    def _backend_command(self) -> List[str]:
        if self._config.backend_cmd is not None:
            return list(self._config.backend_cmd)
        return [sys.executable, str(_REPO_ROOT / "cli.py"), "--gateway"]

    def _build_env(
        self,
        tenant_id: str,
        home: Path,
        port: int,
        api_key: str,
        aiutils_key: Optional[str] = None,
    ) -> Dict[str, str]:
        env = os.environ.copy()
        env["ELIDIA_HOME"] = str(home)
        env["ELIDIA_PROFILE"] = "hosted"
        env["API_SERVER_KEY"] = api_key
        env["API_SERVER_HOST"] = self._config.host
        env["API_SERVER_PORT"] = str(port)
        if self._config.model_name:
            env["API_SERVER_MODEL_NAME"] = self._config.model_name
        if aiutils_key:
            # The provisioned per-tenant key must win over any inherited
            # single-user key, so drop the provider's higher-priority legacy
            # names (ELIDIA_KEY/ELIDIA_API_KEY) before setting AIUTILS_API_KEY.
            env["AIUTILS_API_KEY"] = aiutils_key
            env.pop("ELIDIA_KEY", None)
            env.pop("ELIDIA_API_KEY", None)
        return env

    def _provision_key(self, tenant_id: str) -> Optional[str]:
        """Return the cached or freshly-provisioned aiutils key for a tenant.

        Returns ``None`` when no provisioner is configured (degraded,
        non-billing bring-up). Raises :class:`ProvisionError` if the provisioner
        is enabled but the portal refuses to mint a key.
        """
        provisioner = self._config.provisioner
        if provisioner is None or not provisioner.enabled:
            return None
        cached = self._tenant_keys.get(tenant_id)
        if cached is not None:
            return cached
        key = provisioner.provision(tenant_id)
        self._tenant_keys[tenant_id] = key
        return key

    def _write_tenant_config(self, home: Path) -> None:
        """Write a minimal config.yaml enabling only the api_server platform.

        All messaging platforms default to ``enabled: false``, so enabling
        only ``api_server`` keeps the backend free of Telegram/WhatsApp/etc.
        """
        import yaml  # local import: repo already depends on PyYAML

        config_path = home / "config.yaml"
        payload = {
            "platforms": {
                "api_server": {"enabled": True},
            },
        }
        config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def _allocate_port(self) -> int:
        """Return a free port from the configured range (best effort)."""
        start, end = self._config.port_range
        for port in range(start, end + 1):
            if port in self._used_ports:
                continue
            if self._port_is_free(port):
                self._used_ports.add(port)
                return port
        raise RuntimeError(
            f"no free port in range {start}-{end} for hosted tenants"
        )

    @staticmethod
    def _port_is_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
            return True

    def _health_url(self, backend: TenantBackend) -> str:
        return f"http://{self._config.host}:{backend.port}/health"

    def _wait_healthy(self, backend: TenantBackend) -> bool:
        deadline = time.monotonic() + self._config.health_timeout
        url = self._health_url(backend)
        while time.monotonic() < deadline:
            if backend.process.poll() is not None:
                return False  # exited before becoming healthy
            if self._probe_health(url):
                return True
            time.sleep(self._config.health_interval)
        return False

    @staticmethod
    def _probe_health(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def _is_alive(self, backend: TenantBackend) -> bool:
        if backend.process.poll() is not None:
            return False
        return self._probe_health(self._health_url(backend))

    @staticmethod
    def _terminate(backend: TenantBackend) -> None:
        process = backend.process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        except OSError:
            pass
