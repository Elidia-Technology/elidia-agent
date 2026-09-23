"""Increment A1 (AIUT-3078) — SessionDB tenant scoping.

Proves three things:

1. **Zero behavior change** when ``user_id=None`` (the default): full
   create / get / append / list / delete round-trips behave exactly as
   before — unscoped stores still see every row, including rows that were
   created with an explicit ``user_id``.
2. **Scoping**: a store scoped to ``user_id="A"`` and a store scoped to
   ``user_id="B"`` sharing one DB file are isolated — B cannot get,
   read, append to, retitle, count, list, or delete A's sessions, while A
   still sees them intact.
3. **``set_scope(None)``** clears the filter back to unscoped behavior.
"""
import pytest

from elidia_state import SessionDB


@pytest.fixture
def db(tmp_path):
    store = SessionDB(tmp_path / "state.db")
    yield store
    store.close()


class TestUnscopedZeroBehaviorChange:
    """user_id=None must keep every existing behavior byte-identical."""

    def test_create_get_append_list_delete_roundtrip(self, db):
        db.create_session("s1", source="cli", user_id="legacy-user")
        assert db.get_session("s1")["id"] == "s1"

        mid = db.append_message("s1", role="user", content="hello")
        assert isinstance(mid, int)
        msgs = db.get_messages("s1")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hello"

        assert db.session_count() == 1
        assert [s["id"] for s in db.list_sessions_rich()] == ["s1"]
        assert db.message_count("s1") == 1
        assert db.message_count() == 1

        assert db.delete_session("s1") is True
        assert db.get_session("s1") is None
        assert db.session_count() == 0

    def test_unscoped_sees_sessions_tagged_with_user_id(self, db):
        # The default (user_id=None) applies no filter: rows created with an
        # explicit user_id remain visible exactly as they were pre-scope.
        db.create_session("a", source="cli", user_id="u1")
        db.create_session("b", source="cli", user_id="u2")
        assert db.session_count() == 2
        assert {s["id"] for s in db.list_sessions_rich()} == {"a", "b"}
        assert db.get_session("a")["user_id"] == "u1"
        assert db.message_count() == 0


