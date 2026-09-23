"""Storage abstractions for the Elidia Agent v2 pooled runtime (AIUT-3078).

Phase A (this increment) is a zero-behavior-change structural layer:

- :class:`store.base.StoreBackend` — backend discriminator enum.
- :class:`store.base.SessionStore` — ``typing.Protocol`` declaring the full
  public method surface of ``elidia_state.SessionDB`` plus the two
  pooled-runtime additions (``close`` / ``set_scope``).
- Standalone :func:`store.base.encode_content` /
  :func:`store.base.decode_content` / :func:`store.base.sanitize_title` —
  verbatim copies of the sentinel/title logic in ``elidia_state.SessionDB``
  so the future Postgres store reuses exactly the same serialisation.

No behavior in ``elidia_state.py`` changes while ``user_id`` is unset.

Phase A3 adds:

- :func:`store.factory.create_session_store` — backend-aware factory that
  returns ``SessionDB`` (SQLite) or ``PostgresSessionStore`` (Postgres)
  based on ``ELIDIA_STORE_BACKEND`` / explicit parameter.
- :func:`store.factory.close_shared_pool` — shutdown hook for the shared
  Postgres connection pool (no-op when SQLite is in use).
"""
