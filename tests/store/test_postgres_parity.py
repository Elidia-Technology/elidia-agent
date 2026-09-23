"""Parity tests: PostgresSessionStore vs SessionDB (SQLite).

Each test exercises a core store operation against the Postgres backend and
verifies the result matches the contract established by the SQLite tests in
``test_session_scope.py`` and ``test_base.py``. This is NOT a differential
oracle (we don't run both backends and diff outputs); rather, each test
asserts the same invariants the SQLite tests do, proving the Postgres
implementation is behavior-compatible.

All tests require a local Postgres (``elidia_agent_v2_test`` on 5432) and
are skipped when the DB is not reachable.
"""

import time

import pytest

from tests.store.conftest import postgres


# ═══════════════════════════════════════════════════════════════════════════
# Session lifecycle
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestSessionLifecycle:

    def test_create_get_roundtrip(self, pg_store):
        sid = pg_store.create_session("s1", source="cli", model="gpt-4")
        assert sid == "s1"
        row = pg_store.get_session("s1")
        assert row is not None
        assert row["id"] == "s1"
        assert row["source"] == "cli"
        assert row["model"] == "gpt-4"
        assert row["message_count"] == 0

    def test_ensure_session_idempotent(self, pg_store):
        pg_store.ensure_session("s1", source="cli", model="gpt-4")
        pg_store.ensure_session("s1", source="cli", model="gpt-4o")
        row = pg_store.get_session("s1")
        assert row is not None
        assert row["model"] == "gpt-4"

    def test_end_and_reopen(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.end_session("s1", "user_quit")
        row = pg_store.get_session("s1")
        assert row["ended_at"] is not None
        assert row["end_reason"] == "user_quit"
        pg_store.reopen_session("s1")
        row = pg_store.get_session("s1")
        assert row["ended_at"] is None
        assert row["end_reason"] is None

    def test_update_session_cwd(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.update_session_cwd("s1", "/home/user/project")
        assert pg_store.get_session("s1")["cwd"] == "/home/user/project"

    def test_update_system_prompt(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.update_system_prompt("s1", "You are a helpful assistant.")
        assert pg_store.get_session("s1")["system_prompt"] == "You are a helpful assistant."

    def test_update_session_model(self, pg_store):
        pg_store.create_session("s1", source="cli", model="gpt-3.5")
        pg_store.update_session_model("s1", "gpt-4o")
        assert pg_store.get_session("s1")["model"] == "gpt-4o"


# ═══════════════════════════════════════════════════════════════════════════
# Token counts
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestTokenCounts:

    def test_incremental_token_update(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.update_token_counts("s1", input_tokens=100, output_tokens=50)
        pg_store.update_token_counts("s1", input_tokens=200, output_tokens=100)
        row = pg_store.get_session("s1")
        assert row["input_tokens"] == 300
        assert row["output_tokens"] == 150

    def test_absolute_token_update(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.update_token_counts("s1", input_tokens=100, output_tokens=50)
        pg_store.update_token_counts("s1", input_tokens=500, output_tokens=250, absolute=True)
        row = pg_store.get_session("s1")
        assert row["input_tokens"] == 500
        assert row["output_tokens"] == 250


# ═══════════════════════════════════════════════════════════════════════════
# Messages
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestMessages:

    def test_append_and_get(self, pg_store):
        pg_store.create_session("s1", source="cli")
        mid = pg_store.append_message("s1", role="user", content="hello world")
        assert isinstance(mid, int) and mid > 0
        msgs = pg_store.get_messages("s1")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello world"
        assert msgs[0]["session_id"] == "s1"

    def test_multimodal_content_roundtrip(self, pg_store):
        pg_store.create_session("s1", source="cli")
        parts = [{"type": "text", "text": "describe"}, {"type": "image_url", "image_url": {"url": "data:..."}}]
        pg_store.append_message("s1", role="user", content=parts)
        msgs = pg_store.get_messages("s1")
        assert msgs[0]["content"] == parts

    def test_tool_calls_roundtrip(self, pg_store):
        pg_store.create_session("s1", source="cli")
        tc = [{"id": "tc1", "type": "function", "function": {"name": "search", "arguments": "{}"}}]
        pg_store.append_message("s1", role="assistant", tool_calls=tc)
        msgs = pg_store.get_messages("s1")
        assert msgs[0]["tool_calls"] == tc

    def test_message_count_updates_session(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.append_message("s1", role="user", content="m1")
        pg_store.append_message("s1", role="assistant", content="m2")
        row = pg_store.get_session("s1")
        assert row["message_count"] == 2

    def test_replace_messages(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.append_message("s1", role="user", content="original")
        pg_store.replace_messages("s1", [
            {"role": "user", "content": "replaced1"},
            {"role": "assistant", "content": "replaced2"},
        ])
        msgs = pg_store.get_messages("s1")
        assert len(msgs) == 2
        assert msgs[0]["content"] == "replaced1"
        row = pg_store.get_session("s1")
        assert row["message_count"] == 2

    def test_clear_messages(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.append_message("s1", role="user", content="msg")
        pg_store.clear_messages("s1")
        assert pg_store.get_messages("s1") == []
        assert pg_store.get_session("s1")["message_count"] == 0

    def test_message_count(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.create_session("s2", source="cli")
        pg_store.append_message("s1", role="user", content="a")
        pg_store.append_message("s2", role="user", content="b")
        pg_store.append_message("s2", role="user", content="c")
        assert pg_store.message_count("s1") == 1
        assert pg_store.message_count("s2") == 2
        assert pg_store.message_count() == 3


# ═══════════════════════════════════════════════════════════════════════════
# Session listing and search
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestSessionListing:

    def test_list_sessions_rich_basic(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.append_message("s1", role="user", content="hello world how are you today")
        pg_store.create_session("s2", source="telegram")
        rows = pg_store.list_sessions_rich()
        assert len(rows) == 2
        ids = {r["id"] for r in rows}
        assert ids == {"s1", "s2"}
        s1_row = next(r for r in rows if r["id"] == "s1")
        assert "hello" in s1_row.get("preview", "")

    def test_list_sessions_rich_source_filter(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.create_session("s2", source="telegram")
        rows = pg_store.list_sessions_rich(source="cli")
        assert [r["id"] for r in rows] == ["s1"]

    def test_list_sessions_rich_exclude_children(self, pg_store):
        pg_store.create_session("parent", source="cli")
        pg_store.create_session("child", source="cli", parent_session_id="parent")
        rows = pg_store.list_sessions_rich(include_children=False)
        assert [r["id"] for r in rows] == ["parent"]

    def test_search_sessions(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.create_session("s2", source="telegram")
        rows = pg_store.search_sessions(source="telegram")
        assert len(rows) == 1
        assert rows[0]["id"] == "s2"

    def test_session_count(self, pg_store):
        assert pg_store.session_count() == 0
        pg_store.create_session("s1", source="cli")
        pg_store.create_session("s2", source="cli")
        assert pg_store.session_count() == 2
        assert pg_store.session_count(source="cli") == 2


# ═══════════════════════════════════════════════════════════════════════════
# Titles
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestTitles:

    def test_set_and_get_title(self, pg_store):
        pg_store.create_session("s1", source="cli")
        assert pg_store.set_session_title("s1", "My Session") is True
        assert pg_store.get_session_title("s1") == "My Session"

    def test_title_uniqueness(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.create_session("s2", source="cli")
        pg_store.set_session_title("s1", "unique")
        with pytest.raises(ValueError, match="already in use"):
            pg_store.set_session_title("s2", "unique")

    def test_get_session_by_title(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.set_session_title("s1", "findme")
        row = pg_store.get_session_by_title("findme")
        assert row is not None and row["id"] == "s1"

    def test_resolve_session_by_title(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.set_session_title("s1", "project")
        assert pg_store.resolve_session_by_title("project") == "s1"

    def test_get_next_title_in_lineage(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.set_session_title("s1", "convo")
        assert pg_store.get_next_title_in_lineage("convo") == "convo #2"
        pg_store.create_session("s2", source="cli")
        pg_store.set_session_title("s2", "convo #2")
        assert pg_store.get_next_title_in_lineage("convo") == "convo #3"

    def test_sanitize_title_static(self, pg_store):
        assert pg_store.sanitize_title("  hello   world  ") == "hello world"
        assert pg_store.sanitize_title("") is None
        assert pg_store.sanitize_title(None) is None


# ═══════════════════════════════════════════════════════════════════════════
# Rewind
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestRewind:

    def test_rewind_and_restore(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.append_message("s1", role="user", content="q1")
        pg_store.append_message("s1", role="assistant", content="a1")
        mid3 = pg_store.append_message("s1", role="user", content="q2")
        pg_store.append_message("s1", role="assistant", content="a2")

        result = pg_store.rewind_to_message("s1", mid3)
        assert result["rewound_count"] == 2
        assert result["target_message"]["content"] == "q2"
        msgs = pg_store.get_messages("s1")
        assert len(msgs) == 2

        restored = pg_store.restore_rewound("s1", mid3)
        assert restored == 2
        msgs = pg_store.get_messages("s1", include_inactive=True)
        assert len(msgs) == 4


# ═══════════════════════════════════════════════════════════════════════════
# Compression locks
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestCompressionLocks:

    def test_acquire_release_cycle(self, pg_store):
        pg_store.create_session("s1", source="cli")
        assert pg_store.try_acquire_compression_lock("s1", "holder-A") is True
        assert pg_store.get_compression_lock_holder("s1") == "holder-A"
        assert pg_store.try_acquire_compression_lock("s1", "holder-B") is False
        pg_store.release_compression_lock("s1", "holder-A")
        assert pg_store.get_compression_lock_holder("s1") is None

    def test_expired_lock_reclaimed(self, pg_store):
        pg_store.create_session("s1", source="cli")
        assert pg_store.try_acquire_compression_lock("s1", "old", ttl_seconds=0.0) is True
        time.sleep(0.01)
        assert pg_store.try_acquire_compression_lock("s1", "new") is True
        assert pg_store.get_compression_lock_holder("s1") == "new"


# ═══════════════════════════════════════════════════════════════════════════
# Meta
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestMeta:

    def test_get_set_meta(self, pg_store):
        assert pg_store.get_meta("k") is None
        pg_store.set_meta("k", "v1")
        assert pg_store.get_meta("k") == "v1"
        pg_store.set_meta("k", "v2")
        assert pg_store.get_meta("k") == "v2"


# ═══════════════════════════════════════════════════════════════════════════
# Delete
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestDelete:

    def test_delete_session(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.append_message("s1", role="user", content="msg")
        assert pg_store.delete_session("s1") is True
        assert pg_store.get_session("s1") is None
        assert pg_store.delete_session("s1") is False

    def test_delete_sessions_bulk(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.create_session("s2", source="cli")
        pg_store.create_session("s3", source="cli")
        count = pg_store.delete_sessions(["s1", "s2", "nonexistent"])
        assert count == 2
        assert pg_store.session_count() == 1

    def test_delete_orphans_children(self, pg_store):
        pg_store.create_session("parent", source="cli")
        pg_store.create_session("child", source="cli", parent_session_id="parent")
        pg_store.delete_session("parent")
        child = pg_store.get_session("child")
        assert child is not None
        assert child["parent_session_id"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Scoping (tenant isolation on Postgres)
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestScopedIsolationPostgres:

    def test_tenant_cannot_touch_foreign_session(self, pg_store_factory):
        db_a = pg_store_factory(user_id="A")
        db_b = pg_store_factory(user_id="B")

        db_a.create_session("s1", source="cli")
        db_a.append_message("s1", role="user", content="msg A")
        db_a.set_session_title("s1", "A's title")

        assert db_b.get_session("s1") is None
        assert db_b.get_session_title("s1") is None
        assert db_b.get_session_by_title("A's title") is None
        assert db_b.get_messages("s1") == []
        assert db_b.message_count("s1") == 0
        assert db_b.list_sessions_rich() == []
        assert db_b.session_count() == 0

        assert db_b.set_session_title("s1", "hijacked") is False
        assert db_b.append_message("s1", role="user", content="intruder") == 0
        assert db_b.delete_session("s1") is False

        row_a = db_a.get_session("s1")
        assert row_a is not None and row_a["user_id"] == "A"
        assert [m["content"] for m in db_a.get_messages("s1")] == ["msg A"]

    def test_scoped_create_tags_owner(self, pg_store_factory):
        db_a = pg_store_factory(user_id="A")
        db_a.create_session("s1", source="cli")
        assert db_a.get_session("s1")["user_id"] == "A"
        db_a.ensure_session("s2", source="cli")
        assert db_a.get_session("s2")["user_id"] == "A"

    def test_set_scope_switch_tenant(self, pg_store_factory):
        db = pg_store_factory()
        db.set_scope("A")
        db.create_session("sa", source="cli")
        db.set_scope("B")
        db.create_session("sb", source="cli")
        assert db.session_count() == 1
        assert db.get_session("sa") is None
        db.set_scope(None)
        assert db.session_count() == 2

    def test_scoped_compression_lock_isolated(self, pg_store_factory):
        db_a = pg_store_factory(user_id="A")
        db_b = pg_store_factory(user_id="B")
        db_a.create_session("s1", source="cli")
        assert db_a.try_acquire_compression_lock("s1", "a") is True
        assert db_b.try_acquire_compression_lock("s1", "b") is False
        assert db_b.get_compression_lock_holder("s1") is None
        assert db_a.get_compression_lock_holder("s1") == "a"


# ═══════════════════════════════════════════════════════════════════════════
# FTS (tsvector search on Postgres)
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestFullTextSearch:

    def test_search_messages_basic(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.append_message("s1", role="user", content="kubernetes deployment strategy")
        pg_store.append_message("s1", role="assistant", content="use rolling updates")
        pg_store.create_session("s2", source="cli")
        pg_store.append_message("s2", role="user", content="python web framework comparison")

        results = pg_store.search_messages("kubernetes")
        assert len(results) >= 1
        assert any("kubernetes" in r.get("snippet", "").lower() for r in results)

    def test_search_messages_empty_query(self, pg_store):
        assert pg_store.search_messages("") == []
        assert pg_store.search_messages("   ") == []

    def test_search_messages_source_filter(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.append_message("s1", role="user", content="docker compose setup")
        pg_store.create_session("s2", source="telegram")
        pg_store.append_message("s2", role="user", content="docker swarm cluster")

        results = pg_store.search_messages("docker", source_filter=["cli"])
        assert all(r.get("source") == "cli" for r in results)


# ═══════════════════════════════════════════════════════════════════════════
# Handoff
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestHandoff:

    def test_handoff_lifecycle(self, pg_store):
        pg_store.create_session("s1", source="cli")
        assert pg_store.request_handoff("s1", "telegram") is True
        state = pg_store.get_handoff_state("s1")
        assert state["state"] == "pending"
        assert state["platform"] == "telegram"

        pending = pg_store.list_pending_handoffs()
        assert len(pending) == 1

        assert pg_store.claim_handoff("s1") is True
        assert pg_store.get_handoff_state("s1")["state"] == "running"

        pg_store.complete_handoff("s1")
        assert pg_store.get_handoff_state("s1")["state"] == "completed"

    def test_handoff_fail(self, pg_store):
        pg_store.create_session("s1", source="cli")
        pg_store.request_handoff("s1", "discord")
        pg_store.claim_handoff("s1")
        pg_store.fail_handoff("s1", "connection lost")
        state = pg_store.get_handoff_state("s1")
        assert state["state"] == "failed"
        assert state["error"] == "connection lost"


# ═══════════════════════════════════════════════════════════════════════════
# Archive
# ═══════════════════════════════════════════════════════════════════════════

@postgres
class TestArchive:

    def test_archive_unarchive(self, pg_store):
        pg_store.create_session("s1", source="cli")
        assert pg_store.set_session_archived("s1", True) is True
        assert pg_store.list_sessions_rich() == []
        assert pg_store.list_sessions_rich(archived_only=True)[0]["id"] == "s1"
        assert pg_store.set_session_archived("s1", False) is True
        assert len(pg_store.list_sessions_rich()) == 1