class TestScopedIsolation:
    """Two stores, same file, different user_id — full tenant isolation."""

    def test_tenant_cannot_touch_foreign_session(self, tmp_path):
        path = tmp_path / "state.db"
        db_a = SessionDB(path, user_id="A")
        db_b = SessionDB(path, user_id="B")
        try:
            db_a.create_session("s1", source="cli")
            db_a.append_message("s1", role="user", content="msg A")
            db_a.set_session_title("s1", "A's title")

            # B cannot see the session at all.
            assert db_b.get_session("s1") is None
            assert db_b.get_session_title("s1") is None
            assert db_b.get_session_by_title("A's title") is None
            assert db_b.resolve_session_id("s1") is None
            assert db_b.get_messages("s1") == []
            assert db_b.get_messages_as_conversation("s1") == []
            assert db_b.message_count("s1") == 0
            assert db_b.list_sessions_rich() == []
            assert db_b.session_count() == 0

            # B cannot mutate the session.
            assert db_b.set_session_title("s1", "hijacked") is False
            assert db_b.append_message("s1", role="user", content="intruder") == 0
            assert db_b.message_count("s1") == 0
            db_b.clear_messages("s1")
            assert len(db_a.get_messages("s1")) == 1, "A's messages must survive B's clear_messages"
            assert db_b.delete_session("s1") is False
            db_b.delete_sessions(["s1"])
            db_b.end_session("s1", "bogus")
            db_b.reopen_session("s1")
            db_b.update_token_counts("s1", input_tokens=99)

            # A still sees everything intact.
            row_a = db_a.get_session("s1")
            assert row_a is not None and row_a["user_id"] == "A"
            assert [m["content"] for m in db_a.get_messages("s1")] == ["msg A"]
            assert db_a.get_session_title("s1") == "A's title"
            assert db_a.session_count() == 1
            assert [s["id"] for s in db_a.list_sessions_rich()] == ["s1"]
        finally:
            db_a.close()
            db_b.close()

    def test_scoped_create_tags_owner_user_id(self, tmp_path):
        db_a = SessionDB(tmp_path / "state.db", user_id="A")
        try:
            db_a.create_session("s1", source="cli")
            assert db_a.get_session("s1")["user_id"] == "A"
            # ensure_session (the INSERT OR IGNORE path) tags too.
            db_a.ensure_session("s2", source="cli")
            assert db_a.get_session("s2")["user_id"] == "A"
        finally:
            db_a.close()

    def test_scoped_rich_listing_with_order_by_last_active(self, tmp_path):
        path = tmp_path / "state.db"
        db_a = SessionDB(path, user_id="A")
        db_b = SessionDB(path, user_id="B")
        try:
            db_a.create_session("sa", source="cli")
            db_a.append_message("sa", role="user", content="hello a")
            db_a.set_session_title("sa", "title a")
            db_b.create_session("sb", source="cli")
            db_b.append_message("sb", role="user", content="hello b")
            # order_by_last_active runs a recursive CTE that embeds the
            # where-clauses twice — the scope param must stay in order.
            assert [s["id"] for s in db_a.list_sessions_rich(order_by_last_active=True)] == ["sa"]
            assert [s["id"] for s in db_b.list_sessions_rich(order_by_last_active=True)] == ["sb"]
            assert db_a.get_session_title("sa") == "title a"
        finally:
            db_a.close()
            db_b.close()

    def test_scoped_compression_lock_is_isolated(self, tmp_path):
        path = tmp_path / "state.db"
        db_a = SessionDB(path, user_id="A")
        db_b = SessionDB(path, user_id="B")
        try:
            db_a.create_session("s1", source="cli")
            # A acquires the lock for its own session.
            assert db_a.try_acquire_compression_lock("s1", holder="a") is True
            # B cannot see or mutate that lock.
            assert db_b.try_acquire_compression_lock("s1", holder="b") is False
            assert db_b.get_compression_lock_holder("s1") is None
            db_b.release_compression_lock("s1", holder="b")  # no-op, must not release A's lock
            assert db_a.get_compression_lock_holder("s1") == "a"
            db_a.release_compression_lock("s1", holder="a")
            assert db_a.get_compression_lock_holder("s1") is None
        finally:
            db_a.close()
            db_b.close()

    def test_scoped_message_count_filters_by_owner(self, tmp_path):
        path = tmp_path / "state.db"
        db_a = SessionDB(path, user_id="A")
        db_b = SessionDB(path, user_id="B")
        try:
            db_a.create_session("s1", source="cli")
            db_a.append_message("s1", role="user", content="a1")
            db_b.create_session("s2", source="cli")
            db_b.append_message("s2", role="user", content="b1")
            # Global scoped counts see only the tenant's own messages.
            assert db_a.message_count() == 1
            assert db_b.message_count() == 1
            assert db_b.message_count("s1") == 0
            assert db_b.session_count() == 1
        finally:
            db_a.close()
            db_b.close()


class TestSetScope:
    """set_scope(None) clears the filter; set_scope(user) switches tenants."""

    def test_set_scope_none_clears_filter(self, tmp_path):
        db = SessionDB(tmp_path / "state.db", user_id="A")
        try:
            db.create_session("s1", source="cli")
            assert db.session_count() == 1
            assert db.get_session("s1") is not None

            db.set_scope(None)
            # Back to unscoped: same session visible, new sessions untagged.
            assert db.session_count() == 1
            assert db.get_session("s1") is not None
            db.create_session("s2", source="cli")
            assert db.session_count() == 2
            assert db.get_session("s2")["user_id"] is None
        finally:
            db.close()

    def test_set_scope_switch_tenant(self, tmp_path):
        db = SessionDB(tmp_path / "state.db")
        try:
            db.set_scope("A")
            db.create_session("sa", source="cli")
            db.set_scope("B")
            db.create_session("sb", source="cli")
            assert db.session_count() == 1
            assert [s["id"] for s in db.list_sessions_rich()] == ["sb"]
            assert db.get_session("sa") is None
            db.set_scope(None)
            assert db.session_count() == 2
        finally:
            db.close()
