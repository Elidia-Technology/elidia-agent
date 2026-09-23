"""Shared test fixtures for the store package.

Provides a ``pg_store`` fixture that yields a ``PostgresSessionStore``
connected to a freshly-wiped ``elidia_agent_v2_test`` database on the local
Postgres (127.0.0.1:5432, user ``mac``, trust auth). The fixture truncates
all tables between tests so each test starts with a clean slate.

Tests that need Postgres are marked ``@pytest.mark.postgres`` and skipped
when the database is not reachable.
"""

import os

import pytest

_PG_DSN = os.environ.get(
    "ELIDIA_POSTGRES_TEST_DSN",
    "postgresql://mac@127.0.0.1:5432/elidia_agent_v2_test",
)


def _pg_available() -> bool:
    try:
        import psycopg  # noqa: F401
        conn = psycopg.connect(_PG_DSN, autocommit=True)
        conn.execute("SELECT 1")
        conn.close()
        return True
    except Exception:
        return False


_pg_ok = _pg_available()

postgres = pytest.mark.skipif(not _pg_ok, reason="Postgres test DB not reachable")


@pytest.fixture
def pg_store():
    """Yield a PostgresSessionStore connected to the test database.

    Truncates all store tables before yielding so each test starts clean.
    Closes the store (and its pool) on teardown.
    """
    pytest.importorskip("psycopg")
    if not _pg_ok:
        pytest.skip("Postgres test DB not reachable")

    from store.postgres import PostgresSessionStore

    store = PostgresSessionStore(_PG_DSN, min_size=1, max_size=4)
    # Wipe data from prior tests (TRUNCATE CASCADE handles FK deps).
    import psycopg
    with psycopg.connect(_PG_DSN, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE TABLE messages, sessions, compression_locks, state_meta CASCADE"
        )
        # Also drop the opt-in telegram tables if they exist.
        conn.execute("DROP TABLE IF EXISTS telegram_dm_topic_bindings CASCADE")
        conn.execute("DROP TABLE IF EXISTS telegram_dm_topic_mode CASCADE")
    yield store
    store.close()


@pytest.fixture
def pg_store_scoped(request):
    """Yield a PostgresSessionStore scoped to a given user_id.

    Usage: ``@pytest.mark.parametrize('pg_store_scoped', ['user-A'], indirect=True)``
    or call the factory directly via ``pg_store_factory``.
    """
    pytest.importorskip("psycopg")
    if not _pg_ok:
        pytest.skip("Postgres test DB not reachable")

    from store.postgres import PostgresSessionStore

    user_id = getattr(request, "param", None)
    store = PostgresSessionStore(_PG_DSN, min_size=1, max_size=4, user_id=user_id)
    yield store
    store.close()


@pytest.fixture
def pg_store_factory():
    """Factory fixture that creates PostgresSessionStore instances.

    Returns a callable ``make(user_id=None)`` that returns a new store.
    All stores created are closed on teardown.
    """
    pytest.importorskip("psycopg")
    if not _pg_ok:
        pytest.skip("Postgres test DB not reachable")

    from store.postgres import PostgresSessionStore

    stores = []

    def _make(user_id=None):
        s = PostgresSessionStore(_PG_DSN, min_size=1, max_size=4, user_id=user_id)
        stores.append(s)
        return s

    # Wipe data before yielding the factory.
    import psycopg
    with psycopg.connect(_PG_DSN, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE TABLE messages, sessions, compression_locks, state_meta CASCADE"
        )
        conn.execute("DROP TABLE IF EXISTS telegram_dm_topic_bindings CASCADE")
        conn.execute("DROP TABLE IF EXISTS telegram_dm_topic_mode CASCADE")

    yield _make

    for s in stores:
        try:
            s.close()
        except Exception:
            pass
