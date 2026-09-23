"""Structural store contracts for the Elidia Agent v2 pooled runtime.

This module is the shared seam between the current single-process
``elidia_state.SessionDB`` (SQLite) and the future Postgres-backed store.
It carries NO behavior of its own beyond verbatim copies of
``SessionDB``'s content serialisation + title sanitisation so both
backends serialize payloads identically.

The two member functions that differ from ``SessionDB``'s current surface:

- ``close()`` — already implemented by ``SessionDB``; declared here so the
  contract is explicit.
- ``set_scope(user_id)`` — added by this increment. A worker process
  serving many tenants calls this once per tenant switch so every
  subsequent accessor is filtered by ``sessions.user_id``. Passing
  ``None`` clears the filter (the default, unscoped behaviour).
"""

import json
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Protocol

logger = logging.getLogger(__name__)


class StoreBackend(Enum):
    """Discriminates which storage engine a ``SessionStore`` speaks to."""

    SQLITE = "sqlite"
    POSTGRES = "postgres"


# Sentinel prefix used to distinguish JSON-encoded structured content
# (multimodal messages: lists of parts like text + image_url) from plain
# string content. The NUL byte is not legal in normal text, so this
# cannot collide with real user content. Mirrors
# ``SessionDB._CONTENT_JSON_PREFIX`` verbatim.
_CONTENT_JSON_PREFIX = "\x00json:"


def encode_content(value: Any) -> Any:
    """Serialize structured (list/dict) message content for a SQL store.

    Verbatim copy of ``SessionDB._encode_content``: sqlite3 can only bind
    ``str``, ``bytes``, ``int``, ``float``, and ``None`` to query
    parameters, so structured multimodal ``content`` (a list of parts)
    is serialized with a sentinel-prefixed JSON string.  Scalars pass
    through unchanged — hence the return type is ``Any``, not ``str``.
    """
    if value is None or isinstance(value, (str, bytes, int, float)):
        return value
    try:
        return _CONTENT_JSON_PREFIX + json.dumps(value)
    except (TypeError, ValueError):
        # Last-resort fallback: stringify so persistence never fails.
        return str(value)


def decode_content(content: Any) -> Any:
    """Reverse :func:`encode_content`; returns scalars unchanged.

    Verbatim copy of ``SessionDB._decode_content``.
    """
    if isinstance(content, str) and content.startswith(_CONTENT_JSON_PREFIX):
        try:
            return json.loads(content[len(_CONTENT_JSON_PREFIX):])
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Failed to decode JSON-encoded message content; "
                "returning raw string"
            )
            return content
    return content


# Maximum length for session titles. Mirrors ``SessionDB.MAX_TITLE_LENGTH``.
MAX_TITLE_LENGTH = 100

# Matches the Unicode control-character class removed by
# ``SessionDB.sanitize_title`` (zero-width chars U+200B-U+200F + U+FEFF,
# line/paragraph separators + directional overrides U+2028-U+202E and
# U+2066-U+2069, object replacement U+FFFC, interlinear annotations
# U+FFF9-U+FFFB). Built from explicit code points so the pattern survives
# source transport without the ``\uXXXX`` escapes being resolved to raw
# control characters.
_CONTROL_CHARS = re.compile(
    "[" + "".join(
        chr(cp)
        for cp in (
            *range(0x200B, 0x200F + 1),
            *range(0x2028, 0x202E + 1),
            *range(0x2060, 0x2069 + 1),
            0xFEFF,
            0xFFFC,
            *range(0xFFF9, 0xFFFB + 1),
        )
    ) + "]"
)


