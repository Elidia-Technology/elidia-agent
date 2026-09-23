"""Postgres-backed session store for the Elidia Agent v2 pooled runtime.

Faithful port of ``elidia_state.SessionDB`` (SQLite) to Postgres via
psycopg3 + ``psycopg_pool.ConnectionPool``. Runs entirely in worker threads
(``run_in_executor``) — never on the async event loop.

Design notes vs. the SQLite implementation:

- No WAL / journal-mode handling, no FTS5 probing, no declarative column
  reconciliation — the Postgres schema is already Alembic-migrated
  (``store/migrations``) and is the single source of truth.
- No jitter-retry write wrapper — Postgres MVCC + the connection pool
  handle write contention; each write runs in one ``conn.transaction()``.
- Full-text search uses the ``search_vector`` generated ``tsvector`` column
  (GIN-indexed) via ``plainto_tsquery`` / ``ts_rank`` / ``ts_headline`` for
  the main path, and the ``pg_trgm``-accelerated concatenation (same GIN
  index) via ``LIKE`` for CJK / substring queries — collapsing SQLite's
  three-way FTS5 / trigram-FTS5 / LIKE split into two paths.
- Tenant scoping (``set_scope`` / ``_scope_clause`` / ``_session_owned_by_scope``
  / ``_messages_scope_clause``) is copied verbatim in spirit, with ``?``
  placeholders swapped for ``%s``.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from store.base import (
    StoreBackend,
    sanitize_title,
    MAX_TITLE_LENGTH,
)

logger = logging.getLogger(__name__)

try:
    from agent.memory_manager import sanitize_context as _sanitize_context
except ImportError:  # pragma: no cover - degraded / test environments
    _sanitize_context = None


class PostgresSessionStore:
    """Postgres-backed implementation of the ``SessionStore`` protocol.

    One instance owns one ``ConnectionPool``. Safe to share across worker
    threads within a process; every accessor borrows a connection from the
    pool for the duration of the call and returns it immediately after.
    """

    backend = StoreBackend.POSTGRES
    MAX_TITLE_LENGTH = MAX_TITLE_LENGTH

    # FTS5 virtual tables don't exist in Postgres — search is always backed
    # by the generated ``search_vector`` column + GIN index, so it's never
    # "unavailable" the way SQLite FTS5 can be on an old runtime.
    _fts_enabled = True

    # Indexes merged/rebuilt by optimize_fts().
    _FTS_INDEXES = ("idx_messages_search_vector", "idx_messages_trigram")

    def __init__(
        self,
        conninfo: str | None = None,
        *,
        pool: ConnectionPool | None = None,
        min_size: int = 2,
        max_size: int = 10,
        user_id: str | None = None,
    ):
        logger.debug(
            "Entered into PostgresSessionStore.__init__: "
            "pool=%s, min_size=%d, max_size=%d, scoped=%s",
            "shared" if pool is not None else "new",
            min_size, max_size, "yes" if user_id else "no",
        )
        if pool is not None:
            self._pool = pool
            self._owns_pool = False
        elif conninfo is not None:
            self._pool = ConnectionPool(
                conninfo,
                min_size=min_size,
                max_size=max_size,
                kwargs={"row_factory": dict_row},
                open=True,
            )
            self._owns_pool = True
        else:
            raise ValueError(
                "PostgresSessionStore requires either conninfo or pool"
            )
        # Tenant scope for the pooled runtime (AIUT-3078). When set, core
        # accessors filter ``sessions.user_id``; when None (the default)
        # every statement is unscoped.
        self._scope_user_id = user_id

    # ── Tenant scope (pooled runtime, AIUT-3078) ──

    def set_scope(self, user_id: str | None) -> None:
        """Set the tenant ``user_id`` that scopes every accessor.

        Passing ``None`` clears the filter — every statement reverts to
        unscoped behaviour.
        """
        logger.debug(
            "Entered into PostgresSessionStore.set_scope: %s",
            "<unscoped>" if user_id is None else f"user={user_id!r}",
        )
        self._scope_user_id = user_id

    def _scope_clause(self, alias: str = "sessions") -> Tuple[str, list]:
        """Return ``(where_clause, params)`` filtering by ``_scope_user_id``."""
        if self._scope_user_id is None:
            return "", []
        return f" AND {alias}.user_id = %s", [self._scope_user_id]

    def _session_owned_by_scope(self, conn, session_id: str) -> bool:
        """Return True when unscoped, or when the session belongs to the scope."""
        if self._scope_user_id is None:
            return True
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE id = %s AND user_id = %s LIMIT 1",
            (session_id, self._scope_user_id),
        ).fetchone()
        return row is not None

    def _messages_scope_clause(self) -> Tuple[str, list]:
        """Return ``(clause, params)`` scoping a ``messages`` query by owner."""
        if self._scope_user_id is None:
            return "", []
        return (
            " AND session_id IN (SELECT id FROM sessions WHERE user_id = %s)",
            [self._scope_user_id],
        )

    # ── Core connection helpers ──

    def _execute_write(self, fn):
        """Run *fn(conn)* inside a transaction, returning its result.

        *fn* must not call ``commit()``/``rollback()`` itself — the
        ``conn.transaction()`` context manager commits on success and rolls
        back (re-raising) on any exception raised inside *fn*.
        """
        with self._pool.connection() as conn:
            with conn.transaction():
                return fn(conn)

    def close(self) -> None:
        """Close the underlying connection pool (only if this instance owns it).

        Instances created with ``pool=`` (shared pool from the factory) are
        lightweight views; closing them is a no-op so the pool stays alive
        for other tenants.
        """
        if self._owns_pool:
            logger.debug("Entered into PostgresSessionStore.close: closing owned pool")
            self._pool.close()
        else:
            logger.debug("Entered into PostgresSessionStore.close: shared pool, skipping")

    def _table_exists(self, table_name: str) -> bool:
        """True if *table_name* exists in the current search_path."""
        logger.debug(
            "Entered into PostgresSessionStore._table_exists: table_name=%r",
            table_name,
        )
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT to_regclass(%s) IS NOT NULL AS exists_",
                (table_name,),
            ).fetchone()
        return bool(row and row["exists_"])

    # ── Session lifecycle ──

    def _insert_session_row(
        self,
        session_id: str,
        source: str,
        model: str = None,
        model_config: Dict[str, Any] = None,
        system_prompt: str = None,
        user_id: str = None,
        parent_session_id: str = None,
        cwd: str = None,
    ) -> None:
        """Shared INSERT ... ON CONFLICT DO NOTHING for session rows."""
        logger.debug(
            "Entered into PostgresSessionStore._insert_session_row: "
            "session_id=%r, source=%r",
            session_id, source,
        )
        if user_id is None:
            user_id = self._scope_user_id

        def _do(conn):
            conn.execute(
                """INSERT INTO sessions (id, source, user_id, model, model_config,
                   system_prompt, parent_session_id, cwd, started_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    session_id,
                    source,
                    user_id,
                    model,
                    json.dumps(model_config) if model_config else None,
                    system_prompt,
                    parent_session_id,
                    cwd,
                    time.time(),
                ),
            )

        self._execute_write(_do)

    def create_session(self, session_id: str, source: str, **kwargs) -> str:
        """Create a new session record. Returns the session_id."""
        logger.debug(
            "Entered into PostgresSessionStore.create_session: "
            "session_id=%r, source=%r",
            session_id, source,
        )
        self._insert_session_row(session_id, source, **kwargs)
        return session_id

    def end_session(self, session_id: str, end_reason: str) -> None:
        """Mark a session as ended. First end_reason wins."""
        logger.debug(
            "Entered into PostgresSessionStore.end_session: "
            "session_id=%r, end_reason=%r",
            session_id, end_reason,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            conn.execute(
                "UPDATE sessions SET ended_at = %s, end_reason = %s "
                f"WHERE id = %s AND ended_at IS NULL{scope_clause}",
                (time.time(), end_reason, session_id, *scope_params),
            )

        self._execute_write(_do)

    def reopen_session(self, session_id: str) -> None:
        """Clear ended_at/end_reason so a session can be resumed."""
        logger.debug(
            "Entered into PostgresSessionStore.reopen_session: session_id=%r",
            session_id,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            conn.execute(
                "UPDATE sessions SET ended_at = NULL, end_reason = NULL "
                f"WHERE id = %s{scope_clause}",
                (session_id, *scope_params),
            )

        self._execute_write(_do)

    def update_session_cwd(self, session_id: str, cwd: str) -> None:
        """Persist the session working directory when a frontend knows it."""
        logger.debug(
            "Entered into PostgresSessionStore.update_session_cwd: "
            "session_id=%r",
            session_id,
        )
        if not session_id or not cwd:
            return

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            conn.execute(
                f"UPDATE sessions SET cwd = %s WHERE id = %s{scope_clause}",
                (cwd, session_id, *scope_params),
            )

        self._execute_write(_do)

    # ──────────────────────────────────────────────────────────────────────
    # Compression locks
    # ──────────────────────────────────────────────────────────────────────

    def try_acquire_compression_lock(
        self,
        session_id: str,
        holder: str,
        ttl_seconds: float = 300.0,
    ) -> bool:
        """Try to atomically acquire the compression lock for ``session_id``."""
        logger.debug(
            "Entered into PostgresSessionStore.try_acquire_compression_lock: "
            "session_id=%r, holder=%r",
            session_id, holder,
        )
        if not session_id:
            return False
        now = time.time()
        expires_at = now + ttl_seconds

        def _do(conn):
            if not self._session_owned_by_scope(conn, session_id):
                return False
            conn.execute(
                "DELETE FROM compression_locks "
                "WHERE session_id = %s AND expires_at < %s",
                (session_id, now),
            )
            conn.execute(
                "INSERT INTO compression_locks "
                "(session_id, holder, acquired_at, expires_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (session_id) DO NOTHING",
                (session_id, holder, now, expires_at),
            )
            row = conn.execute(
                "SELECT holder FROM compression_locks WHERE session_id = %s",
                (session_id,),
            ).fetchone()
            return row is not None and row["holder"] == holder

        try:
            return bool(self._execute_write(_do))
        except psycopg.Error as exc:
            logger.warning(
                "try_acquire_compression_lock(%s) failed: %s", session_id, exc,
            )
            return False

    def release_compression_lock(self, session_id: str, holder: str) -> None:
        """Release the compression lock for ``session_id`` iff we own it."""
        logger.debug(
            "Entered into PostgresSessionStore.release_compression_lock: "
            "session_id=%r, holder=%r",
            session_id, holder,
        )
        if not session_id:
            return

        def _do(conn):
            if not self._session_owned_by_scope(conn, session_id):
                return
            conn.execute(
                "DELETE FROM compression_locks "
                "WHERE session_id = %s AND holder = %s",
                (session_id, holder),
            )

        try:
            self._execute_write(_do)
        except psycopg.Error as exc:
            logger.warning(
                "release_compression_lock(%s) failed: %s", session_id, exc,
            )

    def get_compression_lock_holder(self, session_id: str) -> Optional[str]:
        """Return the current (non-expired) holder for ``session_id``, or None."""
        logger.debug(
            "Entered into PostgresSessionStore.get_compression_lock_holder: "
            "session_id=%r",
            session_id,
        )
        if not session_id:
            return None
        with self._pool.connection() as conn:
            if self._scope_user_id is not None:
                owner = conn.execute(
                    "SELECT 1 FROM sessions WHERE id = %s AND user_id = %s LIMIT 1",
                    (session_id, self._scope_user_id),
                ).fetchone()
                if owner is None:
                    return None
            now = time.time()
            row = conn.execute(
                "SELECT holder FROM compression_locks "
                "WHERE session_id = %s AND expires_at >= %s",
                (session_id, now),
            ).fetchone()
        if row is None:
            return None
        return row["holder"]

    def update_system_prompt(self, session_id: str, system_prompt: str) -> None:
        """Store the full assembled system prompt snapshot."""
        logger.debug(
            "Entered into PostgresSessionStore.update_system_prompt: "
            "session_id=%r",
            session_id,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            conn.execute(
                f"UPDATE sessions SET system_prompt = %s WHERE id = %s{scope_clause}",
                (system_prompt, session_id, *scope_params),
            )

        self._execute_write(_do)

    def update_session_model(self, session_id: str, model: str) -> None:
        """Update the model for a session after a mid-session switch."""
        logger.debug(
            "Entered into PostgresSessionStore.update_session_model: "
            "session_id=%r, model=%r",
            session_id, model,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            conn.execute(
                f"UPDATE sessions SET model = %s WHERE id = %s{scope_clause}",
                (model, session_id, *scope_params),
            )

        self._execute_write(_do)

    def update_token_counts(
        self,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = None,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        estimated_cost_usd: Optional[float] = None,
        actual_cost_usd: Optional[float] = None,
        cost_status: Optional[str] = None,
        cost_source: Optional[str] = None,
        pricing_version: Optional[str] = None,
        billing_provider: Optional[str] = None,
        billing_base_url: Optional[str] = None,
        billing_mode: Optional[str] = None,
        api_call_count: int = 0,
        absolute: bool = False,
    ) -> None:
        """Update token counters and backfill model if not already set."""
        logger.debug(
            "Entered into PostgresSessionStore.update_token_counts: "
            "session_id=%r, absolute=%s",
            session_id, absolute,
        )
        # Ensure the session row exists so the UPDATE doesn't silently
        # affect 0 rows.
        self._insert_session_row(session_id, "unknown", model=model)
        if absolute:
            sql = """UPDATE sessions SET
                   input_tokens = %s,
                   output_tokens = %s,
                   cache_read_tokens = %s,
                   cache_write_tokens = %s,
                   reasoning_tokens = %s,
                   estimated_cost_usd = COALESCE(%s, 0),
                   actual_cost_usd = CASE
                       WHEN %s::double precision IS NULL THEN actual_cost_usd
                       ELSE %s
                   END,
                   cost_status = COALESCE(%s, cost_status),
                   cost_source = COALESCE(%s, cost_source),
                   pricing_version = COALESCE(%s, pricing_version),
                   billing_provider = COALESCE(billing_provider, %s),
                   billing_base_url = COALESCE(billing_base_url, %s),
                   billing_mode = COALESCE(billing_mode, %s),
                   model = COALESCE(model, %s),
                   api_call_count = %s
                   WHERE id = %s"""
        else:
            sql = """UPDATE sessions SET
                   input_tokens = input_tokens + %s,
                   output_tokens = output_tokens + %s,
                   cache_read_tokens = cache_read_tokens + %s,
                   cache_write_tokens = cache_write_tokens + %s,
                   reasoning_tokens = reasoning_tokens + %s,
                   estimated_cost_usd = COALESCE(estimated_cost_usd, 0) + COALESCE(%s, 0),
                   actual_cost_usd = CASE
                       WHEN %s::double precision IS NULL THEN actual_cost_usd
                       ELSE COALESCE(actual_cost_usd, 0) + %s
                   END,
                   cost_status = COALESCE(%s, cost_status),
                   cost_source = COALESCE(%s, cost_source),
                   pricing_version = COALESCE(%s, pricing_version),
                   billing_provider = COALESCE(billing_provider, %s),
                   billing_base_url = COALESCE(billing_base_url, %s),
                   billing_mode = COALESCE(billing_mode, %s),
                   model = COALESCE(model, %s),
                   api_call_count = COALESCE(api_call_count, 0) + %s
                   WHERE id = %s"""
        params = (
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_write_tokens,
            reasoning_tokens,
            estimated_cost_usd,
            actual_cost_usd,
            actual_cost_usd,
            cost_status,
            cost_source,
            pricing_version,
            billing_provider,
            billing_base_url,
            billing_mode,
            model,
            api_call_count,
            session_id,
        )
        scope_clause, scope_params = self._scope_clause()
        if scope_clause:
            sql = sql.replace("WHERE id = %s", f"WHERE id = %s{scope_clause}")
            params = (*params, *scope_params)

        def _do(conn):
            conn.execute(sql, params)

        self._execute_write(_do)

    def ensure_session(
        self,
        session_id: str,
        source: str = "unknown",
        model: str = None,
        **kwargs,
    ) -> str:
        """Ensure a session row exists (INSERT ... ON CONFLICT DO NOTHING)."""
        logger.debug(
            "Entered into PostgresSessionStore.ensure_session: "
            "session_id=%r, source=%r",
            session_id, source,
        )
        self._insert_session_row(session_id, source, model=model, **kwargs)
        return session_id

    def prune_empty_ghost_sessions(self, sessions_dir: "Optional[Path]" = None) -> int:
        """Remove empty TUI ghost sessions (no messages, no title, >24hr old)."""
        logger.debug(
            "Entered into PostgresSessionStore.prune_empty_ghost_sessions"
        )
        cutoff = time.time() - 86400

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            rows = conn.execute(
                f"""
                SELECT id FROM sessions
                WHERE source = 'tui'
                  AND title IS NULL
                  AND ended_at IS NOT NULL
                  AND started_at < %s{scope_clause}
                  AND NOT EXISTS (
                      SELECT 1 FROM messages WHERE messages.session_id = sessions.id
                  )
                """,
                (cutoff, *scope_params),
            ).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                conn.execute("DELETE FROM sessions WHERE id = ANY(%s)", (ids,))
            return ids

        removed_ids = self._execute_write(_do) or []
        if sessions_dir and removed_ids:
            for sid in removed_ids:
                self._remove_session_files(sessions_dir, sid)
        return len(removed_ids)

    def finalize_orphaned_compression_sessions(self) -> int:
        """Mark orphaned compression continuation sessions as ended."""
        logger.debug(
            "Entered into PostgresSessionStore.finalize_orphaned_compression_sessions"
        )
        cutoff = time.time() - 604800  # 7 days

        def _do(conn):
            now = time.time()
            scope_clause, scope_params = self._scope_clause()
            result = conn.execute(
                f"""
                UPDATE sessions
                SET ended_at = %s,
                    end_reason = 'orphaned_compression'
                WHERE api_call_count = 0
                  AND end_reason IS NULL
                  AND ended_at IS NULL
                  AND started_at < %s{scope_clause}
                  AND parent_session_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM sessions p
                      WHERE p.id = sessions.parent_session_id
                        AND p.end_reason = 'compression'
                        AND p.ended_at IS NOT NULL
                  )
                  AND EXISTS (
                      SELECT 1 FROM messages m
                      WHERE m.session_id = sessions.id
                  )
                """,
                (now, cutoff, *scope_params),
            )
            return result.rowcount

        return self._execute_write(_do) or 0

    # ── Session reads ──

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a session by ID."""
        logger.debug(
            "Entered into PostgresSessionStore.get_session: session_id=%r",
            session_id,
        )
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT * FROM sessions WHERE id = %s{scope_clause}",
                (session_id, *scope_params),
            ).fetchone()
        return dict(row) if row else None

    def resolve_session_id(self, session_id_or_prefix: str) -> Optional[str]:
        """Resolve an exact or uniquely prefixed session ID to the full ID."""
        logger.debug(
            "Entered into PostgresSessionStore.resolve_session_id: %r",
            session_id_or_prefix,
        )
        exact = self.get_session(session_id_or_prefix)
        if exact:
            return exact["id"]

        escaped = (
            session_id_or_prefix
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            rows = conn.execute(
                f"SELECT id FROM sessions WHERE id LIKE %s ESCAPE '\\'{scope_clause} "
                "ORDER BY started_at DESC LIMIT 2",
                (f"{escaped}%", *scope_params),
            ).fetchall()
        matches = [row["id"] for row in rows]
        if len(matches) == 1:
            return matches[0]
        return None

    @staticmethod
    def sanitize_title(title: Optional[str]) -> Optional[str]:
        """Validate and sanitize a session title. Delegates to store.base."""
        return sanitize_title(title)

    def set_session_title(self, session_id: str, title: str) -> bool:
        """Set or update a session's title. Returns True if found and set."""
        logger.debug(
            "Entered into PostgresSessionStore.set_session_title: "
            "session_id=%r",
            session_id,
        )
        title = self.sanitize_title(title)

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            if title:
                conflict = conn.execute(
                    f"SELECT id FROM sessions WHERE title = %s AND id != %s{scope_clause}",
                    (title, session_id, *scope_params),
                ).fetchone()
                if conflict:
                    raise ValueError(
                        f"Title '{title}' is already in use by session {conflict['id']}"
                    )
            cur = conn.execute(
                f"UPDATE sessions SET title = %s WHERE id = %s{scope_clause}",
                (title, session_id, *scope_params),
            )
            return cur.rowcount

        rowcount = self._execute_write(_do)
        return rowcount > 0

    def get_session_title(self, session_id: str) -> Optional[str]:
        """Get the title for a session, or None."""
        logger.debug(
            "Entered into PostgresSessionStore.get_session_title: "
            "session_id=%r",
            session_id,
        )
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT title FROM sessions WHERE id = %s{scope_clause}",
                (session_id, *scope_params),
            ).fetchone()
        return row["title"] if row else None

    def set_session_archived(self, session_id: str, archived: bool) -> bool:
        """Archive or unarchive a session. Returns True when a row was updated."""
        logger.debug(
            "Entered into PostgresSessionStore.set_session_archived: "
            "session_id=%r, archived=%s",
            session_id, archived,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            cur = conn.execute(
                f"UPDATE sessions SET archived = %s WHERE id = %s{scope_clause}",
                (1 if archived else 0, session_id, *scope_params),
            )
            return cur.rowcount

        rowcount = self._execute_write(_do)
        return rowcount > 0

    def get_session_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        """Look up a session by exact title. Returns session dict or None."""
        logger.debug(
            "Entered into PostgresSessionStore.get_session_by_title: %r",
            title,
        )
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT * FROM sessions WHERE title = %s{scope_clause}",
                (title, *scope_params),
            ).fetchone()
        return dict(row) if row else None

    def resolve_session_by_title(self, title: str) -> Optional[str]:
        """Resolve a title to a session ID, preferring the latest in a lineage."""
        logger.debug(
            "Entered into PostgresSessionStore.resolve_session_by_title: %r",
            title,
        )
        exact = self.get_session_by_title(title)

        escaped = title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            numbered = conn.execute(
                f"SELECT id, title, started_at FROM sessions "
                f"WHERE title LIKE %s ESCAPE '\\'{scope_clause} ORDER BY started_at DESC",
                (f"{escaped} #%", *scope_params),
            ).fetchall()

        if numbered:
            return numbered[0]["id"]
        elif exact:
            return exact["id"]
        return None

    def get_next_title_in_lineage(self, base_title: str) -> str:
        """Generate the next title in a lineage (e.g. 'my session' -> 'my session #2')."""
        logger.debug(
            "Entered into PostgresSessionStore.get_next_title_in_lineage: %r",
            base_title,
        )
        match = re.match(r'^(.*?) #(\d+)$', base_title)
        base = match.group(1) if match else base_title

        escaped = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            rows = conn.execute(
                f"SELECT title FROM sessions WHERE title = %s OR title LIKE %s ESCAPE '\\'{scope_clause}",
                (base, f"{escaped} #%", *scope_params),
            ).fetchall()
        existing = [row["title"] for row in rows]

        if not existing:
            return base

        max_num = 1
        for t in existing:
            m = re.match(r'^.* #(\d+)$', t)
            if m:
                max_num = max(max_num, int(m.group(1)))

        return f"{base} #{max_num + 1}"

    def get_compression_tip(self, session_id: str) -> Optional[str]:
        """Walk the compression-continuation chain forward and return the tip."""
        logger.debug(
            "Entered into PostgresSessionStore.get_compression_tip: "
            "session_id=%r",
            session_id,
        )
        current = session_id
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            for _ in range(100):
                row = conn.execute(
                    f"SELECT id FROM sessions "
                    f"WHERE parent_session_id = %s{scope_clause} "
                    f"  AND started_at >= ("
                    f"      SELECT ended_at FROM sessions "
                    f"      WHERE id = %s AND end_reason = 'compression'{scope_clause}"
                    f"  ) "
                    f"ORDER BY started_at DESC LIMIT 1",
                    (current, *scope_params, current, *scope_params),
                ).fetchone()
                if row is None:
                    return current
                current = row["id"]
        return current

    # ── Session listing / search ──

    def list_sessions_rich(
        self,
        source: str = None,
        exclude_sources: List[str] = None,
        limit: int = 20,
        offset: int = 0,
        include_children: bool = False,
        min_message_count: int = 0,
        project_compression_tips: bool = True,
        order_by_last_active: bool = False,
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List sessions with preview and last-active timestamp."""
        logger.debug(
            "Entered into PostgresSessionStore.list_sessions_rich: "
            "source=%r, limit=%d, offset=%d",
            source, limit, offset,
        )
        where_clauses = []
        params = []

        if not include_children:
            where_clauses.append(
                "(s.parent_session_id IS NULL"
                " OR EXISTS (SELECT 1 FROM sessions p"
                "            WHERE p.id = s.parent_session_id"
                "            AND p.end_reason = 'branched'"
                "            AND s.started_at >= p.ended_at))"
            )

        if source:
            where_clauses.append("s.source = %s")
            params.append(source)
        if exclude_sources:
            where_clauses.append("NOT (s.source = ANY(%s))")
            params.append(exclude_sources)
        if min_message_count > 0:
            where_clauses.append("s.message_count >= %s")
            params.append(min_message_count)
        if archived_only:
            where_clauses.append("s.archived = 1")
        elif not include_archived:
            where_clauses.append("s.archived = 0")

        if self._scope_user_id is not None:
            where_clauses.append("s.user_id = %s")
            params.append(self._scope_user_id)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        if order_by_last_active:
            query = f"""
                WITH RECURSIVE chain(root_id, cur_id) AS (
                    SELECT s.id, s.id FROM sessions s {where_sql}
                    UNION ALL
                    SELECT c.root_id, child.id
                    FROM chain c
                    JOIN sessions parent ON parent.id = c.cur_id
                    JOIN sessions child ON child.parent_session_id = c.cur_id
                    WHERE parent.end_reason = 'compression'
                      AND child.started_at >= parent.ended_at
                ),
                chain_max AS (
                    SELECT
                        root_id,
                        MAX(COALESCE(
                            (SELECT MAX(m.timestamp) FROM messages m WHERE m.session_id = cur_id),
                            (SELECT started_at FROM sessions ss WHERE ss.id = cur_id)
                        )) AS effective_last_active
                    FROM chain
                    GROUP BY root_id
                )
                SELECT s.*,
                    COALESCE(
                        (SELECT SUBSTRING(REPLACE(REPLACE(m.content, chr(10), ' '), chr(13), ' '), 1, 63)
                         FROM messages m
                         WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                         ORDER BY m.timestamp, m.id LIMIT 1),
                        ''
                    ) AS _preview_raw,
                    COALESCE(
                        (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
                        s.started_at
                    ) AS last_active,
                    COALESCE(cm.effective_last_active, s.started_at) AS _effective_last_active
                FROM sessions s
                LEFT JOIN chain_max cm ON cm.root_id = s.id
                {where_sql}
                ORDER BY _effective_last_active DESC, s.started_at DESC, s.id DESC
                LIMIT %s OFFSET %s
            """
            params = params + params + [limit, offset]
        else:
            query = f"""
                SELECT s.*,
                    COALESCE(
                        (SELECT SUBSTRING(REPLACE(REPLACE(m.content, chr(10), ' '), chr(13), ' '), 1, 63)
                         FROM messages m
                         WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                         ORDER BY m.timestamp, m.id LIMIT 1),
                        ''
                    ) AS _preview_raw,
                    COALESCE(
                        (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
                        s.started_at
                    ) AS last_active
                FROM sessions s
                {where_sql}
                ORDER BY s.started_at DESC
                LIMIT %s OFFSET %s
            """
            params = params + [limit, offset]

        with self._pool.connection() as conn:
            rows = conn.execute(query, params).fetchall()

        sessions = []
        for row in rows:
            s = dict(row)
            raw = (s.pop("_preview_raw", "") or "").strip()
            if raw:
                text = raw[:60]
                s["preview"] = text + ("..." if len(raw) > 60 else "")
            else:
                s["preview"] = ""
            s.pop("_effective_last_active", None)
            sessions.append(s)

        if project_compression_tips and not include_children:
            projected = []
            for s in sessions:
                if s.get("end_reason") != "compression":
                    projected.append(s)
                    continue
                tip_id = self.get_compression_tip(s["id"])
                if tip_id == s["id"]:
                    projected.append(s)
                    continue
                tip_row = self._get_session_rich_row(tip_id)
                if not tip_row:
                    projected.append(s)
                    continue
                merged = dict(s)
                for key in (
                    "id", "ended_at", "end_reason", "message_count",
                    "tool_call_count", "title", "last_active", "preview",
                    "model", "system_prompt", "cwd",
                ):
                    if key in tip_row:
                        merged[key] = tip_row[key]
                merged["_lineage_root_id"] = s["id"]
                projected.append(merged)
            sessions = projected

        return sessions

    def _get_session_rich_row(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single session with the same enriched columns as list_sessions_rich."""
        logger.debug(
            "Entered into PostgresSessionStore._get_session_rich_row: "
            "session_id=%r",
            session_id,
        )
        scope_clause, scope_params = self._scope_clause("s")
        query = f"""
            SELECT s.*,
                COALESCE(
                    (SELECT SUBSTRING(REPLACE(REPLACE(m.content, chr(10), ' '), chr(13), ' '), 1, 63)
                     FROM messages m
                     WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                     ORDER BY m.timestamp, m.id LIMIT 1),
                    ''
                ) AS _preview_raw,
                COALESCE(
                    (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
                    s.started_at
                ) AS last_active
            FROM sessions s
            WHERE s.id = %s{scope_clause}
        """
        with self._pool.connection() as conn:
            row = conn.execute(query, (session_id, *scope_params)).fetchone()
        if not row:
            return None
        s = dict(row)
        raw = (s.pop("_preview_raw", "") or "").strip()
        if raw:
            text = raw[:60]
            s["preview"] = text + ("..." if len(raw) > 60 else "")
        else:
            s["preview"] = ""
        return s

    # =========================================================================
    # Message storage
    # =========================================================================

    # Sentinel prefix for JSON-encoded structured (list/dict) message
    # content. ``store.base.encode_content`` uses a NUL-byte
    # (``"\x00json:"``) sentinel that mirrors ``SessionDB``'s SQLite
    # scheme verbatim — but Postgres TEXT columns reject NUL bytes
    # outright ("PostgreSQL text fields cannot contain NUL (0x00) bytes"),
    # so multimodal (vision) messages would fail to persist. This uses a
    # Unicode Private-Use-Area sentinel instead: same encode/decode
    # contract, same "can't collide with real user text" guarantee, but a
    # legal Postgres TEXT byte sequence.
    _CONTENT_JSON_PREFIX = "json:"

    @classmethod
    def _encode_content(cls, content: Any) -> Any:
        """Serialize structured (list/dict) message content for Postgres.

        Scalars (``str``/``bytes``/``int``/``float``/``None``) pass
        through unchanged; lists/dicts (multimodal message parts) are
        JSON-encoded behind :attr:`_CONTENT_JSON_PREFIX`. Paired with
        :meth:`_decode_content` on read.
        """
        if content is None or isinstance(content, (str, bytes, int, float)):
            return content
        try:
            return cls._CONTENT_JSON_PREFIX + json.dumps(content)
        except (TypeError, ValueError):
            return str(content)

    @classmethod
    def _decode_content(cls, content: Any) -> Any:
        """Reverse :meth:`_encode_content`; returns scalars unchanged."""
        if isinstance(content, str) and content.startswith(cls._CONTENT_JSON_PREFIX):
            try:
                return json.loads(content[len(cls._CONTENT_JSON_PREFIX):])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Failed to decode JSON-encoded message content; "
                    "returning raw string"
                )
                return content
        return content

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str = None,
        tool_name: str = None,
        tool_calls: Any = None,
        tool_call_id: str = None,
        token_count: int = None,
        finish_reason: str = None,
        reasoning: str = None,
        reasoning_content: str = None,
        reasoning_details: Any = None,
        codex_reasoning_items: Any = None,
        codex_message_items: Any = None,
        platform_message_id: str = None,
        observed: bool = False,
    ) -> int:
        """Append a message to a session. Returns the message row ID."""
        logger.debug(
            "Entered into PostgresSessionStore.append_message: "
            "session_id=%r, role=%r",
            session_id, role,
        )
        reasoning_details_json = (
            json.dumps(reasoning_details) if reasoning_details else None
        )
        codex_items_json = (
            json.dumps(codex_reasoning_items) if codex_reasoning_items else None
        )
        codex_message_items_json = (
            json.dumps(codex_message_items) if codex_message_items else None
        )
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        stored_content = self._encode_content(content)

        num_tool_calls = 0
        if tool_calls is not None:
            num_tool_calls = len(tool_calls) if isinstance(tool_calls, list) else 1

        def _do(conn):
            if not self._session_owned_by_scope(conn, session_id):
                return 0
            cur = conn.execute(
                """INSERT INTO messages (session_id, role, content, tool_call_id,
                   tool_calls, tool_name, timestamp, token_count, finish_reason,
                   reasoning, reasoning_content, reasoning_details, codex_reasoning_items,
                   codex_message_items, platform_message_id, observed)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    session_id,
                    role,
                    stored_content,
                    tool_call_id,
                    tool_calls_json,
                    tool_name,
                    time.time(),
                    token_count,
                    finish_reason,
                    reasoning,
                    reasoning_content,
                    reasoning_details_json,
                    codex_items_json,
                    codex_message_items_json,
                    platform_message_id,
                    1 if observed else 0,
                ),
            )
            msg_id = cur.fetchone()["id"]

            if num_tool_calls > 0:
                conn.execute(
                    """UPDATE sessions SET message_count = message_count + 1,
                       tool_call_count = tool_call_count + %s WHERE id = %s""",
                    (num_tool_calls, session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET message_count = message_count + 1 WHERE id = %s",
                    (session_id,),
                )
            return msg_id

        return self._execute_write(_do)

    def replace_messages(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        """Atomically replace every message for a session."""
        logger.debug(
            "Entered into PostgresSessionStore.replace_messages: "
            "session_id=%r, count=%d",
            session_id, len(messages),
        )

        def _do(conn):
            if not self._session_owned_by_scope(conn, session_id):
                return
            conn.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
            conn.execute(
                "UPDATE sessions SET message_count = 0, tool_call_count = 0 WHERE id = %s",
                (session_id,),
            )

            now_ts = time.time()
            total_messages = 0
            total_tool_calls = 0
            for msg in messages:
                role = msg.get("role", "unknown")
                tool_calls = msg.get("tool_calls")
                reasoning_details = msg.get("reasoning_details") if role == "assistant" else None
                codex_reasoning_items = (
                    msg.get("codex_reasoning_items") if role == "assistant" else None
                )
                codex_message_items = (
                    msg.get("codex_message_items") if role == "assistant" else None
                )

                reasoning_details_json = (
                    json.dumps(reasoning_details) if reasoning_details else None
                )
                codex_items_json = (
                    json.dumps(codex_reasoning_items) if codex_reasoning_items else None
                )
                codex_message_items_json = (
                    json.dumps(codex_message_items) if codex_message_items else None
                )
                tool_calls_json = json.dumps(tool_calls) if tool_calls else None
                platform_msg_id = (
                    msg.get("platform_message_id") or msg.get("message_id")
                )

                conn.execute(
                    """INSERT INTO messages (session_id, role, content, tool_call_id,
                       tool_calls, tool_name, timestamp, token_count, finish_reason,
                       reasoning, reasoning_content, reasoning_details, codex_reasoning_items,
                       codex_message_items, platform_message_id, observed)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        session_id,
                        role,
                        self._encode_content(msg.get("content")),
                        msg.get("tool_call_id"),
                        tool_calls_json,
                        msg.get("tool_name"),
                        now_ts,
                        msg.get("token_count"),
                        msg.get("finish_reason"),
                        msg.get("reasoning") if role == "assistant" else None,
                        msg.get("reasoning_content") if role == "assistant" else None,
                        reasoning_details_json,
                        codex_items_json,
                        codex_message_items_json,
                        platform_msg_id,
                        1 if msg.get("observed") else 0,
                    ),
                )
                total_messages += 1
                if tool_calls is not None:
                    total_tool_calls += (
                        len(tool_calls) if isinstance(tool_calls, list) else 1
                    )
                now_ts += 1e-6

            conn.execute(
                "UPDATE sessions SET message_count = %s, tool_call_count = %s WHERE id = %s",
                (total_messages, total_tool_calls, session_id),
            )

        self._execute_write(_do)

    def get_messages(
        self, session_id: str, include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """Load messages for a session in insertion order."""
        logger.debug(
            "Entered into PostgresSessionStore.get_messages: "
            "session_id=%r, include_inactive=%s",
            session_id, include_inactive,
        )
        active_clause = "" if include_inactive else " AND active = 1"
        msg_scope, msg_scope_params = self._messages_scope_clause()
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = %s"
                f"{msg_scope}{active_clause} ORDER BY id",
                (session_id, *msg_scope_params),
            ).fetchall()
        result = []
        for row in rows:
            msg = dict(row)
            if "content" in msg:
                msg["content"] = self._decode_content(msg["content"])
            if msg.get("tool_calls"):
                try:
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Failed to deserialize tool_calls in get_messages, "
                        "falling back to []"
                    )
                    msg["tool_calls"] = []
            result.append(msg)
        return result

    def get_messages_around(
        self,
        session_id: str,
        around_message_id: int,
        window: int = 5,
    ) -> Dict[str, Any]:
        """Load a window of messages anchored on a specific message id."""
        logger.debug(
            "Entered into PostgresSessionStore.get_messages_around: "
            "session_id=%r, around_message_id=%r, window=%d",
            session_id, around_message_id, window,
        )
        if window < 0:
            window = 0
        msg_scope, msg_scope_params = self._messages_scope_clause()
        with self._pool.connection() as conn:
            anchor_exists = conn.execute(
                f"SELECT 1 FROM messages WHERE id = %s AND session_id = %s{msg_scope} LIMIT 1",
                (around_message_id, session_id, *msg_scope_params),
            ).fetchone()
            if not anchor_exists:
                return {"window": [], "messages_before": 0, "messages_after": 0}

            before_rows = conn.execute(
                "SELECT * FROM messages "
                f"WHERE session_id = %s AND id <= %s{msg_scope} "
                "ORDER BY id DESC LIMIT %s",
                (session_id, around_message_id, *msg_scope_params, window + 1),
            ).fetchall()
            after_rows = conn.execute(
                "SELECT * FROM messages "
                f"WHERE session_id = %s AND id > %s{msg_scope} "
                "ORDER BY id ASC LIMIT %s",
                (session_id, around_message_id, *msg_scope_params, window),
            ).fetchall()

        rows = list(reversed(before_rows)) + list(after_rows)
        result = []
        for row in rows:
            msg = dict(row)
            if "content" in msg:
                msg["content"] = self._decode_content(msg["content"])
            if msg.get("tool_calls"):
                try:
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Failed to deserialize tool_calls in get_messages_around, "
                        "falling back to []"
                    )
                    msg["tool_calls"] = []
            result.append(msg)

        messages_before = max(0, len(before_rows) - 1)
        messages_after = len(after_rows)
        return {
            "window": result,
            "messages_before": messages_before,
            "messages_after": messages_after,
        }

    def get_anchored_view(
        self,
        session_id: str,
        around_message_id: int,
        window: int = 5,
        bookend: int = 3,
        keep_roles: Optional[Tuple[str, ...]] = ("user", "assistant"),
    ) -> Dict[str, Any]:
        """Return an anchored window plus session bookends."""
        logger.debug(
            "Entered into PostgresSessionStore.get_anchored_view: "
            "session_id=%r, around_message_id=%r",
            session_id, around_message_id,
        )
        if bookend < 0:
            bookend = 0

        primitive = self.get_messages_around(
            session_id, around_message_id, window=window
        )
        window_rows = primitive["window"]
        if not window_rows:
            return {
                "window": [],
                "messages_before": 0,
                "messages_after": 0,
                "bookend_start": [],
                "bookend_end": [],
            }

        if keep_roles is not None:
            keep_set = set(keep_roles)
            filtered_window = [
                m for m in window_rows
                if m.get("id") == around_message_id or m.get("role") in keep_set
            ]
        else:
            filtered_window = window_rows

        window_min_id = window_rows[0]["id"]
        window_max_id = window_rows[-1]["id"]

        bookend_start_rows: List[Any] = []
        bookend_end_rows: List[Any] = []
        msg_scope, msg_scope_params = self._messages_scope_clause()
        if bookend > 0:
            role_clause = ""
            role_params: list = []
            if keep_roles is not None:
                role_clause = " AND role = ANY(%s)"
                role_params = [list(keep_roles)]

            with self._pool.connection() as conn:
                bookend_start_rows = conn.execute(
                    f"SELECT * FROM messages "
                    f"WHERE session_id = %s AND id < %s{msg_scope}{role_clause} "
                    f"AND length(content) > 0 "
                    f"ORDER BY id ASC LIMIT %s",
                    (session_id, window_min_id, *msg_scope_params, *role_params, bookend),
                ).fetchall()

                bookend_end_rows = conn.execute(
                    f"SELECT * FROM messages "
                    f"WHERE session_id = %s AND id > %s{msg_scope}{role_clause} "
                    f"AND length(content) > 0 "
                    f"ORDER BY id DESC LIMIT %s",
                    (session_id, window_max_id, *msg_scope_params, *role_params, bookend),
                ).fetchall()
                bookend_end_rows = list(reversed(bookend_end_rows))

        def _hydrate(row) -> Dict[str, Any]:
            msg = dict(row)
            if "content" in msg:
                msg["content"] = self._decode_content(msg["content"])
            if msg.get("tool_calls"):
                try:
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Failed to deserialize tool_calls in get_anchored_view, "
                        "falling back to []"
                    )
                    msg["tool_calls"] = []
            return msg

        return {
            "window": filtered_window,
            "messages_before": primitive["messages_before"],
            "messages_after": primitive["messages_after"],
            "bookend_start": [_hydrate(r) for r in bookend_start_rows],
            "bookend_end": [_hydrate(r) for r in bookend_end_rows],
        }

    def resolve_resume_session_id(self, session_id: str) -> str:
        """Redirect a resume target to the descendant session that holds the messages."""
        logger.debug(
            "Entered into PostgresSessionStore.resolve_resume_session_id: %r",
            session_id,
        )
        if not session_id:
            return session_id

        msg_scope, msg_scope_params = self._messages_scope_clause()
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            try:
                row = conn.execute(
                    f"SELECT 1 FROM messages WHERE session_id = %s{msg_scope} LIMIT 1",
                    (session_id, *msg_scope_params),
                ).fetchone()
            except Exception:
                return session_id
            if row is not None:
                return session_id

            current = session_id
            seen = {current}
            for _ in range(32):
                try:
                    child_row = conn.execute(
                        f"SELECT id FROM sessions "
                        f"WHERE parent_session_id = %s{scope_clause} "
                        f"ORDER BY started_at DESC, id DESC LIMIT 1",
                        (current, *scope_params),
                    ).fetchone()
                except Exception:
                    return session_id
                if child_row is None:
                    return session_id
                child_id = child_row["id"]
                if not child_id or child_id in seen:
                    return session_id
                seen.add(child_id)
                try:
                    msg_row = conn.execute(
                        f"SELECT 1 FROM messages WHERE session_id = %s{msg_scope} LIMIT 1",
                        (child_id, *msg_scope_params),
                    ).fetchone()
                except Exception:
                    return session_id
                if msg_row is not None:
                    return child_id
                current = child_id
        return session_id

    def get_messages_as_conversation(
        self,
        session_id: str,
        include_ancestors: bool = False,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Load messages in the OpenAI conversation format (role + content dicts)."""
        logger.debug(
            "Entered into PostgresSessionStore.get_messages_as_conversation: "
            "session_id=%r, include_ancestors=%s",
            session_id, include_ancestors,
        )
        session_ids = [session_id]
        if include_ancestors:
            session_ids = self._session_lineage_root_to_tip(session_id)

        active_clause = "" if include_inactive else " AND active = 1"
        msg_scope, msg_scope_params = self._messages_scope_clause()
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT role, content, tool_call_id, tool_calls, tool_name, "
                "finish_reason, reasoning, reasoning_content, reasoning_details, "
                "codex_reasoning_items, codex_message_items, platform_message_id, observed "
                f"FROM messages WHERE session_id = ANY(%s)"
                f"{msg_scope}{active_clause} ORDER BY id",
                (session_ids, *msg_scope_params),
            ).fetchall()

        messages = []
        for row in rows:
            content = self._decode_content(row["content"])
            if (
                row["role"] in {"user", "assistant"}
                and isinstance(content, str)
                and _sanitize_context is not None
            ):
                content = _sanitize_context(content).strip()
            msg = {"role": row["role"], "content": content}
            if row["tool_call_id"]:
                msg["tool_call_id"] = row["tool_call_id"]
            if row["tool_name"]:
                msg["tool_name"] = row["tool_name"]
            if row["tool_calls"]:
                try:
                    msg["tool_calls"] = json.loads(row["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Failed to deserialize tool_calls in conversation replay, "
                        "falling back to []"
                    )
                    msg["tool_calls"] = []
            if row["platform_message_id"]:
                msg["message_id"] = row["platform_message_id"]
            if row["observed"]:
                msg["observed"] = True
            if row["role"] == "assistant":
                if row["finish_reason"]:
                    msg["finish_reason"] = row["finish_reason"]
                if row["reasoning"]:
                    msg["reasoning"] = row["reasoning"]
                if row["reasoning_content"] is not None:
                    msg["reasoning_content"] = row["reasoning_content"]
                if row["reasoning_details"]:
                    try:
                        msg["reasoning_details"] = json.loads(row["reasoning_details"])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "Failed to deserialize reasoning_details, falling back to None"
                        )
                        msg["reasoning_details"] = None
                if row["codex_reasoning_items"]:
                    try:
                        msg["codex_reasoning_items"] = json.loads(row["codex_reasoning_items"])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "Failed to deserialize codex_reasoning_items, falling back to None"
                        )
                        msg["codex_reasoning_items"] = None
                if row["codex_message_items"]:
                    try:
                        msg["codex_message_items"] = json.loads(row["codex_message_items"])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "Failed to deserialize codex_message_items, falling back to None"
                        )
                        msg["codex_message_items"] = None
            if include_ancestors and self._is_duplicate_replayed_user_message(messages, msg):
                continue
            messages.append(msg)
        return messages

    def _session_lineage_root_to_tip(self, session_id: str) -> List[str]:
        logger.debug(
            "Entered into PostgresSessionStore._session_lineage_root_to_tip: %r",
            session_id,
        )
        if not session_id:
            return [session_id]

        chain = []
        current = session_id
        seen = set()
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            for _ in range(100):
                if not current or current in seen:
                    break
                seen.add(current)
                chain.append(current)
                row = conn.execute(
                    f"SELECT parent_session_id FROM sessions WHERE id = %s{scope_clause}",
                    (current, *scope_params),
                ).fetchone()
                if row is None:
                    break
                current = row["parent_session_id"]
        return list(reversed(chain)) or [session_id]

    @staticmethod
    def _is_duplicate_replayed_user_message(
        messages: List[Dict[str, Any]], msg: Dict[str, Any]
    ) -> bool:
        if msg.get("role") != "user":
            return False
        content = msg.get("content")
        if not isinstance(content, str) or not content:
            return False
        for prev in reversed(messages):
            if prev.get("role") == "user" and prev.get("content") == content:
                return True
            if prev.get("role") == "assistant" and (prev.get("content") or prev.get("tool_calls")):
                return False
        return False

    # =========================================================================
    # Rewind (soft-delete)
    # =========================================================================

    def rewind_to_message(
        self, session_id: str, target_message_id: int
    ) -> Dict[str, Any]:
        """Soft-delete all messages with id >= ``target_message_id`` in *session_id*."""
        logger.debug(
            "Entered into PostgresSessionStore.rewind_to_message: "
            "session_id=%r, target_message_id=%r",
            session_id, target_message_id,
        )
        msg_scope, msg_scope_params = self._messages_scope_clause()
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT * FROM messages WHERE id = %s AND session_id = %s{msg_scope}",
                (target_message_id, session_id, *msg_scope_params),
            ).fetchone()
        if row is None:
            raise ValueError(
                f"message {target_message_id} not found in session {session_id}"
            )
        target_row = dict(row)
        if target_row.get("role") != "user":
            raise ValueError(
                f"rewind target must be a 'user' message (got role="
                f"{target_row.get('role')!r}, id={target_message_id})"
            )

        target_row["content"] = self._decode_content(target_row.get("content"))

        def _do(conn):
            if not self._session_owned_by_scope(conn, session_id):
                return []
            cur = conn.execute(
                "SELECT id FROM messages "
                "WHERE session_id = %s AND id >= %s AND active = 1",
                (session_id, target_message_id),
            )
            ids = [r["id"] for r in cur.fetchall()]
            if ids:
                conn.execute(
                    "UPDATE messages SET active = 0 WHERE id = ANY(%s)", (ids,),
                )
            conn.execute(
                "UPDATE sessions SET rewind_count = COALESCE(rewind_count, 0) + 1 "
                "WHERE id = %s",
                (session_id,),
            )
            return ids

        rewound = self._execute_write(_do)

        with self._pool.connection() as conn:
            head_row = conn.execute(
                f"SELECT MAX(id) AS max_id FROM messages "
                f"WHERE session_id = %s AND active = 1{msg_scope}",
                (session_id, *msg_scope_params),
            ).fetchone()
        new_head_id = head_row["max_id"] if head_row else None

        return {
            "rewound_count": len(rewound),
            "target_message": target_row,
            "new_head_id": new_head_id,
        }

    def restore_rewound(self, session_id: str, since_message_id: int) -> int:
        """Mark inactive messages with id >= *since_message_id* active again."""
        logger.debug(
            "Entered into PostgresSessionStore.restore_rewound: "
            "session_id=%r, since_message_id=%r",
            session_id, since_message_id,
        )

        def _do(conn):
            if not self._session_owned_by_scope(conn, session_id):
                return 0
            cur = conn.execute(
                "SELECT id FROM messages "
                "WHERE session_id = %s AND id >= %s AND active = 0",
                (session_id, since_message_id),
            )
            ids = [r["id"] for r in cur.fetchall()]
            if ids:
                conn.execute(
                    "UPDATE messages SET active = 1 WHERE id = ANY(%s)", (ids,),
                )
            return len(ids)

        return self._execute_write(_do)

    def list_recent_user_messages(
        self,
        session_id: str,
        limit: int = 20,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return the *limit* most-recent user messages, newest first."""
        logger.debug(
            "Entered into PostgresSessionStore.list_recent_user_messages: "
            "session_id=%r, limit=%d",
            session_id, limit,
        )
        active_clause = "" if include_inactive else " AND active = 1"
        msg_scope, msg_scope_params = self._messages_scope_clause()
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, content FROM messages "
                f"WHERE session_id = %s AND role = 'user'{msg_scope}"
                f"{active_clause} "
                "ORDER BY id DESC LIMIT %s",
                (session_id, *msg_scope_params, int(limit)),
            ).fetchall()

        result: List[Dict[str, Any]] = []
        for row in rows:
            decoded = self._decode_content(row["content"])
            if isinstance(decoded, list):
                text_parts = [
                    p.get("text", "") for p in decoded
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                preview = " ".join(t for t in text_parts if t).strip()
                if not preview:
                    preview = "[multimodal content]"
            elif isinstance(decoded, str):
                preview = decoded
            else:
                preview = ""
            preview = " ".join(preview.split())
            if len(preview) > 80:
                preview = preview[:77] + "..."
            result.append(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "preview": preview,
                }
            )
        return result

    # =========================================================================
    # Search
    # =========================================================================

    @staticmethod
    def _is_cjk_codepoint(cp: int) -> bool:
        return (0x4E00 <= cp <= 0x9FFF or
                0x3400 <= cp <= 0x4DBF or
                0x20000 <= cp <= 0x2A6DF or
                0x3000 <= cp <= 0x303F or
                0x3040 <= cp <= 0x309F or
                0x30A0 <= cp <= 0x30FF or
                0xAC00 <= cp <= 0xD7AF)

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        """Check if text contains CJK (Chinese, Japanese, Korean) characters."""
        for ch in text:
            if PostgresSessionStore._is_cjk_codepoint(ord(ch)):
                return True
        return False

    @classmethod
    def _count_cjk(cls, text: str) -> int:
        """Count CJK characters in text."""
        return sum(1 for ch in text if cls._is_cjk_codepoint(ord(ch)))

    def search_messages(
        self,
        query: str,
        source_filter: List[str] = None,
        exclude_sources: List[str] = None,
        role_filter: List[str] = None,
        limit: int = 20,
        offset: int = 0,
        sort: str = None,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Full-text search across session messages using Postgres tsvector.

        The default ``'simple'`` text search config (no stopwords, no
        stemming) is the closest match to SQLite FTS5's unicode61 tokenizer.
        CJK / substring queries bypass ``tsvector`` (whose tokenizer splits
        CJK glyphs the same way unicode61 does) and use a ``pg_trgm``-backed
        ``LIKE`` scan over the same concatenated content instead.

        ``sort`` controls temporal ordering:
          - ``None`` (default): relevance only (``ts_rank`` / newest-first
            for the CJK LIKE path, which has no relevance signal).
          - ``"newest"``: order by message timestamp DESC.
          - ``"oldest"``: order by message timestamp ASC.

        Rewound (``active=0``) rows are excluded by default. Pass
        ``include_inactive=True`` to search every row.
        """
        logger.debug(
            "Entered into PostgresSessionStore.search_messages: "
            "query=%r, limit=%d, offset=%d",
            query, limit, offset,
        )
        if not self._fts_enabled:
            return []
        if not query or not query.strip():
            return []
        query = query.strip()

        if isinstance(sort, str):
            sort_norm = sort.strip().lower()
            if sort_norm not in ("newest", "oldest"):
                sort_norm = None
        else:
            sort_norm = None

        is_cjk = self._contains_cjk(query)
        matches: List[Dict[str, Any]] = []

        with self._pool.connection() as conn:
            if is_cjk:
                non_op_tokens = [
                    t for t in query.split()
                    if t.upper() not in {"AND", "OR", "NOT"}
                ] or [query]
                concat_expr = (
                    "(COALESCE(m.content, '') || ' ' || COALESCE(m.tool_name, '') "
                    "|| ' ' || COALESCE(m.tool_calls, ''))"
                )
                token_clauses = []
                like_params: list = []
                for tok in non_op_tokens:
                    esc = (
                        tok.replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                    )
                    token_clauses.append(f"{concat_expr} LIKE %s ESCAPE '\\'")
                    like_params.append(f"%{esc}%")
                where_clauses = [f"({' OR '.join(token_clauses)})"]
                if not include_inactive:
                    where_clauses.append("m.active = 1")
                if source_filter is not None:
                    where_clauses.append("s.source = ANY(%s)")
                    like_params.append(source_filter)
                if exclude_sources is not None:
                    where_clauses.append("NOT (s.source = ANY(%s))")
                    like_params.append(exclude_sources)
                if role_filter:
                    where_clauses.append("m.role = ANY(%s)")
                    like_params.append(role_filter)

                order_sql = (
                    "ORDER BY m.timestamp ASC" if sort_norm == "oldest"
                    else "ORDER BY m.timestamp DESC"
                )
                cjk_sql = f"""
                    SELECT m.id, m.session_id, m.role,
                           SUBSTRING(m.content FROM GREATEST(1, POSITION(%s IN m.content) - 40) FOR 120) AS snippet,
                           m.content, m.timestamp, m.tool_name,
                           s.source, s.model, s.started_at AS session_started
                    FROM messages m
                    JOIN sessions s ON s.id = m.session_id
                    WHERE {' AND '.join(where_clauses)}
                    {order_sql}
                    LIMIT %s OFFSET %s
                """
                cjk_params = [non_op_tokens[0]] + like_params + [limit, offset]
                try:
                    cursor = conn.execute(cjk_sql, cjk_params)
                except psycopg.Error:
                    matches = []
                else:
                    matches = [dict(row) for row in cursor.fetchall()]
            else:
                where_clauses = ["m.search_vector @@ plainto_tsquery('simple', %s)"]
                filter_params: list = [query]
                if not include_inactive:
                    where_clauses.append("m.active = 1")
                if source_filter is not None:
                    where_clauses.append("s.source = ANY(%s)")
                    filter_params.append(source_filter)
                if exclude_sources is not None:
                    where_clauses.append("NOT (s.source = ANY(%s))")
                    filter_params.append(exclude_sources)
                if role_filter:
                    where_clauses.append("m.role = ANY(%s)")
                    filter_params.append(role_filter)

                if sort_norm == "newest":
                    order_sql = "ORDER BY m.timestamp DESC, rank DESC"
                elif sort_norm == "oldest":
                    order_sql = "ORDER BY m.timestamp ASC, rank DESC"
                else:
                    order_sql = "ORDER BY rank DESC"

                sql = f"""
                    SELECT
                        m.id, m.session_id, m.role,
                        ts_headline(
                            'simple',
                            COALESCE(m.content, '') || ' ' || COALESCE(m.tool_name, '') || ' ' || COALESCE(m.tool_calls, ''),
                            plainto_tsquery('simple', %s),
                            'StartSel=>>>, StopSel=<<<, MaxFragments=3, MaxWords=40'
                        ) AS snippet,
                        m.content, m.timestamp, m.tool_name,
                        s.source, s.model, s.started_at AS session_started,
                        ts_rank(m.search_vector, plainto_tsquery('simple', %s)) AS rank
                    FROM messages m
                    JOIN sessions s ON s.id = m.session_id
                    WHERE {' AND '.join(where_clauses)}
                    {order_sql}
                    LIMIT %s OFFSET %s
                """
                params = [query, query] + filter_params + [limit, offset]
                try:
                    cursor = conn.execute(sql, params)
                except psycopg.Error:
                    matches = []
                else:
                    matches = [dict(row) for row in cursor.fetchall()]

            for match in matches:
                try:
                    ctx_cursor = conn.execute(
                        """WITH target AS (
                               SELECT session_id, timestamp, id
                               FROM messages
                               WHERE id = %s
                           )
                           SELECT role, content
                           FROM (
                               SELECT m.id, m.timestamp, m.role, m.content
                               FROM messages m
                               JOIN target t ON t.session_id = m.session_id
                               WHERE (m.timestamp < t.timestamp)
                                  OR (m.timestamp = t.timestamp AND m.id < t.id)
                               ORDER BY m.timestamp DESC, m.id DESC
                               LIMIT 1
                           ) before_msg
                           UNION ALL
                           SELECT role, content
                           FROM messages
                           WHERE id = %s
                           UNION ALL
                           SELECT role, content
                           FROM (
                               SELECT m.id, m.timestamp, m.role, m.content
                               FROM messages m
                               JOIN target t ON t.session_id = m.session_id
                               WHERE (m.timestamp > t.timestamp)
                                  OR (m.timestamp = t.timestamp AND m.id > t.id)
                               ORDER BY m.timestamp ASC, m.id ASC
                               LIMIT 1
                           ) after_msg""",
                        (match["id"], match["id"]),
                    )
                    context_msgs = []
                    for r in ctx_cursor.fetchall():
                        decoded = self._decode_content(r["content"])
                        if isinstance(decoded, list):
                            text_parts = [
                                p.get("text", "") for p in decoded
                                if isinstance(p, dict) and p.get("type") == "text"
                            ]
                            text = " ".join(t for t in text_parts if t).strip()
                            preview = text or "[multimodal content]"
                        elif isinstance(decoded, str):
                            preview = decoded
                        else:
                            preview = ""
                        context_msgs.append({"role": r["role"], "content": preview[:200]})
                    match["context"] = context_msgs
                except Exception:
                    match["context"] = []

        for match in matches:
            match.pop("content", None)

        return matches

    def search_sessions(
        self,
        source: str = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List sessions, optionally filtered by source, most-recently-used first."""
        logger.debug(
            "Entered into PostgresSessionStore.search_sessions: "
            "source=%r, limit=%d, offset=%d",
            source, limit, offset,
        )
        select_with_last_active = (
            "SELECT s.*, COALESCE(m.last_active, s.started_at) AS last_active "
            "FROM sessions s "
            "LEFT JOIN ("
            "SELECT session_id, MAX(timestamp) AS last_active "
            "FROM messages GROUP BY session_id"
            ") m ON m.session_id = s.id "
        )
        scope_clause, scope_params = self._scope_clause("s")
        with self._pool.connection() as conn:
            if source:
                rows = conn.execute(
                    f"{select_with_last_active}"
                    f"WHERE s.source = %s{scope_clause} "
                    "ORDER BY last_active DESC, s.started_at DESC, s.id DESC LIMIT %s OFFSET %s",
                    (source, *scope_params, limit, offset),
                ).fetchall()
            elif scope_clause:
                rows = conn.execute(
                    f"{select_with_last_active}"
                    f"WHERE 1 = 1{scope_clause} "
                    "ORDER BY last_active DESC, s.started_at DESC, s.id DESC LIMIT %s OFFSET %s",
                    (*scope_params, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"{select_with_last_active}"
                    "ORDER BY last_active DESC, s.started_at DESC, s.id DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                ).fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # Utility
    # =========================================================================

    def session_count(
        self,
        source: str = None,
        min_message_count: int = 0,
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> int:
        """Count sessions, optionally filtered by source."""
        logger.debug(
            "Entered into PostgresSessionStore.session_count: source=%r",
            source,
        )
        where_clauses = []
        params = []

        if source:
            where_clauses.append("source = %s")
            params.append(source)
        if min_message_count > 0:
            where_clauses.append("message_count >= %s")
            params.append(min_message_count)
        if archived_only:
            where_clauses.append("archived = 1")
        elif not include_archived:
            where_clauses.append("archived = 0")

        if self._scope_user_id is not None:
            where_clauses.append("user_id = %s")
            params.append(self._scope_user_id)

        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM sessions{where_sql}", params
            ).fetchone()
            return row["n"]

    def message_count(self, session_id: str = None) -> int:
        """Count messages, optionally for a specific session."""
        logger.debug(
            "Entered into PostgresSessionStore.message_count: "
            "session_id=%r",
            session_id,
        )
        msg_scope, msg_scope_params = self._messages_scope_clause()
        with self._pool.connection() as conn:
            if session_id:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM messages WHERE session_id = %s{msg_scope}",
                    (session_id, *msg_scope_params),
                ).fetchone()
            elif self._scope_user_id is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()
            else:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM messages WHERE 1 = 1{msg_scope}",
                    msg_scope_params,
                ).fetchone()
            return row["n"]

    # =========================================================================
    # Export and cleanup
    # =========================================================================

    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Export a single session with all its messages as a dict."""
        logger.debug(
            "Entered into PostgresSessionStore.export_session: "
            "session_id=%r",
            session_id,
        )
        session = self.get_session(session_id)
        if not session:
            return None
        messages = self.get_messages(session_id)
        return {**session, "messages": messages}

    def export_all(self, source: str = None) -> List[Dict[str, Any]]:
        """Export all sessions (with messages) as a list of dicts."""
        logger.debug(
            "Entered into PostgresSessionStore.export_all: source=%r",
            source,
        )
        sessions = self.search_sessions(source=source, limit=100000)
        results = []
        for session in sessions:
            messages = self.get_messages(session["id"])
            results.append({**session, "messages": messages})
        return results

    def clear_messages(self, session_id: str) -> None:
        """Delete all messages for a session and reset its counters."""
        logger.debug(
            "Entered into PostgresSessionStore.clear_messages: "
            "session_id=%r",
            session_id,
        )

        def _do(conn):
            if not self._session_owned_by_scope(conn, session_id):
                return
            conn.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
            conn.execute(
                "UPDATE sessions SET message_count = 0, tool_call_count = 0 WHERE id = %s",
                (session_id,),
            )

        self._execute_write(_do)

    @staticmethod
    def _remove_session_files(sessions_dir: Optional[Path], session_id: str) -> None:
        """Remove on-disk transcript files for a session."""
        if sessions_dir is None:
            return
        for suffix in (".json", ".jsonl"):
            p = sessions_dir / f"{session_id}{suffix}"
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            for p in sessions_dir.glob(f"request_dump_{session_id}_*.json"):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError:
            pass

    def delete_session(
        self,
        session_id: str,
        sessions_dir: Optional[Path] = None,
    ) -> bool:
        """Delete a session and all its messages."""
        logger.debug(
            "Entered into PostgresSessionStore.delete_session: "
            "session_id=%r",
            session_id,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM sessions WHERE id = %s{scope_clause}",
                (session_id, *scope_params),
            ).fetchone()
            if row["n"] == 0:
                return False
            conn.execute(
                f"UPDATE sessions SET parent_session_id = NULL "
                f"WHERE parent_session_id = %s{scope_clause}",
                (session_id, *scope_params),
            )
            conn.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
            conn.execute(
                f"DELETE FROM sessions WHERE id = %s{scope_clause}",
                (session_id, *scope_params),
            )
            return True

        deleted = self._execute_write(_do)
        if deleted:
            self._remove_session_files(sessions_dir, session_id)
        return deleted

    def delete_sessions(
        self,
        session_ids: List[str],
        sessions_dir: Optional[Path] = None,
    ) -> int:
        """Delete every session in *session_ids* in a single transaction."""
        logger.debug(
            "Entered into PostgresSessionStore.delete_sessions: count=%d",
            len(session_ids or []),
        )
        if not session_ids:
            return 0
        unique_ids = list({sid for sid in session_ids if isinstance(sid, str) and sid})
        if not unique_ids:
            return 0

        removed_ids: List[str] = []

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            rows = conn.execute(
                f"SELECT id FROM sessions WHERE id = ANY(%s){scope_clause}",
                [unique_ids, *scope_params],
            ).fetchall()
            existing = [row["id"] for row in rows]
            if not existing:
                return 0

            conn.execute(
                f"UPDATE sessions SET parent_session_id = NULL "
                f"WHERE parent_session_id = ANY(%s){scope_clause}",
                [existing, *scope_params],
            )
            conn.execute(
                "DELETE FROM messages WHERE session_id = ANY(%s)", (existing,)
            )
            conn.execute(
                f"DELETE FROM sessions WHERE id = ANY(%s){scope_clause}",
                [existing, *scope_params],
            )
            removed_ids.extend(existing)
            return len(existing)

        count = self._execute_write(_do)
        for sid in removed_ids:
            self._remove_session_files(sessions_dir, sid)
        return count

    def count_empty_sessions(self) -> int:
        """Return the count of empty, ended, non-archived sessions."""
        logger.debug("Entered into PostgresSessionStore.count_empty_sessions")
        scope_clause, scope_params = self._scope_clause()
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM sessions "
                f"WHERE message_count = 0 "
                f"AND ended_at IS NOT NULL "
                f"AND archived = 0{scope_clause}",
                scope_params,
            ).fetchone()
            return row["n"]

    def delete_empty_sessions(
        self,
        sessions_dir: Optional[Path] = None,
    ) -> int:
        """Delete every empty, ended, non-archived session."""
        logger.debug("Entered into PostgresSessionStore.delete_empty_sessions")
        removed_ids: List[str] = []

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            rows = conn.execute(
                f"SELECT id FROM sessions "
                f"WHERE message_count = 0 "
                f"AND ended_at IS NOT NULL "
                f"AND archived = 0{scope_clause}",
                scope_params,
            ).fetchall()
            session_ids = {row["id"] for row in rows}

            if not session_ids:
                return 0

            id_list = list(session_ids)
            conn.execute(
                "UPDATE sessions SET parent_session_id = NULL "
                "WHERE parent_session_id = ANY(%s)",
                (id_list,),
            )

            for sid in id_list:
                conn.execute("DELETE FROM messages WHERE session_id = %s", (sid,))
                conn.execute("DELETE FROM sessions WHERE id = %s", (sid,))
                removed_ids.append(sid)
            return len(id_list)

        count = self._execute_write(_do)
        for sid in removed_ids:
            self._remove_session_files(sessions_dir, sid)
        return count

    def prune_sessions(
        self,
        older_than_days: int = 90,
        source: str = None,
        sessions_dir: Optional[Path] = None,
    ) -> int:
        """Delete sessions older than N days. Returns count of deleted sessions."""
        logger.debug(
            "Entered into PostgresSessionStore.prune_sessions: "
            "older_than_days=%d, source=%r",
            older_than_days, source,
        )
        cutoff = time.time() - (older_than_days * 86400)
        removed_ids: List[str] = []

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            if source:
                rows = conn.execute(
                    f"""SELECT id FROM sessions
                       WHERE started_at < %s AND ended_at IS NOT NULL AND source = %s{scope_clause}""",
                    (cutoff, source, *scope_params),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT id FROM sessions WHERE started_at < %s AND ended_at IS NOT NULL{scope_clause}",
                    (cutoff, *scope_params),
                ).fetchall()
            session_ids = {row["id"] for row in rows}

            if not session_ids:
                return 0

            id_list = list(session_ids)
            conn.execute(
                "UPDATE sessions SET parent_session_id = NULL "
                "WHERE parent_session_id = ANY(%s)",
                (id_list,),
            )

            for sid in id_list:
                conn.execute("DELETE FROM messages WHERE session_id = %s", (sid,))
                conn.execute("DELETE FROM sessions WHERE id = %s", (sid,))
                removed_ids.append(sid)
            return len(id_list)

        count = self._execute_write(_do)
        for sid in removed_ids:
            self._remove_session_files(sessions_dir, sid)
        return count

    # ── Meta key/value (global, unscoped) ──

    def get_meta(self, key: str) -> Optional[str]:
        """Read a value from the state_meta key/value store."""
        logger.debug("Entered into PostgresSessionStore.get_meta: key=%r", key)
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT value FROM state_meta WHERE key = %s", (key,)
            ).fetchone()
        if row is None:
            return None
        return row["value"]

    def set_meta(self, key: str, value: str) -> None:
        """Write a value to the state_meta key/value store."""
        logger.debug("Entered into PostgresSessionStore.set_meta: key=%r", key)

        def _do(conn):
            conn.execute(
                "INSERT INTO state_meta (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )

        self._execute_write(_do)

    # ── Telegram DM topic mode ──

    def apply_telegram_topic_migration(self) -> None:
        """Create Telegram DM topic-mode tables on explicit /topic opt-in.

        Deliberately not part of automatic store initialization — these
        tables are only created the first time a Telegram DM chat opts
        into /topic.
        """
        logger.debug(
            "Entered into PostgresSessionStore.apply_telegram_topic_migration"
        )

        def _do(conn):
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_dm_topic_mode (
                    chat_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    enabled SMALLINT NOT NULL DEFAULT 1,
                    activated_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    has_topics_enabled SMALLINT,
                    allows_users_to_create_topics SMALLINT,
                    capability_checked_at DOUBLE PRECISION,
                    intro_message_id TEXT,
                    pinned_message_id TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_dm_topic_bindings (
                    chat_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_key TEXT NOT NULL,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    managed_mode TEXT NOT NULL DEFAULT 'auto',
                    linked_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (chat_id, thread_id)
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_dm_topic_bindings_session "
                "ON telegram_dm_topic_bindings(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_telegram_dm_topic_bindings_user "
                "ON telegram_dm_topic_bindings(user_id, chat_id)"
            )

            current = conn.execute(
                "SELECT value FROM state_meta WHERE key = %s",
                ("telegram_dm_topic_schema_version",),
            ).fetchone()
            current_version = (
                int(current["value"])
                if current and str(current["value"]).isdigit()
                else 0
            )
            if current_version < 2:
                fk_rows = conn.execute(
                    """
                    SELECT rc.delete_rule
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.referential_constraints rc
                        ON rc.constraint_name = tc.constraint_name
                        AND rc.constraint_schema = tc.constraint_schema
                    JOIN information_schema.constraint_column_usage ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.constraint_schema = tc.constraint_schema
                    WHERE tc.table_name = 'telegram_dm_topic_bindings'
                      AND tc.constraint_type = 'FOREIGN KEY'
                      AND ccu.table_name = 'sessions'
                    """
                ).fetchall()
                needs_rebuild = any(
                    (row["delete_rule"] or "") != "CASCADE" for row in fk_rows
                )
                if needs_rebuild:
                    conn.execute(
                        """
                        CREATE TABLE telegram_dm_topic_bindings_new (
                            chat_id TEXT NOT NULL,
                            thread_id TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            session_key TEXT NOT NULL,
                            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                            managed_mode TEXT NOT NULL DEFAULT 'auto',
                            linked_at DOUBLE PRECISION NOT NULL,
                            updated_at DOUBLE PRECISION NOT NULL,
                            PRIMARY KEY (chat_id, thread_id)
                        )
                        """
                    )
                    conn.execute(
                        "INSERT INTO telegram_dm_topic_bindings_new "
                        "SELECT chat_id, thread_id, user_id, session_key, session_id, "
                        "managed_mode, linked_at, updated_at FROM telegram_dm_topic_bindings"
                    )
                    conn.execute("DROP TABLE telegram_dm_topic_bindings")
                    conn.execute(
                        "ALTER TABLE telegram_dm_topic_bindings_new "
                        "RENAME TO telegram_dm_topic_bindings"
                    )
                    conn.execute(
                        "CREATE UNIQUE INDEX idx_telegram_dm_topic_bindings_session "
                        "ON telegram_dm_topic_bindings(session_id)"
                    )
                    conn.execute(
                        "CREATE INDEX idx_telegram_dm_topic_bindings_user "
                        "ON telegram_dm_topic_bindings(user_id, chat_id)"
                    )

            conn.execute(
                "INSERT INTO state_meta (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                ("telegram_dm_topic_schema_version", "2"),
            )

        self._execute_write(_do)

    def enable_telegram_topic_mode(
        self,
        *,
        chat_id: str,
        user_id: str,
        has_topics_enabled: Optional[bool] = None,
        allows_users_to_create_topics: Optional[bool] = None,
    ) -> None:
        """Enable Telegram DM topic mode for one private chat/user."""
        logger.debug(
            "Entered into PostgresSessionStore.enable_telegram_topic_mode: "
            "chat_id=%r, user_id=%r",
            chat_id, user_id,
        )
        self.apply_telegram_topic_migration()
        now = time.time()

        def _to_int(value: Optional[bool]) -> Optional[int]:
            if value is None:
                return None
            return 1 if value else 0

        def _do(conn):
            conn.execute(
                """
                INSERT INTO telegram_dm_topic_mode (
                    chat_id, user_id, enabled, activated_at, updated_at,
                    has_topics_enabled, allows_users_to_create_topics,
                    capability_checked_at
                ) VALUES (%s, %s, 1, %s, %s, %s, %s, %s)
                ON CONFLICT (chat_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    enabled = 1,
                    updated_at = EXCLUDED.updated_at,
                    has_topics_enabled = EXCLUDED.has_topics_enabled,
                    allows_users_to_create_topics = EXCLUDED.allows_users_to_create_topics,
                    capability_checked_at = EXCLUDED.capability_checked_at
                """,
                (
                    str(chat_id),
                    str(user_id),
                    now,
                    now,
                    _to_int(has_topics_enabled),
                    _to_int(allows_users_to_create_topics),
                    now,
                ),
            )

        self._execute_write(_do)

    def disable_telegram_topic_mode(
        self,
        *,
        chat_id: str,
        clear_bindings: bool = True,
    ) -> None:
        """Disable Telegram DM topic mode for one private chat."""
        logger.debug(
            "Entered into PostgresSessionStore.disable_telegram_topic_mode: "
            "chat_id=%r",
            chat_id,
        )
        if not self._table_exists("telegram_dm_topic_mode"):
            return

        def _do(conn):
            conn.execute(
                "UPDATE telegram_dm_topic_mode SET enabled = 0, updated_at = %s "
                "WHERE chat_id = %s",
                (time.time(), str(chat_id)),
            )
            if clear_bindings:
                conn.execute(
                    "DELETE FROM telegram_dm_topic_bindings WHERE chat_id = %s",
                    (str(chat_id),),
                )

        self._execute_write(_do)

    def is_telegram_topic_mode_enabled(self, *, chat_id: str, user_id: str) -> bool:
        """Return whether Telegram DM topic mode is enabled for this chat/user."""
        logger.debug(
            "Entered into PostgresSessionStore.is_telegram_topic_mode_enabled: "
            "chat_id=%r, user_id=%r",
            chat_id, user_id,
        )
        if not self._table_exists("telegram_dm_topic_mode"):
            return False
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT enabled FROM telegram_dm_topic_mode "
                "WHERE chat_id = %s AND user_id = %s",
                (str(chat_id), str(user_id)),
            ).fetchone()
        if row is None:
            return False
        return bool(row["enabled"])

    def get_telegram_topic_binding(
        self,
        *,
        chat_id: str,
        thread_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the session binding for a Telegram DM topic, if present."""
        logger.debug(
            "Entered into PostgresSessionStore.get_telegram_topic_binding: "
            "chat_id=%r, thread_id=%r",
            chat_id, thread_id,
        )
        if not self._table_exists("telegram_dm_topic_bindings"):
            return None
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_dm_topic_bindings "
                "WHERE chat_id = %s AND thread_id = %s",
                (str(chat_id), str(thread_id)),
            ).fetchone()
        return dict(row) if row else None

    def list_telegram_topic_bindings_for_chat(
        self,
        *,
        chat_id: str,
    ) -> List[Dict[str, Any]]:
        """All Telegram DM topic bindings for one chat, newest first."""
        logger.debug(
            "Entered into PostgresSessionStore.list_telegram_topic_bindings_for_chat: "
            "chat_id=%r",
            chat_id,
        )
        if not self._table_exists("telegram_dm_topic_bindings"):
            return []
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM telegram_dm_topic_bindings "
                "WHERE chat_id = %s ORDER BY updated_at DESC",
                (str(chat_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_telegram_topic_binding_by_session(
        self,
        *,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the Telegram DM topic binding for a given session_id, if present."""
        logger.debug(
            "Entered into PostgresSessionStore.get_telegram_topic_binding_by_session: "
            "session_id=%r",
            session_id,
        )
        if not self._table_exists("telegram_dm_topic_bindings"):
            return None
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_dm_topic_bindings WHERE session_id = %s",
                (str(session_id),),
            ).fetchone()
        return dict(row) if row else None

    def bind_telegram_topic(
        self,
        *,
        chat_id: str,
        thread_id: str,
        user_id: str,
        session_key: str,
        session_id: str,
        managed_mode: str = "auto",
    ) -> None:
        """Bind one Telegram DM topic thread to one Elidia session."""
        logger.debug(
            "Entered into PostgresSessionStore.bind_telegram_topic: "
            "chat_id=%r, thread_id=%r, session_id=%r",
            chat_id, thread_id, session_id,
        )
        self.apply_telegram_topic_migration()
        now = time.time()
        chat_id = str(chat_id)
        thread_id = str(thread_id)
        user_id = str(user_id)
        session_key = str(session_key)
        session_id = str(session_id)

        def _do(conn):
            existing_session = conn.execute(
                "SELECT chat_id, thread_id FROM telegram_dm_topic_bindings "
                "WHERE session_id = %s",
                (session_id,),
            ).fetchone()
            if existing_session is not None:
                linked_chat = existing_session["chat_id"]
                linked_thread = existing_session["thread_id"]
                if str(linked_chat) != chat_id or str(linked_thread) != thread_id:
                    raise ValueError("session is already linked to another Telegram topic")

            conn.execute(
                """
                INSERT INTO telegram_dm_topic_bindings (
                    chat_id, thread_id, user_id, session_key, session_id,
                    managed_mode, linked_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chat_id, thread_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    session_key = EXCLUDED.session_key,
                    session_id = EXCLUDED.session_id,
                    managed_mode = EXCLUDED.managed_mode,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    chat_id,
                    thread_id,
                    user_id,
                    session_key,
                    session_id,
                    managed_mode,
                    now,
                    now,
                ),
            )

        self._execute_write(_do)

    def is_telegram_session_linked_to_topic(self, *, session_id: str) -> bool:
        """Return True if an Elidia session is already bound to any Telegram DM topic."""
        logger.debug(
            "Entered into PostgresSessionStore.is_telegram_session_linked_to_topic: "
            "session_id=%r",
            session_id,
        )
        if not self._table_exists("telegram_dm_topic_bindings"):
            return False
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM telegram_dm_topic_bindings WHERE session_id = %s LIMIT 1",
                (str(session_id),),
            ).fetchone()
        return row is not None

    def list_unlinked_telegram_sessions_for_user(
        self,
        *,
        chat_id: str,
        user_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """List previous Telegram sessions for this user that are not bound to a topic."""
        logger.debug(
            "Entered into PostgresSessionStore.list_unlinked_telegram_sessions_for_user: "
            "chat_id=%r, user_id=%r",
            chat_id, user_id,
        )
        bindings_exist = self._table_exists("telegram_dm_topic_bindings")
        with self._pool.connection() as conn:
            if bindings_exist:
                rows = conn.execute(
                    """
                    SELECT s.*,
                        COALESCE(
                            (SELECT SUBSTRING(REPLACE(REPLACE(m.content, chr(10), ' '), chr(13), ' '), 1, 63)
                             FROM messages m
                             WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                             ORDER BY m.timestamp, m.id LIMIT 1),
                            ''
                        ) AS _preview_raw,
                        COALESCE(
                            (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
                            s.started_at
                        ) AS last_active
                    FROM sessions s
                    WHERE s.source = 'telegram'
                      AND s.user_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM telegram_dm_topic_bindings b
                          WHERE b.session_id = s.id
                      )
                    ORDER BY last_active DESC, s.started_at DESC
                    LIMIT %s
                    """,
                    (str(user_id), int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.*,
                        COALESCE(
                            (SELECT SUBSTRING(REPLACE(REPLACE(m.content, chr(10), ' '), chr(13), ' '), 1, 63)
                             FROM messages m
                             WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                             ORDER BY m.timestamp, m.id LIMIT 1),
                            ''
                        ) AS _preview_raw,
                        COALESCE(
                            (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
                            s.started_at
                        ) AS last_active
                    FROM sessions s
                    WHERE s.source = 'telegram'
                      AND s.user_id = %s
                    ORDER BY last_active DESC, s.started_at DESC
                    LIMIT %s
                    """,
                    (str(user_id), int(limit)),
                ).fetchall()

        sessions: List[Dict[str, Any]] = []
        for row in rows:
            session = dict(row)
            raw = str(session.pop("_preview_raw", "") or "").strip()
            session["preview"] = raw[:60] + ("..." if len(raw) > 60 else "") if raw else ""
            sessions.append(session)
        return sessions

    # ── Space reclamation ──

    def optimize_fts(self) -> int:
        """Merge/rebuild the tsvector + trigram GIN indexes.

        Postgres doesn't fragment a ``tsvector`` GIN index the way SQLite
        FTS5 accumulates b-tree segments, but periodic ``REINDEX`` still
        clears index bloat left by heavy update/delete churn on ``messages``.
        Runs with ``autocommit`` so one index's REINDEX failure doesn't
        poison the transaction for the next.

        Returns the number of indexes successfully reindexed.
        """
        logger.debug("Entered into PostgresSessionStore.optimize_fts")
        optimized = 0
        with self._pool.connection() as conn:
            conn.autocommit = True
            try:
                for idx in self._FTS_INDEXES:
                    try:
                        conn.execute(f"REINDEX INDEX {idx}")
                        optimized += 1
                    except psycopg.Error as exc:
                        logger.warning("REINDEX %s failed: %s", idx, exc)
            finally:
                conn.autocommit = False
        return optimized

    def vacuum(self) -> int:
        """Run VACUUM to reclaim disk space after large deletes.

        ``VACUUM`` cannot run inside a transaction block, so the borrowed
        connection is switched to autocommit for the duration of the call
        and reset before it's returned to the pool.

        Returns the number of FTS indexes reindexed by :meth:`optimize_fts`
        (run first so the freed index pages are reclaimed in the same pass).
        """
        logger.debug("Entered into PostgresSessionStore.vacuum")
        optimized = 0
        try:
            optimized = self.optimize_fts()
        except Exception as exc:
            logger.warning("FTS optimize before VACUUM failed: %s", exc)
        with self._pool.connection() as conn:
            conn.autocommit = True
            try:
                conn.execute("VACUUM")
            finally:
                conn.autocommit = False
        return optimized

    def maybe_auto_prune_and_vacuum(
        self,
        retention_days: int = 90,
        min_interval_hours: int = 24,
        vacuum: bool = True,
        sessions_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Idempotent auto-maintenance: prune old sessions + optional VACUUM."""
        logger.debug(
            "Entered into PostgresSessionStore.maybe_auto_prune_and_vacuum: "
            "retention_days=%d",
            retention_days,
        )
        result: Dict[str, Any] = {"skipped": False, "pruned": 0, "vacuumed": False}
        try:
            last_raw = self.get_meta("last_auto_prune")
            now = time.time()
            if last_raw:
                try:
                    last_ts = float(last_raw)
                    if now - last_ts < min_interval_hours * 3600:
                        result["skipped"] = True
                        return result
                except (TypeError, ValueError):
                    pass

            pruned = self.prune_sessions(
                older_than_days=retention_days,
                sessions_dir=sessions_dir,
            )
            result["pruned"] = pruned

            if vacuum and pruned > 0:
                try:
                    self.vacuum()
                    result["vacuumed"] = True
                except Exception as exc:
                    logger.warning("Postgres store VACUUM failed: %s", exc)

            self.set_meta("last_auto_prune", str(now))

            if pruned > 0:
                logger.info(
                    "Postgres store auto-maintenance: pruned %d session(s) "
                    "older than %d days%s",
                    pruned,
                    retention_days,
                    " + VACUUM" if result["vacuumed"] else "",
                )
        except Exception as exc:
            logger.warning("Postgres store auto-maintenance failed: %s", exc)
            result["error"] = str(exc)

        return result

    # ── Handoff (cross-platform session transfer) ──

    def request_handoff(self, session_id: str, platform: str) -> bool:
        """Mark a session as pending handoff to the given platform."""
        logger.debug(
            "Entered into PostgresSessionStore.request_handoff: "
            "session_id=%r, platform=%r",
            session_id, platform,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            cur = conn.execute(
                "UPDATE sessions "
                "SET handoff_state = 'pending', "
                "    handoff_platform = %s, "
                "    handoff_error = NULL "
                "WHERE id = %s AND (handoff_state IS NULL "
                f"                  OR handoff_state IN ('completed', 'failed')){scope_clause}",
                (platform, session_id, *scope_params),
            )
            return cur.rowcount > 0

        return self._execute_write(_do)

    def get_handoff_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Read the current handoff state for a session."""
        logger.debug(
            "Entered into PostgresSessionStore.get_handoff_state: "
            "session_id=%r",
            session_id,
        )
        scope_clause, scope_params = self._scope_clause()
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT handoff_state, handoff_platform, handoff_error "
                    f"FROM sessions WHERE id = %s{scope_clause}",
                    (session_id, *scope_params),
                ).fetchone()
            if not row:
                return None
            return {
                "state": row["handoff_state"],
                "platform": row["handoff_platform"],
                "error": row["handoff_error"],
            }
        except Exception:
            return None

    def list_pending_handoffs(self) -> List[Dict[str, Any]]:
        """Return all sessions in handoff_state='pending', oldest first."""
        logger.debug("Entered into PostgresSessionStore.list_pending_handoffs")
        scope_clause, scope_params = self._scope_clause()
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    f"SELECT * FROM sessions "
                    f"WHERE handoff_state = 'pending'{scope_clause} "
                    f"ORDER BY started_at ASC",
                    scope_params,
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def claim_handoff(self, session_id: str) -> bool:
        """Atomically transition pending -> running. Returns True if claimed."""
        logger.debug(
            "Entered into PostgresSessionStore.claim_handoff: "
            "session_id=%r",
            session_id,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            cur = conn.execute(
                "UPDATE sessions SET handoff_state = 'running' "
                f"WHERE id = %s AND handoff_state = 'pending'{scope_clause}",
                (session_id, *scope_params),
            )
            return cur.rowcount > 0

        return self._execute_write(_do)

    def complete_handoff(self, session_id: str) -> None:
        """Mark a handoff as completed."""
        logger.debug(
            "Entered into PostgresSessionStore.complete_handoff: "
            "session_id=%r",
            session_id,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            conn.execute(
                "UPDATE sessions SET handoff_state = 'completed', "
                f"handoff_error = NULL WHERE id = %s{scope_clause}",
                (session_id, *scope_params),
            )

        self._execute_write(_do)

    def fail_handoff(self, session_id: str, error: str) -> None:
        """Mark a handoff as failed and record the reason."""
        logger.debug(
            "Entered into PostgresSessionStore.fail_handoff: "
            "session_id=%r",
            session_id,
        )

        def _do(conn):
            scope_clause, scope_params = self._scope_clause()
            conn.execute(
                "UPDATE sessions SET handoff_state = 'failed', "
                f"handoff_error = %s WHERE id = %s{scope_clause}",
                (error[:500], session_id, *scope_params),
            )

        self._execute_write(_do)
