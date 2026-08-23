"""Tests for per-user API key linking on gateway platforms (B14).

The gateway serves many people through one bot and resolved a single operator
key, so everyone's DT spend billed the operator. These tests are about whether a
person's own key is used for their own calls — and about the ways this could
leak a key, which matter more than the happy path.
"""

import json
import os
import stat

import pytest

from elidia_cli import key_store
from gateway import key_link


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ELIDIA_HOME", str(tmp_path))
    for name in key_store.ENV_VAR_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(key_store, "_keyring", lambda: None)
    key_store.invalidate_cache()
    yield
    key_store.invalidate_cache()


class TestIdentity:
    def test_platform_and_user_are_both_required(self):
        assert key_link.identity("telegram", "123") == "telegram:123"
        assert key_link.identity("", "123") is None
        assert key_link.identity("telegram", "") is None

    def test_the_same_id_on_two_platforms_stays_separate(self):
        """User ids are unique only WITHIN a platform. Keying on the id alone
        would hand a Telegram user's key to a Slack user with the same id."""
        key_link.link("telegram", "42", "ak-dev-telegram-user")
        key_link.link("slack", "42", "ak-dev-slack-user")

        assert key_link.linked_key("telegram", "42") == "ak-dev-telegram-user"
        assert key_link.linked_key("slack", "42") == "ak-dev-slack-user"

    def test_platform_case_does_not_split_an_identity(self):
        key_link.link("Telegram", "42", "ak-dev-abc123")
        assert key_link.linked_key("telegram", "42") == "ak-dev-abc123"


class TestLinking:
    def test_a_linked_key_is_returned_for_that_user(self):
        ok, message = key_link.link("telegram", "42", "ak-dev-abc123def")
        assert ok is True
        assert key_link.linked_key("telegram", "42") == "ak-dev-abc123def"

    def test_an_unlinked_user_has_no_key(self):
        assert key_link.linked_key("telegram", "999") is None

    def test_an_invalid_key_is_refused_with_the_reason(self):
        ok, message = key_link.link("telegram", "42", "sk-proj-wrong")
        assert ok is False
        assert "OpenAI-style" in message
        assert key_link.linked_key("telegram", "42") is None

    def test_relinking_replaces_and_says_so(self):
        key_link.link("telegram", "42", "ak-dev-first1234")
        ok, message = key_link.link("telegram", "42", "ak-dev-second123")
        assert ok is True and message.startswith("Replaced")
        assert key_link.linked_key("telegram", "42") == "ak-dev-second123"

    def test_unlink_removes_it(self):
        key_link.link("telegram", "42", "ak-dev-abc123def")
        ok, message = key_link.unlink("telegram", "42")
        assert ok is True
        assert key_link.linked_key("telegram", "42") is None

    def test_unlink_when_nothing_is_linked(self):
        ok, message = key_link.unlink("telegram", "42")
        assert ok is False and "do not have a key linked" in message


class TestKeyIsNeverExposed:
    """These matter more than the happy path: a leaked key is spendable."""

    def test_the_confirmation_does_not_contain_the_key(self):
        secret = "ak-dev-SUPERSECRETVALUE9999"
        ok, message = key_link.link("telegram", "42", secret)
        assert ok is True
        assert secret not in message
        assert "SUPERSECRET" not in message

    def test_the_confirmation_shows_enough_to_identify_it(self):
        ok, message = key_link.link("telegram", "42", "ak-dev-SUPERSECRETVALUE9999")
        assert "ak-dev-SUPE" in message

    def test_the_confirmation_tells_them_to_delete_their_message(self):
        """The key is still sitting in the chat history until they do."""
        ok, message = key_link.link("telegram", "42", "ak-dev-abc123def")
        assert "Delete the message" in message

    def test_status_masks_the_key(self):
        key_link.link("telegram", "42", "ak-dev-SUPERSECRETVALUE9999")
        line = key_link.status("telegram", "42")
        assert "SUPERSECRET" not in line and "ak-dev-SUPE" in line

    def test_a_short_key_is_still_masked(self):
        assert key_link.masked("ak-dev-x") == "ak-d…"

    def test_the_trust_notice_says_the_operator_can_read_it(self):
        """Encryption at rest would be theatre against whoever runs the
        process — the gateway must hold usable credentials to spend on a
        user's behalf. So it is stated rather than obscured."""
        notice = key_link.trust_notice()
        assert "can read it" in notice
        assert "revoke" in notice


