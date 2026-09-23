"""Session-store factory for the Elidia Agent v2 pooled runtime (AIUT-3078).

Resolves the store backend from configuration and returns the right
``SessionStore`` implementation:

- **SQLite** (default / CLI) — returns ``elidia_state.SessionDB``
- **Postgres** (pooled-worker path) — returns ``PostgresSessionStore``
  sharing a process-wide ``ConnectionPool`` singleton

Backend resolution order:
  1. Explicit ``backend`` parameter.
  2. ``ELIDIA_STORE_BACKEND`` environment variable (``"sqlite"`` / ``"postgres"``).
  3. Default: ``StoreBackend.SQLITE``.

For Postgres, the DSN is resolved:
  1. Explicit ``dsn`` parameter.
  2. ``ELIDIA_POSTGRES_DSN`` environment variable.
  3. Raises ``RuntimeError``.

Portal mode:
  When ``ELIDIA_POSTGRES_SCHEMA`` is set (e.g. ``"elidia_gw"``), every
  connection's ``search_path`` is configured so unqualified table names
  (``sessions``, ``messages``, …) resolve inside that schema. This lets
  the gateway share the portal's Postgres database without table-name
  collisions.  The portal Alembic migration ``gw_002`` creates the
  ``elidia_gw`` schema with the gateway's exact table definitions.

Thread-safety: ``create_session_store`` returns a new store instance per
call. In Postgres mode, every instance shares the same ``ConnectionPool``
but holds its own ``_scope_user_id``, so concurrent threads each operate
on their own tenant without interference.
"""

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from store.base import StoreBackend

if TYPE_CHECKING:
    from store.base import SessionStore

logger = logging.getLogger(__name__)

_pg_pool_lock = threading.Lock()
_pg_pool = None  # psycopg_pool.ConnectionPool | None


def _resolve_backend(backend: StoreBackend | None = None) -> StoreBackend:
    """Resolve the store backend from arg → env → default."""
    if backend is not None:
        return backend
    env = os.environ.get("ELIDIA_STORE_BACKEND", "").strip().lower()
    if env == "postgres":
        return StoreBackend.POSTGRES
    return StoreBackend.SQLITE


def _resolve_pg_dsn(dsn: str | None = None) -> str:
    """Resolve the Postgres DSN from arg → env."""
    if dsn:
        return dsn
    dsn = os.environ.get("ELIDIA_POSTGRES_DSN", "").strip()
    if dsn:
        return dsn
    raise RuntimeError(
        "Postgres store requires a DSN: pass dsn= or set ELIDIA_POSTGRES_DSN"
    )


def _resolve_pg_schema(schema: str | None = None) -> str | None:
    """Resolve the Postgres schema from arg → env → None (no override)."""
    if schema is not None:
        return schema or None
    env = os.environ.get("ELIDIA_POSTGRES_SCHEMA", "").strip()
    return env or None


def _get_pg_pool(
    dsn: str,
    min_size: int = 2,
    max_size: int = 10,
    schema: str | None = None,
) -> "ConnectionPool":
    """Return the process-wide Postgres connection pool, creating it on first call.

    When *schema* is set (e.g. ``"elidia_gw"``), every connection borrrowed
    from the pool has its ``search_path`` set to ``<schema>, public`` so
    unqualified table names resolve inside that schema first.
    """
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pg_pool_lock:
        if _pg_pool is not None:
            return _pg_pool
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        configure_fn = None
        if schema:
            safe_schema = schema.replace('"', '""')

            def configure_fn(conn):
                conn.execute(
                    f'SET search_path TO "{safe_schema}", public'
                )

        logger.debug(
            "Entered into _get_pg_pool: creating shared pool "
            "(min_size=%d, max_size=%d, schema=%s)",
            min_size, max_size, schema or "<default>",
        )
        _pg_pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            configure=configure_fn,
            open=True,
        )
        return _pg_pool


def create_session_store(
    *,
    backend: StoreBackend | None = None,
    user_id: str | None = None,
    db_path: Path | None = None,
    dsn: str | None = None,
    schema: str | None = None,
    pg_min_size: int = 2,
    pg_max_size: int = 10,
) -> "SessionStore":
    """Create a ``SessionStore`` for the resolved backend.

    Parameters
    ----------
    backend
        Explicit backend override. Falls back to ``ELIDIA_STORE_BACKEND``
        env var, then ``StoreBackend.SQLITE``.
    user_id
        Tenant scope. Passed to the underlying store's constructor so every
        accessor filters by this user_id.
    db_path
        SQLite only: path to the ``state.db`` file. ``None`` = default.
    dsn
        Postgres only: connection URI. Falls back to ``ELIDIA_POSTGRES_DSN``.
    schema
        Postgres only: schema name (e.g. ``"elidia_gw"``). Falls back to
        ``ELIDIA_POSTGRES_SCHEMA``. When set, the pool's ``search_path``
        is configured so unqualified table names resolve in that schema.
    pg_min_size
        Postgres only: minimum pool connections (shared singleton).
    pg_max_size
        Postgres only: maximum pool connections (shared singleton).

    Returns
    -------
    SessionStore
        A fully initialized store instance.
    """
    resolved = _resolve_backend(backend)
    logger.debug(
        "Entered into create_session_store: backend=%s, user_id=%s",
        resolved.value, user_id,
    )

    if resolved == StoreBackend.POSTGRES:
        from store.postgres import PostgresSessionStore

        pg_dsn = _resolve_pg_dsn(dsn)
        pg_schema = _resolve_pg_schema(schema)
        pool = _get_pg_pool(
            pg_dsn,
            min_size=pg_min_size,
            max_size=pg_max_size,
            schema=pg_schema,
        )
        return PostgresSessionStore(pool=pool, user_id=user_id)

    from elidia_state import SessionDB
    return SessionDB(db_path=db_path, user_id=user_id)


def close_shared_pool() -> None:
    """Shut down the shared Postgres pool, if one was created.

    Call once at process shutdown (e.g. in an ``atexit`` hook or ``finally``
    block). Safe to call multiple times or when no pool was ever created.
    """
    global _pg_pool
    with _pg_pool_lock:
        if _pg_pool is not None:
            logger.debug("Entered into close_shared_pool: closing")
            _pg_pool.close()
            _pg_pool = None


def _reset_for_tests() -> None:
    """Reset module state between test runs. NOT for production use."""
    global _pg_pool
    with _pg_pool_lock:
        if _pg_pool is not None:
            try:
                _pg_pool.close()
            except Exception:
                pass
            _pg_pool = None
