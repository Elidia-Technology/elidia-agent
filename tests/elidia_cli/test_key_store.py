"""Tests for the API key store (B13 — key-holder).

The point of this module is that the key stops living in os.environ, because
this agent starts terminal commands, code sandboxes and MCP servers by design
and every one of them inherits the environment. So the tests are about where the
key is read from and what a wrong key tells the user — not about keyring's own
behaviour.
"""

import types

import pytest

from elidia_cli import key_store


class _FakeKeyring:
    """Stands in for the OS credential store."""

    def __init__(self, *, broken=False, no_backend=False):
        self._store = {}
        self._broken = broken
        self._no_backend = no_backend

    def get_keyring(self):
        if self._no_backend:
            from keyring.backends.fail import Keyring as FailKeyring
            return FailKeyring()
        return types.SimpleNamespace()

    def set_password(self, service, account, value):
        if self._broken:
            raise RuntimeError("keychain is locked")
        self._store[(service, account)] = value

    def get_password(self, service, account):
        if self._broken:
            raise RuntimeError("keychain is locked")
        return self._store.get((service, account))

    def delete_password(self, service, account):
        del self._store[(service, account)]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in key_store.ENV_VAR_NAMES:
        monkeypatch.delenv(name, raising=False)
    key_store.invalidate_cache()
    yield
    key_store.invalidate_cache()


@pytest.fixture
def fake_keyring(monkeypatch):
    kr = _FakeKeyring()
    monkeypatch.setattr(key_store, "_keyring", lambda: kr)
    return kr


class TestValidation:
    def test_a_real_key_shape_passes(self):
        assert key_store.validate("ak-dev-abc123def456") == (True, None)

    def test_an_openai_key_is_named_as_such(self):
        """The gateway answers 401 for this. Saying so at the moment of pasting
        beats a failure at the first billed call, which reads like a broken
        tool rather than a wrong key."""
        ok, problem = key_store.validate("sk-proj-abc123")
        assert ok is False
        assert "OpenAI-style" in problem

    def test_a_session_token_is_named_as_such(self):
        ok, problem = key_store.validate("eyJhbGciOiJIUzI1NiJ9.abc")
        assert ok is False and "session token" in problem

    def test_a_wrong_prefix_shows_what_was_pasted(self):
        ok, problem = key_store.validate("pk-live-abcdefghij")
        assert ok is False
        assert "ak-dev-" in problem and "pk-live" in problem

    def test_prefix_only_is_rejected(self):
        ok, problem = key_store.validate("ak-dev-")
        assert ok is False and "missing" in problem

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_empty_is_rejected(self, value):
        assert key_store.validate(value)[0] is False

    def test_validation_is_shape_only(self):
        """Whether a key is live, revoked or funded is the server's business,
        and the only honest way to know is to use it."""
        assert key_store.validate("ak-dev-completely-made-up")[0] is True


class TestStorage:
    def test_a_stored_key_is_read_back(self, fake_keyring):
        assert key_store.store("ak-dev-abc123") == (True, None)
        key_store.invalidate_cache()
        assert key_store.load() == "ak-dev-abc123"
        assert key_store.source() == "os-keychain"

    def test_an_invalid_key_is_refused_before_it_reaches_the_keychain(self, fake_keyring):
        """Writing a bad credential into the keychain just relocates the
        confusion, and the user then has to find and clear it."""
        stored, problem = key_store.store("sk-proj-nope")
        assert stored is False and "OpenAI-style" in problem
        assert fake_keyring._store == {}

    def test_surrounding_whitespace_is_stripped(self, fake_keyring):
        key_store.store("  ak-dev-abc123\n")
        key_store.invalidate_cache()
        assert key_store.load() == "ak-dev-abc123"

    def test_a_broken_keychain_reports_rather_than_raises(self, monkeypatch):
        monkeypatch.setattr(key_store, "_keyring", lambda: _FakeKeyring(broken=True))
        stored, problem = key_store.store("ak-dev-abc123")
        assert stored is False and "locked" in problem

    def test_delete_removes_it(self, fake_keyring):
        key_store.store("ak-dev-abc123")
        assert key_store.delete() is True
        key_store.invalidate_cache()
        assert key_store.load() is None

    def test_delete_when_nothing_is_stored(self, fake_keyring):
        assert key_store.delete() is False