class TestStorageOnDisk:
    def test_the_store_is_owner_only(self, tmp_path):
        key_link.link("telegram", "42", "ak-dev-abc123def")
        mode = stat.S_IMODE(os.stat(tmp_path / key_link.STORE_FILENAME).st_mode)
        assert mode == 0o600, f"world-readable key store: {oct(mode)}"

    def test_the_temp_file_is_never_world_readable(self, tmp_path, monkeypatch):
        """mkstemp creates 0600 already, so the secret is not briefly exposed
        between write and chmod."""
        seen = {}
        real_replace = os.replace

        def _spy(src, dst):
            seen["mode"] = stat.S_IMODE(os.stat(src).st_mode)
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", _spy)
        key_link.link("telegram", "42", "ak-dev-abc123def")
        assert seen["mode"] == 0o600

    def test_a_corrupt_store_means_nobody_is_linked_rather_than_a_crash(self, tmp_path):
        (tmp_path / key_link.STORE_FILENAME).write_text("{ not json")
        assert key_link.linked_key("telegram", "42") is None

    def test_an_unwritable_store_reports_rather_than_claiming_success(self, monkeypatch):
        monkeypatch.setattr(key_link, "_save_all", lambda data: False)
        ok, message = key_link.link("telegram", "42", "ak-dev-abc123def")
        assert ok is False and "Nothing was stored" in message

    def test_the_file_is_valid_json(self, tmp_path):
        key_link.link("telegram", "42", "ak-dev-abc123def")
        data = json.loads((tmp_path / key_link.STORE_FILENAME).read_text())
        assert "telegram:42" in data


class TestResolutionDuringAMessage:
    def test_the_session_key_wins_over_the_operator_key(self, monkeypatch):
        """The whole point: on a gateway serving many users through one bot,
        falling back to the operator's key bills their wallet for someone
        else's work."""
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-operator")
        key_link.link("telegram", "42", "ak-dev-alice")

        token = key_store.set_session_key_resolver(
            lambda: key_link.linked_key("telegram", "42")
        )
        try:
            assert key_store.load() == "ak-dev-alice"
        finally:
            key_store.reset_session_key_resolver(token)

        assert key_store.load() == "ak-dev-operator", "must not leak past the message"

    def test_an_unlinked_user_falls_back_to_the_operator_key(self, monkeypatch):
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-operator")
        token = key_store.set_session_key_resolver(
            lambda: key_link.linked_key("telegram", "999")
        )
        try:
            assert key_store.load() == "ak-dev-operator"
        finally:
            key_store.reset_session_key_resolver(token)

    def test_a_broken_resolver_falls_back_rather_than_dropping_the_message(self, monkeypatch):
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-operator")
        token = key_store.set_session_key_resolver(
            lambda: (_ for _ in ()).throw(RuntimeError("store on fire"))
        )
        try:
            assert key_store.load() == "ak-dev-operator"
        finally:
            key_store.reset_session_key_resolver(token)

    def test_the_resolver_is_called_lazily(self, monkeypatch):
        """A message that never touches a billed tool should cost no store
        read."""
        calls = []
        token = key_store.set_session_key_resolver(lambda: calls.append(1) or None)
        try:
            assert calls == []
            key_store.load()
            assert len(calls) == 1
        finally:
            key_store.reset_session_key_resolver(token)

    def test_concurrent_messages_do_not_share_a_key(self):
        """Two users' turns run concurrently in the gateway. A module global
        would let one user's key serve the other's request."""
        import concurrent.futures

        from tools.thread_context import propagate_context_to_thread

        key_link.link("telegram", "1", "ak-dev-alice")
        key_link.link("telegram", "2", "ak-dev-bob")

        def _turn(user_id):
            token = key_store.set_session_key_resolver(
                lambda: key_link.linked_key("telegram", user_id)
            )
            try:
                return key_store.load()
            finally:
                key_store.reset_session_key_resolver(token)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            # One wrapper per worker: the returned callable holds a single
            # captured Context, and a Context cannot be entered twice at once.
            futures = [
                pool.submit(propagate_context_to_thread(_turn), user_id)
                for user_id in ("1", "2")
            ]
            results = [f.result() for f in futures]

        assert results == ["ak-dev-alice", "ak-dev-bob"]


class TestStatusMessages:
    def test_unlinked_status_explains_the_billing(self):
        line = key_link.status("telegram", "42")
        assert "operator's wallet" in line and "/link" in line

    def test_linked_status_explains_how_to_undo(self):
        key_link.link("telegram", "42", "ak-dev-abc123def")
        assert "/link off" in key_link.status("telegram", "42")


