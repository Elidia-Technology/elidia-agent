"""Increment A1 (AIUT-3078) — store/base.py structural contracts + helpers.

The helpers must be behavior-identical to the SessionDB methods they copy
verbatim, and the ``SessionStore`` Protocol must be satisfied structurally
by ``SessionDB`` (with the two pooled-runtime additions present).
"""
import pytest

from elidia_state import SessionDB
from store.base import (
    MAX_TITLE_LENGTH,
    StoreBackend,
    SessionStore,
    decode_content,
    encode_content,
    sanitize_title,
)


class TestStoreBackend:
    def test_enum_values(self):
        assert StoreBackend.SQLITE.value == "sqlite"
        assert StoreBackend.POSTGRES.value == "postgres"


class TestContentEncodeDecode:
    """encode_content/decode_content must match SessionDB verbatim."""

    @pytest.mark.parametrize("value", [
        None,
        "plain string",
        42,
        3.14,
        b"bytes",
        ["a", {"b": 1}],
        {"type": "image_url", "image_url": {"url": "x"}},
    ])
    def test_matches_sessiondb(self, value):
        assert encode_content(value) == SessionDB._encode_content(value)
        encoded = encode_content(value)
        assert decode_content(encoded) == SessionDB._decode_content(encoded)

    def test_scalars_pass_through_unchanged(self):
        assert encode_content("hi") == "hi"
        assert encode_content(42) == 42
        assert encode_content(None) is None

    def test_structured_roundtrip(self):
        payload = [{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": "u"}}]
        assert decode_content(encode_content(payload)) == payload

    def test_undecodable_sentinel_returns_raw_string(self):
        # \x00json: followed by invalid JSON must fall back to the raw string.
        raw = "\x00json:{not json"
        assert decode_content(raw) == raw


class TestSanitizeTitle:
    def test_matches_sessiondb(self):
        for title in [None, "", "   ", "  hello world  ", "a\t\n b", "ctrl\x00\x1fchar"]:
            assert sanitize_title(title) == SessionDB.sanitize_title(title)

    def test_removes_unicode_control_chars(self):
        # zero-width space, RTL override, word joiner, BOM
        dirty = "ab​cd‮e⁠f﻿g"
        assert sanitize_title(dirty) == "abcdefg"
        assert sanitize_title(dirty) == SessionDB.sanitize_title(dirty)

    def test_too_long_raises(self):
        with pytest.raises(ValueError):
            sanitize_title("a" * (MAX_TITLE_LENGTH + 1))
        with pytest.raises(ValueError):
            SessionDB.sanitize_title("a" * (MAX_TITLE_LENGTH + 1))

    def test_exactly_max_length_ok(self):
        assert sanitize_title("a" * MAX_TITLE_LENGTH) == "a" * MAX_TITLE_LENGTH


class TestSessionStoreProtocol:
    """SessionDB must satisfy the full SessionStore Protocol structurally."""

    def test_sessiondb_exposes_every_protocol_member(self):
        missing = [
            name
            for name in dir(SessionStore)
            if not name.startswith("_") and not hasattr(SessionDB, name)
        ]
        assert missing == []

    def test_pooled_runtime_additions_present(self):
        assert callable(SessionDB.close)
        assert callable(SessionDB.set_scope)
        assert callable(SessionDB._scope_clause)

    def test_protocol_has_set_scope_and_close(self):
        assert hasattr(SessionStore, "set_scope")
        assert hasattr(SessionStore, "close")