class TestResolutionOrder:
    def test_keychain_wins_over_a_stale_shell(self, fake_keyring, monkeypatch):
        """An env var may be a leftover from a shell open for a week; the
        keychain is where the user deliberately put the key."""
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-from-env")
        key_store.store("ak-dev-from-keychain")
        key_store.invalidate_cache()
        assert key_store.load() == "ak-dev-from-keychain"

    def test_env_is_used_when_nothing_is_stored(self, fake_keyring, monkeypatch):
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-from-env")
        assert key_store.load() == "ak-dev-from-env"
        assert key_store.source() == "environment"

    def test_env_precedence_matches_the_documented_order(self, monkeypatch):
        monkeypatch.setenv("AIUTILS_API_KEY", "ak-dev-third")
        monkeypatch.setenv("ELIDIA_API_KEY", "ak-dev-second")
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-first")
        assert key_store.load_from_env() == "ak-dev-first"

    def test_an_explicit_override_can_prefer_env(self, fake_keyring, monkeypatch):
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-one-off")
        key_store.store("ak-dev-stored")
        assert key_store.load_preferring_env() == "ak-dev-one-off"

    def test_nothing_configured_reports_so(self, fake_keyring):
        assert key_store.load() is None
        assert key_store.source() == "not-configured"


class TestDegradesWithoutAKeyring:
    """Not a declared dependency, and a headless Linux box often has no Secret
    Service. Refusing to run over that would be worse than the exposure it
    prevents."""

    def test_no_keyring_module_falls_back_to_env(self, monkeypatch):
        monkeypatch.setattr(key_store, "_keyring", lambda: None)
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-env-only")
        assert key_store.load() == "ak-dev-env-only"
        assert key_store.backend_available() is False

    def test_storing_without_a_backend_explains_rather_than_crashes(self, monkeypatch):
        monkeypatch.setattr(key_store, "_keyring", lambda: None)
        stored, problem = key_store.store("ak-dev-abc123")
        assert stored is False and "No OS credential store" in problem

    def test_fail_backend_counts_as_no_backend(self, monkeypatch):
        """keyring imports fine on a headless box and only raises on use, so
        the backend has to be checked up front."""
        real = _FakeKeyring(no_backend=True)
        monkeypatch.setattr("keyring.get_keyring", real.get_keyring)
        assert key_store.backend_available() is False

    def test_a_locked_keychain_falls_back_instead_of_failing(self, monkeypatch):
        monkeypatch.setattr(key_store, "_keyring", lambda: _FakeKeyring(broken=True))
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-env-fallback")
        assert key_store.load() == "ak-dev-env-fallback"


class TestMigrationHint:
    def test_hint_when_the_key_is_only_in_the_environment(self, fake_keyring, monkeypatch):
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-abc")
        hint = key_store.migration_hint()
        assert hint and "inherits it" in hint

    def test_no_hint_once_it_is_in_the_keychain(self, fake_keyring, monkeypatch):
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-abc")
        key_store.store("ak-dev-abc")
        key_store.invalidate_cache()
        assert key_store.migration_hint() is None

    def test_no_hint_when_there_is_nowhere_better_to_put_it(self, monkeypatch):
        monkeypatch.setattr(key_store, "_keyring", lambda: None)
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-abc")
        assert key_store.migration_hint() is None

    def test_no_hint_when_no_key_is_configured(self, fake_keyring):
        assert key_store.migration_hint() is None


class TestCaching:
    def test_reads_are_cached_off_the_hot_path(self, monkeypatch):
        """api_key() runs on every check_aiutils_requirements call; a Keychain
        round trip there would be felt, and on macOS could prompt."""
        calls = []

        class _Counting(_FakeKeyring):
            def get_password(self, service, account):
                calls.append(1)
                return "ak-dev-abc"

        monkeypatch.setattr(key_store, "_keyring", lambda: _Counting())
        for _ in range(10):
            key_store.load()
        assert len(calls) == 1

    def test_storing_refreshes_the_cache(self, fake_keyring):
        key_store.load()                      # caches None
        key_store.store("ak-dev-new")
        assert key_store.load() == "ak-dev-new"