class TestCommandBehaviour:
    """The /link handler's refusals matter more than its successes."""

    def _event(self, args, chat_type="dm", platform="telegram", user_id="42"):
        import types as _t

        source = _t.SimpleNamespace(
            platform=_t.SimpleNamespace(value=platform),
            user_id=user_id, chat_type=chat_type, chat_id="c1",
        )
        return _t.SimpleNamespace(
            source=source, get_command_args=lambda: args, text=f"/link {args}",
        )

    async def _run(self, event):
        from gateway.run import GatewayRunner

        return await GatewayRunner._handle_link_command(None, event)

    def test_a_key_in_a_group_is_refused_and_called_compromised(self):
        """It is already public by the time we see it — everyone in the group
        can read it and it stays in the platform's history."""
        import asyncio

        reply = asyncio.run(self._run(self._event("ak-dev-abc123def", chat_type="group")))
        text = getattr(reply, "text", str(reply))

        assert "will not link a key from a group" in text
        assert "compromised" in text and "revoke" in text
        assert key_link.linked_key("telegram", "42") is None, "must not be stored"

    def test_the_refusal_does_not_repeat_the_key_back(self):
        """Echoing it would put it in the history a second time."""
        import asyncio

        reply = asyncio.run(
            self._run(self._event("ak-dev-SECRETVALUE123", chat_type="group"))
        )
        assert "SECRETVALUE" not in getattr(reply, "text", str(reply))

    def test_a_dm_links_the_key(self):
        import asyncio

        reply = asyncio.run(self._run(self._event("ak-dev-abc123def", chat_type="dm")))
        assert key_link.linked_key("telegram", "42") == "ak-dev-abc123def"
        assert "Linked" in getattr(reply, "text", str(reply))

    def test_bare_link_shows_status_and_the_trust_notice(self):
        """Someone about to hand over a spendable credential should be told
        what that means before they do it, not after."""
        import asyncio

        reply = asyncio.run(self._run(self._event("")))
        text = getattr(reply, "text", str(reply))
        assert "no AiUtils key linked" in text
        assert "can read it" in text

    def test_link_off_unlinks(self):
        import asyncio

        key_link.link("telegram", "42", "ak-dev-abc123def")
        reply = asyncio.run(self._run(self._event("off")))
        assert key_link.linked_key("telegram", "42") is None
        assert "Unlinked" in getattr(reply, "text", str(reply))

    def test_unlink_works_from_a_group_since_no_secret_is_involved(self):
        import asyncio

        key_link.link("telegram", "42", "ak-dev-abc123def")
        asyncio.run(self._run(self._event("off", chat_type="group")))
        assert key_link.linked_key("telegram", "42") is None

    def test_registered_as_gateway_only(self):
        """On the CLI a key belongs in the OS keychain via `elidia key store`,
        not attached to a platform identity that does not exist there."""
        from elidia_cli.commands import COMMAND_REGISTRY

        definition = next(c for c in COMMAND_REGISTRY if c.name == "link")
        assert definition.gateway_only is True


class TestNativeMenuOptOut:
    """Slack's 50-slash ceiling is already full, so a new command evicts an
    existing alias. Adding /link dropped /q until it opted out."""

    def test_link_is_absent_from_both_native_menus(self):
        from elidia_cli.commands import slack_native_slashes, telegram_bot_commands

        assert "link" not in {n for n, _, _ in slack_native_slashes()}
        assert "link" not in {n for n, _ in telegram_bot_commands()}

    # Parity between the two platforms is already enforced by
    # test_commands.py::TestSlackNativeSlashes::test_telegram_parity, which
    # normalises underscore/hyphen naming and excludes Slack-reserved names. A
    # naive set difference here duplicated it and got the normalisation wrong;
    # what matters for this feature is only that native_slash governs BOTH
    # lists, which the test above asserts directly.

    def test_the_alias_it_had_evicted_is_back(self):
        from elidia_cli.commands import slack_native_slashes

        assert "q" in {n for n, _, _ in slack_native_slashes()}

    def test_link_still_dispatches_when_typed(self):
        """Opting out affects DISCOVERY only — the gateway resolves commands
        through COMMAND_REGISTRY, not through what a platform registered."""
        from elidia_cli.commands import is_gateway_known_command, resolve_command

        assert resolve_command("link") is not None
        assert is_gateway_known_command("link") is True
