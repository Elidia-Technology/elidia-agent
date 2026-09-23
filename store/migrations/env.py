"""Alembic environment for the pooled-runtime Postgres session store.

There is no ORM here — the store speaks raw SQL (psycopg3) end-to-end, so
``target_metadata`` is ``None`` and migrations are hand-written ``op.execute``
DDL. This keeps the store path free of a second query layer and makes the
DDL in ``versions/`` the single source of truth for the Postgres schema.

URL resolution order (documented in alembic.ini):
  1. ``alembic -x db_url=postgresql://...`` command-line override,
  2. ``ELIDIA_POSTGRES_DSN`` environment variable,
  3. ``sqlalchemy.url`` in alembic.ini (empty by default).
"""

import os

from alembic import context
from logging.config import fileConfig
from sqlalchemy import create_engine, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM metadata to autogenerate against.
target_metadata = None


def _resolve_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    url = x_args.get("db_url")
    if url:
        return url
    url = os.environ.get("ELIDIA_POSTGRES_DSN")
    if url:
        return url
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "No database URL: pass -x db_url=... or set ELIDIA_POSTGRES_DSN"
        )
    return url


def _sqlalchemy_url() -> str:
    """Return the resolved URL in SQLAlchemy's ``postgresql+psycopg`` dialect.

    The store itself (``PostgresSessionStore``) consumes ``ELIDIA_POSTGRES_DSN``
    as a psycopg3 conninfo URI (``postgresql://…``). SQLAlchemy needs the driver
    spelled out (``postgresql+psycopg://…``) or it falls back to the uninstalled
    psycopg2. Normalising here lets one DSN serve both callers.
    """
    url = _resolve_url()
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without connecting)."""
    context.configure(
        url=_sqlalchemy_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to the DB)."""
    connectable = create_engine(_sqlalchemy_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