class TestClientUsesIt:
    def test_api_key_reads_through_the_store(self, fake_keyring, monkeypatch):
        from tools import aiutils_client

        key_store.store("ak-dev-via-keychain")
        key_store.invalidate_cache()
        assert aiutils_client.api_key() == "ak-dev-via-keychain"

    def test_api_key_still_works_with_only_an_env_var(self, monkeypatch):
        from tools import aiutils_client

        monkeypatch.setattr(key_store, "_keyring", lambda: None)
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-env")
        key_store.invalidate_cache()
        assert aiutils_client.api_key() == "ak-dev-env"


class TestCliOutput:
    def test_status_masks_the_key(self, fake_keyring, capsys):
        from elidia_cli import key_cli

        key_store.store("ak-dev-SECRETVALUE1234")
        key_store.invalidate_cache()
        key_cli.cmd_key_status(types.SimpleNamespace())

        out = capsys.readouterr().out
        assert "SECRETVALUE" not in out, "the full key must never be printed"
        assert "ak-dev-SECR" in out, "but enough to tell which key it is"

    def test_status_says_where_it_is_and_who_can_reach_it(self, fake_keyring, capsys):
        from elidia_cli import key_cli

        key_store.store("ak-dev-abc123def")
        key_store.invalidate_cache()
        key_cli.cmd_key_status(types.SimpleNamespace())
        out = capsys.readouterr().out
        assert "keychain" in out
        assert "not inherited by subprocesses" in out

    def test_status_warns_when_the_key_is_in_the_environment(self, fake_keyring, monkeypatch, capsys):
        from elidia_cli import key_cli

        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-abc123def")
        key_store.invalidate_cache()
        key_cli.cmd_key_status(types.SimpleNamespace())
        out = capsys.readouterr().out
        assert "inherited by every command" in out

    def test_store_refuses_a_bad_key_with_a_reason(self, fake_keyring, capsys):
        from elidia_cli import key_cli

        rc = key_cli.cmd_key_store(types.SimpleNamespace(key="sk-proj-wrong"))
        assert rc == 1
        assert "OpenAI-style" in capsys.readouterr().err

    def test_store_says_the_env_copy_is_still_there(self, fake_keyring, monkeypatch, capsys):
        """Never deleted for them: the file may be deployment-managed or shared
        with the gateway."""
        from elidia_cli import key_cli

        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-abc123def")
        rc = key_cli.cmd_key_store(types.SimpleNamespace(key="ak-dev-abc123def"))
        assert rc == 0
        assert "still inherited by subprocesses" in capsys.readouterr().out


class TestCacheScope:
    """The first version cached the RESOLVED key, which froze the environment
    for the process lifetime — a test setting ELIDIA_KEY, a gateway reloading
    config, or a mid-session export were all ignored until restart. It broke
    7 existing tests, which is how it was caught."""

    def test_environment_changes_are_seen_immediately(self, fake_keyring, monkeypatch):
        assert key_store.load() is None
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-set-later")
        assert key_store.load() == "ak-dev-set-later"

    def test_environment_removal_is_seen_immediately(self, fake_keyring, monkeypatch):
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-temporary")
        assert key_store.load() == "ak-dev-temporary"
        monkeypatch.delenv("ELIDIA_KEY")
        assert key_store.load() is None

    def test_a_locked_keychain_is_not_cached_as_empty(self, monkeypatch):
        """A keychain the user unlocks mid-session should start working, not
        stay broken because the first failed read was remembered."""
        state = {"broken": True}

        class _Flaky(_FakeKeyring):
            def get_password(self, service, account):
                if state["broken"]:
                    raise RuntimeError("locked")
                return "ak-dev-unlocked"

        monkeypatch.setattr(key_store, "_keyring", lambda: _Flaky())
        assert key_store.load() is None
        state["broken"] = False
        assert key_store.load() == "ak-dev-unlocked"