def sanitize_title(title: Optional[str]) -> Optional[str]:
    """Validate and sanitize a session title.

    Verbatim copy of ``SessionDB.sanitize_title``:

    - Strips leading/trailing whitespace
    - Removes ASCII control characters (0x00-0x1F, 0x7F) and problematic
      Unicode control chars (zero-width, RTL/LTR overrides, etc.)
    - Collapses internal whitespace runs to single spaces
    - Normalizes empty/whitespace-only strings to None
    - Enforces ``MAX_TITLE_LENGTH``

    Returns the cleaned title string or None.
    Raises ValueError if the title exceeds ``MAX_TITLE_LENGTH`` after cleaning.
    """
    if not title:
        return None

    # Remove ASCII control characters (0x00-0x1F, 0x7F) but keep
    # whitespace chars (\t=0x09, \n=0x0A, \r=0x0D) so they can be
    # normalized to spaces by the whitespace collapsing step below
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', title)

    # Remove the Unicode control characters (zero-width, directional
    # overrides, object replacement, interlinear annotations).
    cleaned = _CONTROL_CHARS.sub('', cleaned)

    # Collapse internal whitespace runs and strip
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if not cleaned:
        return None

    if len(cleaned) > MAX_TITLE_LENGTH:
        raise ValueError(
            f"Title too long ({len(cleaned)} chars, max {MAX_TITLE_LENGTH})"
        )

    return cleaned


