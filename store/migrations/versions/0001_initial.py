"""Initial Postgres schema for the pooled-runtime session store.

Revision ID: 0001
Revises:
Create Date: 2026-08-28

Faithful port of ``elidia_state.SessionDB``'s SQLite schema (SCHEMA_SQL +
DEFERRED_INDEX_SQL + FTS_SQL + FTS_TRIGRAM_SQL) to Postgres. Mapping notes:

- SQLite ``INTEGER`` (64-bit) -> Postgres ``BIGINT``; boolean flags (``archived``,
  ``active``, ``observed``) -> ``SMALLINT``.
- SQLite ``REAL`` (8-byte double) -> ``DOUBLE PRECISION`` (``REAL`` in Postgres
  is only 4 bytes and would lose ``time.time()`` precision).
- ``messages.id INTEGER PRIMARY KEY AUTOINCREMENT`` -> ``BIGSERIAL``.
- FTS5 inline index (content || tool_name || tool_calls) -> a ``STORED``
  generated ``tsvector`` column + GIN index; the ``'simple'`` config (no
  stopwords, no stemming, lowercase) is the closest match to unicode61's
  default.
- FTS5 trigram tokenizer (CJK substring) -> ``pg_trgm`` GIN index on the same
  concatenation, accelerated via ``LIKE '%…%'``.
- The telegram DM topic-mode tables are deliberately NOT here — like SQLite,
  they are opt-in via ``apply_telegram_topic_migration()``.
- SQLite's ``schema_version`` + declarative column reconciliation is replaced
  by Alembic's own ``alembic_version`` bookkeeping; there is no ORM.

``pg_trgm`` is created by this migration and therefore requires the migration
role to hold CREATE on the target database (typically a superuser or a role
with the extension pre-installed by the DBA).
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SESSIONS = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    parent_session_id TEXT REFERENCES sessions(id),
    started_at DOUBLE PRECISION NOT NULL,
    ended_at DOUBLE PRECISION,
    end_reason TEXT,
    message_count BIGINT DEFAULT 0,
    tool_call_count BIGINT DEFAULT 0,
    input_tokens BIGINT DEFAULT 0,
    output_tokens BIGINT DEFAULT 0,
    cache_read_tokens BIGINT DEFAULT 0,
    cache_write_tokens BIGINT DEFAULT 0,
    reasoning_tokens BIGINT DEFAULT 0,
    cwd TEXT,
    billing_provider TEXT,
    billing_base_url TEXT,
    billing_mode TEXT,
    estimated_cost_usd DOUBLE PRECISION,
    actual_cost_usd DOUBLE PRECISION,
    cost_status TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,
    api_call_count BIGINT DEFAULT 0,
    handoff_state TEXT,
    handoff_platform TEXT,
    handoff_error TEXT,
    rewind_count BIGINT NOT NULL DEFAULT 0,
    archived SMALLINT NOT NULL DEFAULT 0
)
"""

_MESSAGES = """
CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp DOUBLE PRECISION NOT NULL,
    token_count BIGINT,
    finish_reason TEXT,
    reasoning TEXT,
    reasoning_content TEXT,
    reasoning_details TEXT,
    codex_reasoning_items TEXT,
    codex_message_items TEXT,
    platform_message_id TEXT,
    observed SMALLINT DEFAULT 0,
    active SMALLINT NOT NULL DEFAULT 1,
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'simple',
            COALESCE(content, '') || ' ' || COALESCE(tool_name, '') || ' ' || COALESCE(tool_calls, '')
        )
    ) STORED
)
"""

_STATE_META = """
CREATE TABLE state_meta (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""

_COMPRESSION_LOCKS = """
CREATE TABLE compression_locks (
    session_id TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    acquired_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL
)
"""

_INDEXES = [
    "CREATE INDEX idx_sessions_source ON sessions(source)",
    "CREATE INDEX idx_sessions_parent ON sessions(parent_session_id)",
    "CREATE INDEX idx_sessions_started ON sessions(started_at DESC)",
    "CREATE INDEX idx_messages_session ON messages(session_id, timestamp)",
    "CREATE INDEX idx_compression_locks_expires ON compression_locks(expires_at)",
    "CREATE INDEX idx_messages_session_active ON messages(session_id, active, timestamp)",
    "CREATE INDEX idx_messages_platform_msg_id ON messages(session_id, platform_message_id) "
    "WHERE platform_message_id IS NOT NULL",
    "CREATE UNIQUE INDEX idx_sessions_title_unique ON sessions(title) WHERE title IS NOT NULL",
    "CREATE INDEX idx_messages_search_vector ON messages USING GIN (search_vector)",
    "CREATE INDEX idx_messages_trigram ON messages USING GIN ("
    "(COALESCE(content, '') || ' ' || COALESCE(tool_name, '') || ' ' || COALESCE(tool_calls, '')) gin_trgm_ops"
    ")",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(_SESSIONS)
    op.execute(_MESSAGES)
    op.execute(_STATE_META)
    op.execute(_COMPRESSION_LOCKS)
    for ddl in _INDEXES:
        op.execute(ddl)


def downgrade() -> None:
    # Reverse order: indexes then tables.
    op.execute("DROP INDEX IF EXISTS idx_messages_trigram")
    op.execute("DROP INDEX IF EXISTS idx_messages_search_vector")
    op.execute("DROP INDEX IF EXISTS idx_sessions_title_unique")
    op.execute("DROP INDEX IF EXISTS idx_messages_platform_msg_id")
    op.execute("DROP INDEX IF EXISTS idx_messages_session_active")
    op.execute("DROP INDEX IF EXISTS idx_compression_locks_expires")
    op.execute("DROP INDEX IF EXISTS idx_messages_session")
    op.execute("DROP INDEX IF EXISTS idx_sessions_started")
    op.execute("DROP INDEX IF EXISTS idx_sessions_parent")
    op.execute("DROP INDEX IF EXISTS idx_sessions_source")
    op.execute("DROP TABLE IF EXISTS compression_locks")
    op.execute("DROP TABLE IF EXISTS state_meta")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS sessions")
    # Leave pg_trgm installed — other databases/tables may use it; dropping a
    # shared extension on downgrade is more destructive than the migration
    # itself warrants.
