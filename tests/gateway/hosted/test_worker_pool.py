"""Tests for the in-process multi-tenant worker pool (AIUT-3078 B3)."""

import asyncio
import threading
import time

import pytest

from gateway.hosted.worker_pool import WorkerPool, WorkerPoolConfig


# ═══════════════════════════════════════════════════════════════════════
# Tenant ID validation
# ═══════════════════════════════════════════════════════════════════════


class TestTenantValidation:

    def test_valid_tenant_id(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        pool._validate_tenant_id("user_123")
        pool._validate_tenant_id("abc-def.ghi")
        pool._validate_tenant_id("A" * 128)
        pool.shutdown()

    def test_empty_tenant_id(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        with pytest.raises(ValueError, match="unsafe"):
            pool._validate_tenant_id("")
        pool.shutdown()

    def test_too_long_tenant_id(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        with pytest.raises(ValueError, match="unsafe"):
            pool._validate_tenant_id("A" * 129)
        pool.shutdown()

    def test_unsafe_chars(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        for bad in ["../etc", "user;rm", "tenant id", "a/b"]:
            with pytest.raises(ValueError, match="unsafe"):
                pool._validate_tenant_id(bad)
        pool.shutdown()


# ═══════════════════════════════════════════════════════════════════════
# Dispatch
# ═══════════════════════════════════════════════════════════════════════


class TestDispatch:

    @pytest.mark.asyncio
    async def test_dispatch_runs_callable(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=2))
        try:
            result = await pool.dispatch("tenant-a", lambda: 42)
            assert result == 42
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_dispatch_passes_args(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=2))
        try:
            result = await pool.dispatch("tenant-a", lambda x, y: x + y, 3, 7)
            assert result == 10
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_dispatch_sets_session_key_contextvar(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=2))
        try:
            def _check_context():
                from gateway.session_context import get_session_env
                return get_session_env("ELIDIA_SESSION_KEY")

            result = await pool.dispatch("tenant-xyz", _check_context)
            assert result == "tenant-xyz"
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_dispatch_isolates_tenants(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=4))
        try:
            captured = {}
            barrier = threading.Barrier(2, timeout=5)

            def _capture(tenant_id):
                from gateway.session_context import get_session_env
                barrier.wait()
                captured[tenant_id] = get_session_env("ELIDIA_SESSION_KEY")
                return tenant_id

            results = await asyncio.gather(
                pool.dispatch("tenant-A", _capture, "tenant-A"),
                pool.dispatch("tenant-B", _capture, "tenant-B"),
            )
            assert set(results) == {"tenant-A", "tenant-B"}
            assert captured["tenant-A"] == "tenant-A"
            assert captured["tenant-B"] == "tenant-B"
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_dispatch_propagates_exception(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        try:
            with pytest.raises(ZeroDivisionError):
                await pool.dispatch("t", lambda: 1 / 0)
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_dispatch_rejects_after_shutdown(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        pool.shutdown()
        with pytest.raises(RuntimeError, match="shutting down"):
            await pool.dispatch("t", lambda: 1)


# ═══════════════════════════════════════════════════════════════════════
# Health + bookkeeping
# ═══════════════════════════════════════════════════════════════════════


class TestHealth:

    @pytest.mark.asyncio
    async def test_health_reports_pool_size(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=4))
        try:
            h = pool.health()
            assert h["pool_size"] == 4
            assert h["active_runs"] == 0
            assert h["tenants_tracked"] == 0
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_health_tracks_active_runs(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=2))
        try:
            started = threading.Event()
            release = threading.Event()

            def _block():
                started.set()
                release.wait(timeout=5)

            task = asyncio.ensure_future(pool.dispatch("t1", _block))
            await asyncio.get_running_loop().run_in_executor(None, started.wait, 2)
            await asyncio.sleep(0.05)

            h = pool.health()
            assert h["active_runs"] == 1
            assert h["tenants_active"] == 1

            release.set()
            await task

            h2 = pool.health()
            assert h2["active_runs"] == 0
        finally:
            pool.shutdown()


class TestReapIdle:

    @pytest.mark.asyncio
    async def test_reap_idle_removes_stale_tenants(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1, idle_ttl=0.01))
        try:
            await pool.dispatch("old-tenant", lambda: None)
            await asyncio.sleep(0.05)
            reaped = pool.reap_idle()
            assert "old-tenant" in reaped
            assert pool.health()["tenants_tracked"] == 0
        finally:
            pool.shutdown()

    @pytest.mark.asyncio
    async def test_reap_idle_keeps_active_tenants(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=2, idle_ttl=10))
        try:
            await pool.dispatch("active-tenant", lambda: None)
            reaped = pool.reap_idle()
            assert reaped == []
            assert pool.health()["tenants_tracked"] == 1
        finally:
            pool.shutdown()


# ═══════════════════════════════════════════════════════════════════════
# Provisioning
# ═══════════════════════════════════════════════════════════════════════


class TestProvisionKey:

    def test_no_provisioner_returns_none(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=1))
        assert pool.provision_key("t") is None
        pool.shutdown()

    def test_provisioner_caches_key(self):
        from unittest.mock import MagicMock
        from gateway.hosted.provisioning import KeyProvisioner, ProvisionerConfig

        mock_prov = MagicMock(spec=KeyProvisioner)
        mock_prov.enabled = True
        mock_prov.provision.return_value = "key-for-t"

        pool = WorkerPool(WorkerPoolConfig(max_workers=1, provisioner=mock_prov))
        try:
            k1 = pool.provision_key("t")
            k2 = pool.provision_key("t")
            assert k1 == "key-for-t"
            assert k2 == "key-for-t"
            mock_prov.provision.assert_called_once_with("t")
        finally:
            pool.shutdown()
