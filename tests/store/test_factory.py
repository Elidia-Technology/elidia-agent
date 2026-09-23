"""Tests for the store factory (AIUT-3078 A3).

Verifies backend resolution, pool sharing, tenant scoping, and the
close/reset lifecycle. Postgres tests require a local
``elidia_agent_v2_test`` DB and are skipped when unreachable.
"""

import os

import pytest

from store.base import StoreBackend
from store.factory import (
    _resolve_backend,
    _resolve_pg_dsn,
    _reset_for_tests,
    close_shared_pool,
    create_session_store,
)
from tests.store.conftest import _PG_DSN, _pg_ok, postgres


# ═══════════════════════════════════════════════════════════════════════════
# Backend resolution
# ═══════════════════════════════════════════════════════════════════════════

class TestResolveBackend:

    def test_explicit_postgres(self):
        assert _resolve_backend(StoreBackend.POSTGRES) == StoreBackend.POSTGRES

    def test_explicit_sqlite(self):
        assert _resolve_backend(StoreBackend.SQLITE) == StoreBackend.SQLITE

    def test_default_is_sqlite(self, monkeypatch):
        monkeypatch.delenv("ELIDIA_STORE_BACKEND", raising=False)
        assert _resolve_backend() == StoreBackend.SQLITE

    def test_env_postgres(self, monkeypatch):
        monkeypatch.setenv("ELIDIA_STORE_BACKEND", "postgres")
        assert _resolve_backend() == StoreBackend.POSTGRES

    def test_env_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ELIDIA_STORE_BACKEND", "  POSTGRES  ")
        assert _resolve_backend() == StoreBackend.POSTGRES

    def test_env_unknown_falls_back_to_sqlite(self, monkeypatch):
        monkeypatch.setenv("ELIDIA_STORE_BACKEND", "redis")
        assert _resolve_backend() == StoreBackend.SQLITE


# ═══════════════════════════════════════════════════════════════════════════
# DSN resolution
# ═══════════════════════════════════════════════════════════════════════════

class TestResolvePgDsn:

    def test_explicit_dsn(self):
        assert _resolve_pg_dsn("postgresql://x") == "postgresql://x"

    def test_env_dsn(self, monkeypatch):
        monkeypatch.setenv("ELIDIA_POSTGRES_DSN", "postgresql://env")
        assert _resolve_pg_dsn() == "postgresql://env"

    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("ELIDIA_POSTGRES_DSN", raising=False)
        with pytest.raises(RuntimeError, match="DSN"):
            _resolve_pg_dsn()


# ═══════════════════════════════════════════════════════════════════════════
# SQLite factory path
# ═══════════════════════════════════════════════════════════════════════════

class TestFactorySqlite:

    def test_default_returns_sessiondb(self, monkeypatch):
        monkeypatch.delenv("ELIDIA_STORE_BACKEND", raising=False)
        store = create_session_store()
        try:
            from elidia_state import SessionDB
            assert isinstance(store, SessionDB)
        finally:
            store.close()

    def test_explicit_sqlite_with_custom_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ELIDIA_STORE_BACKEND", raising=False)
        db_path = tmp_path / "custom.db"
        store = create_session_store(backend=StoreBackend.SQLITE, db_path=db_path)
        try:
            from elidia_state import SessionDB
            assert isinstance(store, SessionDB)
            assert store.db_path == db_path
        finally:
            store.close()

    def test_sqlite_with_user_id(self, monkeypatch):
        monkeypatch.delenv("ELIDIA_STORE_BACKEND", raising=False)
        store = create_session_store(user_id="tenant-1")
        try:
            assert store._scope_user_id == "tenant-1"
        finally:
            store.close()


# ═══════════════════════════════════════════════════════════════════════════
# Postgres factory path
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestFactoryPostgres:

    def setup_method(self):
        _reset_for_tests()

    def teardown_method(self):
        _reset_for_tests()

    def test_returns_postgres_store(self):
        from store.postgres import PostgresSessionStore
        store = create_session_store(
            backend=StoreBackend.POSTGRES, dsn=_PG_DSN, user_id="A",
        )
        assert isinstance(store, PostgresSessionStore)
        assert store._scope_user_id == "A"

    def test_shared_pool_singleton(self):
        s1 = create_session_store(
            backend=StoreBackend.POSTGRES, dsn=_PG_DSN, user_id="A",
        )
        s2 = create_session_store(
            backend=StoreBackend.POSTGRES, dsn=_PG_DSN, user_id="B",
        )
        assert s1._pool is s2._pool
        assert not s1._owns_pool
        assert not s2._owns_pool

    def test_tenant_isolation_through_factory(self):
        import psycopg
        with psycopg.connect(_PG_DSN, autocommit=True) as conn:
            conn.execute(
                "TRUNCATE TABLE messages, sessions, compression_locks, state_meta CASCADE"
            )

        s_a = create_session_store(
            backend=StoreBackend.POSTGRES, dsn=_PG_DSN, user_id="A",
        )
        s_b = create_session_store(
            backend=StoreBackend.POSTGRES, dsn=_PG_DSN, user_id="B",
        )

        s_a.create_session("sa", source="cli")
        s_b.create_session("sb", source="cli")

        assert s_a.get_session("sa") is not None
        assert s_a.get_session("sb") is None
        assert s_b.get_session("sb") is not None
        assert s_b.get_session("sa") is None
        assert s_a.session_count() == 1
        assert s_b.session_count() == 1

    def test_close_shared_does_not_kill_pool(self):
        s1 = create_session_store(
            backend=StoreBackend.POSTGRES, dsn=_PG_DSN, user_id="X",
        )
        s1.close()
        s2 = create_session_store(
            backend=StoreBackend.POSTGRES, dsn=_PG_DSN, user_id="Y",
        )
        s2.create_session("alive", source="cli")
        assert s2.get_session("alive") is not None

    def test_close_shared_pool_shuts_down(self):
        create_session_store(
            backend=StoreBackend.POSTGRES, dsn=_PG_DSN,
        )
        close_shared_pool()
        from store.factory import _pg_pool
        assert _pg_pool is None

    def test_env_resolved_postgres(self, monkeypatch):
        from store.postgres import PostgresSessionStore
        monkeypatch.setenv("ELIDIA_STORE_BACKEND", "postgres")
        monkeypatch.setenv("ELIDIA_POSTGRES_DSN", _PG_DSN)
        store = create_session_store(user_id="env-test")
        assert isinstance(store, PostgresSessionStore)
        assert store._scope_user_id == "env-test"
