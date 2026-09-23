"""In-process multi-tenant worker pool (AIUT-3078 B3).

Replaces ``supervisor.py``'s Popen-per-tenant model with a shared
``ThreadPoolExecutor``. Each tenant request runs in a ``copy_context()``
scope so ContextVar writes (session key, session id, platform vars) are
isolated per-request without OS-process boundaries.

The pool owns:
  * a ``ThreadPoolExecutor`` sized to the expected concurrent-tenant peak,
  * cached per-tenant provisioned API keys (same lifecycle as the old
    supervisor — keys survive across requests but not across restarts),
  * a ``_TENANT_ID_RE`` validator (same rules as the supervisor).

It does NOT:
  * spawn subprocesses,
  * allocate TCP ports,
  * create per-tenant home directories or config files,
  * proxy HTTP.

The ``dispatch`` method is the only public entry point for request
handling — it takes a tenant id and a sync callable, sets up the tenant
ContextVar scope, and runs the callable in the executor. The gateway
(``server.py``) calls ``dispatch`` instead of ``supervisor.acquire`` +
``proxy_to_backend``.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, TypeVar

from gateway.hosted.provisioning import KeyProvisioner

logger = logging.getLogger(__name__)

_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

T = TypeVar("T")

DEFAULT_MAX_WORKERS = 8
DEFAULT_IDLE_TTL = 3600.0


@dataclass
class WorkerPoolConfig:
    """Configuration for the in-process worker pool."""

    max_workers: int = DEFAULT_MAX_WORKERS
    provisioner: Optional[KeyProvisioner] = None
    idle_ttl: float = DEFAULT_IDLE_TTL


@dataclass
class _TenantState:
    """Per-tenant runtime bookkeeping (NOT per-request — per tenant)."""

    tenant_id: str
    active_runs: int = 0
    last_active: float = field(default_factory=time.monotonic)
    provisioned_key: Optional[str] = None


class WorkerPool:
    """In-process multi-tenant worker pool.

    Thread-safe. All mutable state is guarded by ``_lock``.
    """

    def __init__(self, config: WorkerPoolConfig):
        logger.debug("Entered into WorkerPool.__init__: max_workers=%d", config.max_workers)
        self._config = config
        self._executor = ThreadPoolExecutor(
            max_workers=config.max_workers,
            thread_name_prefix="elidia-worker",
        )
        self._lock = threading.Lock()
        self._tenants: Dict[str, _TenantState] = {}
        self._shutting_down = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        tenant_id: str,
        fn: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Run ``fn(*args, **kwargs)`` in a worker thread with tenant context.

        Sets up ContextVars (``ELIDIA_SESSION_KEY``) before calling ``fn``.
        The callable runs inside ``copy_context().run()`` so ContextVar
        writes are isolated per-request.

        Raises ``ValueError`` for an unsafe tenant id, ``RuntimeError`` if
        the pool is shutting down.
        """
        logger.debug("Entered into WorkerPool.dispatch: tenant=%s fn=%s", tenant_id, fn.__name__)
        self._validate_tenant_id(tenant_id)
        if self._shutting_down:
            raise RuntimeError("worker pool is shutting down")

        state = self._touch(tenant_id)
        ctx = contextvars.copy_context()
        loop = asyncio.get_running_loop()

        def _run() -> T:
            from gateway.session_context import set_session_vars

            set_session_vars(session_key=tenant_id)
            with self._run_guard(state):
                return fn(*args, **kwargs)

        return await loop.run_in_executor(self._executor, ctx.run, _run)

    def provision_key(self, tenant_id: str) -> Optional[str]:
        """Return the cached or freshly-provisioned aiutils key for a tenant.

        Returns ``None`` when no provisioner is configured.
        """
        logger.debug("Entered into WorkerPool.provision_key: tenant=%s", tenant_id)
        self._validate_tenant_id(tenant_id)
        provisioner = self._config.provisioner
        if provisioner is None or not provisioner.enabled:
            return None
        with self._lock:
            state = self._tenants.get(tenant_id)
            if state is not None and state.provisioned_key is not None:
                return state.provisioned_key
        key = provisioner.provision(tenant_id)
        with self._lock:
            state = self._ensure_tenant(tenant_id)
            state.provisioned_key = key
        return key

    def health(self) -> Dict[str, Any]:
        """Return pool health metrics."""
        with self._lock:
            active = sum(s.active_runs for s in self._tenants.values())
            tenants_active = sum(
                1 for s in self._tenants.values() if s.active_runs > 0
            )
            return {
                "pool_size": self._config.max_workers,
                "active_runs": active,
                "tenants_tracked": len(self._tenants),
                "tenants_active": tenants_active,
                "shutting_down": self._shutting_down,
            }

    def reap_idle(self) -> list[str]:
        """Forget tenants idle longer than ``idle_ttl``; return their ids.

        Only affects bookkeeping — no processes to kill. Provisioned keys
        are discarded (re-provisioned on next request).
        """
        now = time.monotonic()
        reaped: list[str] = []
        with self._lock:
            for tenant_id in list(self._tenants):
                state = self._tenants[tenant_id]
                if (
                    state.active_runs == 0
                    and now - state.last_active >= self._config.idle_ttl
                ):
                    del self._tenants[tenant_id]
                    reaped.append(tenant_id)
        if reaped:
            logger.info("worker pool: reaped idle tenants: %s", reaped)
        return reaped

    def shutdown(self) -> None:
        """Shut down the executor. Idempotent."""
        logger.debug("Entered into WorkerPool.shutdown")
        self._shutting_down = True
        self._executor.shutdown(wait=True)
        with self._lock:
            self._tenants.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        if not isinstance(tenant_id, str) or not _TENANT_ID_RE.match(tenant_id):
            raise ValueError(f"unsafe tenant id: {tenant_id!r}")

    def _touch(self, tenant_id: str) -> _TenantState:
        """Ensure tenant state exists and refresh its idle timer."""
        with self._lock:
            state = self._ensure_tenant(tenant_id)
            state.last_active = time.monotonic()
            return state

    def _ensure_tenant(self, tenant_id: str) -> _TenantState:
        """Return (or create) the _TenantState for ``tenant_id``. Caller holds _lock."""
        state = self._tenants.get(tenant_id)
        if state is None:
            state = _TenantState(tenant_id=tenant_id)
            self._tenants[tenant_id] = state
        return state

    class _run_guard:
        """Context manager that increments/decrements active_runs."""

        def __init__(self, state: _TenantState):
            self._state = state

        def __enter__(self):
            self._state.active_runs += 1
            return self

        def __exit__(self, *exc):
            self._state.active_runs = max(0, self._state.active_runs - 1)
            return False