class SessionStore(Protocol):
    """Structural contract for the Elidia session storage backend.

    Declares the full public method surface of ``elidia_state.SessionDB``
    (signatures copied verbatim from source) plus the two pooled-runtime
    additions: :meth:`close` and :meth:`set_scope`.

    A worker process serving many tenants instantiates one store, calls
    ``set_scope(user_id)`` per tenant switch, and every accessor is then
    filtered by ``sessions.user_id``.  ``set_scope(None)`` clears the
    filter — identical to today's unscoped behaviour.
    """

    # ── Pooled-runtime additions ──
    def close(self) -> None:
        """Close the underlying connection (PASSIVE checkpoint first)."""
        ...

    def set_scope(self, user_id: str | None) -> None:
        """Set the tenant ``user_id`` that scopes every accessor (None = unscoped)."""
        ...

    # ── Session lifecycle ──
    def create_session(self, session_id: str, source: str, **kwargs) -> str:
        """Create a new session record. Returns the session_id."""
        ...

    def ensure_session(
        self,
        session_id: str,
        source: str = "unknown",
        model: str = None,
        **kwargs,
    ) -> str:
        """Ensure a session row exists (INSERT OR IGNORE). Accepts optional kwargs."""
        ...

    def end_session(self, session_id: str, end_reason: str) -> None:
        """Mark a session as ended. First end_reason wins."""
        ...

    def reopen_session(self, session_id: str) -> None:
        """Clear ended_at/end_reason so a session can be resumed."""
        ...

    def update_session_cwd(self, session_id: str, cwd: str) -> None:
        """Persist the session working directory when a frontend knows it."""
        ...

    def update_system_prompt(self, session_id: str, system_prompt: str) -> None:
        """Store the full assembled system prompt snapshot."""
        ...

    def update_session_model(self, session_id: str, model: str) -> None:
        """Update the model for a session after a mid-session switch."""
        ...

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
        ...

    # ── Session reads ──
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a session by ID."""
        ...

    def resolve_session_id(self, session_id_or_prefix: str) -> Optional[str]:
        """Resolve an exact or uniquely prefixed session ID to the full ID."""
        ...

    def get_session_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        """Look up a session by exact title. Returns session dict or None."""
        ...

    def resolve_session_by_title(self, title: str) -> Optional[str]:
        """Resolve a title to a session ID, preferring the latest in a lineage."""
        ...

    def get_next_title_in_lineage(self, base_title: str) -> str:
        """Generate the next title in a lineage (e.g., 'my session' -> 'my session #2')."""
        ...

    def get_compression_tip(self, session_id: str) -> Optional[str]:
        """Walk the compression-continuation chain forward and return the tip."""
        ...

    def get_session_title(self, session_id: str) -> Optional[str]:
        """Get the title for a session, or None."""
        ...

    def set_session_title(self, session_id: str, title: str) -> bool:
        """Set or update a session's title. Returns True if found and set."""
        ...

    def set_session_archived(self, session_id: str, archived: bool) -> bool:
        """Archive or unarchive a session. Returns True when a row was updated."""
        ...

    @staticmethod
    def sanitize_title(title: Optional[str]) -> Optional[str]:
        """Validate and sanitize a session title."""
        ...

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
        ...

    def search_sessions(
        self,
        source: str = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List sessions, optionally filtered by source, most-recently-used first."""
        ...

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
        """Full-text search across session messages using FTS5."""
        ...

    def session_count(
        self,
        source: str = None,
        min_message_count: int = 0,
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> int:
        """Count sessions, optionally filtered by source."""
        ...

    # ── Messages ──
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
        ...

    def replace_messages(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        """Atomically replace every message for a session."""
        ...

    def get_messages(
        self, session_id: str, include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """Load messages for a session in insertion order."""
        ...

    def get_messages_around(
        self,
        session_id: str,
        around_message_id: int,
        window: int = 5,
    ) -> Dict[str, Any]:
        """Load a window of messages anchored on a specific message id."""
        ...

    def get_anchored_view(
        self,
        session_id: str,
        around_message_id: int,
        window: int = 5,
        bookend: int = 3,
        keep_roles: Optional[Tuple[str, ...]] = ("user", "assistant"),
    ) -> Dict[str, Any]:
        """Return an anchored window plus session bookends."""
        ...

    def resolve_resume_session_id(self, session_id: str) -> str:
        """Redirect a resume target to the descendant session that holds the messages."""
        ...

    def get_messages_as_conversation(
        self,
        session_id: str,
        include_ancestors: bool = False,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Load messages in the OpenAI conversation format (role + content dicts)."""
        ...

    def rewind_to_message(
        self, session_id: str, target_message_id: int
    ) -> Dict[str, Any]:
        """Soft-delete all messages with id >= target in session_id."""
        ...

    def restore_rewound(self, session_id: str, since_message_id: int) -> int:
        """Mark inactive messages with id >= since_message_id active again."""
        ...

    def list_recent_user_messages(
        self,
        session_id: str,
        limit: int = 20,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return the *limit* most-recent user messages, newest first."""
        ...

    def message_count(self, session_id: str = None) -> int:
        """Count messages, optionally for a specific session."""
        ...

    # ── Compression locks ──
    def try_acquire_compression_lock(
        self,
        session_id: str,
        holder: str,
        ttl_seconds: float = 300.0,
    ) -> bool:
        """Try to atomically acquire the compression lock for ``session_id``."""
        ...

    def release_compression_lock(self, session_id: str, holder: str) -> None:
        """Release the compression lock for ``session_id`` iff we own it."""
        ...

    def get_compression_lock_holder(self, session_id: str) -> Optional[str]:
        """Return the current (non-expired) holder for ``session_id``, or None."""
        ...

    # ── Export / cleanup / maintenance ──
    def export_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Export a single session with all its messages as a dict."""
        ...

    def export_all(self, source: str = None) -> List[Dict[str, Any]]:
        """Export all sessions (with messages) as a list of dicts."""
        ...

    def clear_messages(self, session_id: str) -> None:
        """Delete all messages for a session and reset its counters."""
        ...

    def delete_session(
        self,
        session_id: str,
        sessions_dir: Optional[Path] = None,
    ) -> bool:
        """Delete a session and all its messages. Returns True if found/deleted."""
        ...

    def delete_sessions(
        self,
        session_ids: List[str],
        sessions_dir: Optional[Path] = None,
    ) -> int:
        """Delete every session in *session_ids* in a single transaction."""
        ...

    def count_empty_sessions(self) -> int:
        """Return the count of empty, ended, non-archived sessions."""
        ...

    def delete_empty_sessions(
        self,
        sessions_dir: Optional[Path] = None,
    ) -> int:
        """Delete every empty, ended, non-archived session."""
        ...

    def prune_sessions(
        self,
        older_than_days: int = 90,
        source: str = None,
        sessions_dir: Optional[Path] = None,
    ) -> int:
        """Delete sessions older than N days. Returns count of deleted sessions."""
        ...

    def prune_empty_ghost_sessions(self, sessions_dir: "Optional[Path]" = None) -> int:
        """Remove empty TUI ghost sessions (no messages, no title, >24hr old)."""
        ...

    def finalize_orphaned_compression_sessions(self) -> int:
        """Mark orphaned compression continuation sessions as ended."""
        ...

    def optimize_fts(self) -> int:
        """Merge/compact FTS5 segments. Returns number of indexes optimized."""
        ...

    def vacuum(self) -> int:
        """Run VACUUM to reclaim disk space after large deletes."""
        ...

    def maybe_auto_prune_and_vacuum(
        self,
        retention_days: int = 90,
        min_interval_hours: int = 24,
        vacuum: bool = True,
        sessions_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Idempotent auto-maintenance: prune old sessions + optional VACUUM."""
        ...

    # ── Meta key/value (global, unscoped) ──
    def get_meta(self, key: str) -> Optional[str]:
        """Read a value from the state_meta key/value store."""
        ...

    def set_meta(self, key: str, value: str) -> None:
        """Write a value to the state_meta key/value store."""
        ...

    # ── Telegram DM topic mode ──
    def apply_telegram_topic_migration(self) -> None:
        """Create Telegram DM topic-mode tables on explicit /topic opt-in."""
        ...

    def enable_telegram_topic_mode(
        self,
        *,
        chat_id: str,
        user_id: str,
        has_topics_enabled: Optional[bool] = None,
        allows_users_to_create_topics: Optional[bool] = None,
    ) -> None:
        """Enable Telegram DM topic mode for one private chat/user."""
        ...

    def disable_telegram_topic_mode(
        self,
        *,
        chat_id: str,
        clear_bindings: bool = True,
    ) -> None:
        """Disable Telegram DM topic mode for one private chat."""
        ...

    def is_telegram_topic_mode_enabled(self, *, chat_id: str, user_id: str) -> bool:
        """Return whether Telegram DM topic mode is enabled for this chat/user."""
        ...

    def get_telegram_topic_binding(
        self,
        *,
        chat_id: str,
        thread_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the session binding for a Telegram DM topic, if present."""
        ...

    def list_telegram_topic_bindings_for_chat(
        self,
        *,
        chat_id: str,
    ) -> List[Dict[str, Any]]:
        """All Telegram DM topic bindings for one chat, newest first."""
        ...

    def get_telegram_topic_binding_by_session(
        self,
        *,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the Telegram DM topic binding for a given session_id, if present."""
        ...

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
        ...

    def is_telegram_session_linked_to_topic(self, *, session_id: str) -> bool:
        """Return True if an Elidia session is already bound to any Telegram DM topic."""
        ...

    def list_unlinked_telegram_sessions_for_user(
        self,
        *,
        chat_id: str,
        user_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """List previous Telegram sessions for this user that are not bound to a topic."""
        ...

    # ── Handoff (cross-platform session transfer) ──
    def request_handoff(self, session_id: str, platform: str) -> bool:
        """Mark a session as pending handoff to the given platform."""
        ...

    def get_handoff_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Read the current handoff state for a session."""
        ...

    def list_pending_handoffs(self) -> List[Dict[str, Any]]:
        """Return all sessions in handoff_state='pending', oldest first."""
        ...

    def claim_handoff(self, session_id: str) -> bool:
        """Atomically transition pending -> running. Returns True if claimed."""
        ...

    def complete_handoff(self, session_id: str) -> None:
        """Mark a handoff as completed."""
        ...

    def fail_handoff(self, session_id: str, error: str) -> None:
        """Mark a handoff as failed and record the reason."""
        ...
