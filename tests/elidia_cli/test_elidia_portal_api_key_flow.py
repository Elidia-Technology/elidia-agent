"""Elidia Portal authenticates with an AiUtils Developer API key (AIUT-3434).

The Portal's OAuth device-code endpoint does not exist (HTTP 405). These tests
pin the replacement behaviour:

- ``elidia model`` → Elidia Portal / ``elidia portal`` / ``elidia setup --portal``
  all go through ``_model_flow_elidia``, which must never start an OAuth login
  and must hand off to the ``aiutils`` API-key flow.
- A key kept only in the OS keychain (``elidia key store``) must reach the chat
  provider, resolved with the same precedence the tools use, so chat and tools
  never bill different keys.
- Replacing / clearing the key from the model picker acts on the keychain.

Only the OS keychain and the interactive prompts are faked; the dispatch and
resolution logic under test runs for real.
"""

import types

import pytest

from elidia_cli import key_store


class _FakeKeyring:
    """Stands in for the OS credential store."""

    def __init__(self):
        self._store = {}

    def get_keyring(self):
        return types.SimpleNamespace()

    def set_password(self, service, account, value):
        self._store[(service, account)] = value

    def get_password(self, service, account):
        return self._store.get((service, account))

    def delete_password(self, service, account):
        del self._store[(service, account)]


@pytest.fixture(autouse=True)
def _clean_key_env(monkeypatch):
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


@pytest.fixture
def no_keyring(monkeypatch):
    monkeypatch.setattr(key_store, "_keyring", lambda: None)


@pytest.fixture
def oauth_forbidden(monkeypatch):
    """Fail the test if anything tries the dead OAuth device-code login."""

    def _boom(*args, **kwargs):
        raise AssertionError("Elidia Portal must not start an OAuth login")

    monkeypatch.setattr("elidia_cli.auth._login_elidia", _boom)
    monkeypatch.setattr("elidia_cli.auth._elidia_device_code_login", _boom)


# ── Chat provider key resolution ───────────────────────────────────────────


def test_keychain_only_key_reaches_chat_provider(fake_keyring):
    key_store.store("ak-dev-keychainonly123")
    from elidia_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested="aiutils")

    assert runtime["provider"] == "aiutils"
    assert runtime["api_key"] == "ak-dev-keychainonly123"


def test_chat_and_tools_resolve_the_same_key_when_both_exist(fake_keyring, monkeypatch):
    """Tools read keychain-first (key_store.load); chat must agree with them."""
    key_store.store("ak-dev-fromkeychain1")
    monkeypatch.setenv("ELIDIA_KEY", "ak-dev-staleenvvalue")
    from elidia_cli.auth import PROVIDER_REGISTRY, _resolve_api_key_provider_secret

    chat_key, source = _resolve_api_key_provider_secret("aiutils", PROVIDER_REGISTRY["aiutils"])

    assert chat_key == key_store.load() == "ak-dev-fromkeychain1"
    assert source == "os-keychain"


def test_env_key_still_works_without_a_keychain(no_keyring, monkeypatch):
    monkeypatch.setenv("AIUTILS_API_KEY", "ak-dev-envonly12345")
    from elidia_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested="aiutils")

    assert runtime["api_key"] == "ak-dev-envonly12345"


def test_no_key_anywhere_resolves_empty(fake_keyring):
    from elidia_cli.auth import PROVIDER_REGISTRY, _resolve_api_key_provider_secret

    assert _resolve_api_key_provider_secret("aiutils", PROVIDER_REGISTRY["aiutils"]) == ("", "")


# ── _model_flow_elidia (elidia model / elidia portal / setup --portal) ─────


def test_model_flow_elidia_with_key_goes_straight_to_api_key_flow(
    fake_keyring, oauth_forbidden, monkeypatch
):
    key_store.store("ak-dev-existingkey01")
    calls = []
    monkeypatch.setattr(
        "elidia_cli.main._model_flow_api_key_provider",
        lambda config, provider_id, current_model="": calls.append((provider_id, current_model)),
    )
    stored = []
    monkeypatch.setattr("elidia_cli.key_cli.cmd_key_store", lambda args: stored.append(args) or 0)
    from elidia_cli import main as elidia_main

    elidia_main._model_flow_elidia({}, current_model="deepseek-v4-flash")

    assert calls == [("aiutils", "deepseek-v4-flash")]
    assert stored == [], "an existing key must not be asked for again"


def test_model_flow_elidia_without_key_stores_one_in_keychain_then_picks_model(
    fake_keyring, oauth_forbidden, monkeypatch, capsys
):
    def _fake_store_command(args):
        # The real command prompts with getpass; the prompt is the only fake.
        assert args.key is None
        stored, problem = key_store.store("ak-dev-freshlypasted1")
        assert stored, problem
        return 0

    monkeypatch.setattr("elidia_cli.key_cli.cmd_key_store", _fake_store_command)
    seen_keys = []

    def _fake_api_key_flow(config, provider_id, current_model=""):
        from elidia_cli.auth import PROVIDER_REGISTRY, _resolve_api_key_provider_secret

        seen_keys.append(_resolve_api_key_provider_secret(provider_id, PROVIDER_REGISTRY[provider_id])[0])

    monkeypatch.setattr("elidia_cli.main._model_flow_api_key_provider", _fake_api_key_flow)
    from elidia_cli import main as elidia_main

    elidia_main._model_flow_elidia({})

    out = capsys.readouterr().out
    assert "AiUtils Developer API key" in out
    assert "https://developer.aiutils.io/api-keys" in out
    assert seen_keys == ["ak-dev-freshlypasted1"]


def test_model_flow_elidia_stops_when_key_store_is_cancelled(
    fake_keyring, oauth_forbidden, monkeypatch
):
    monkeypatch.setattr("elidia_cli.key_cli.cmd_key_store", lambda args: 1)
    calls = []
    monkeypatch.setattr(
        "elidia_cli.main._model_flow_api_key_provider",
        lambda *a, **k: calls.append(a),
    )
    from elidia_cli import main as elidia_main

    elidia_main._model_flow_elidia({})

    assert calls == []


def test_model_flow_elidia_without_keychain_falls_back_to_env_prompt(
    no_keyring, oauth_forbidden, monkeypatch
):
    def _must_not_run(args):
        raise AssertionError("no keychain: the generic flow prompts instead")

    monkeypatch.setattr("elidia_cli.key_cli.cmd_key_store", _must_not_run)
    calls = []
    monkeypatch.setattr(
        "elidia_cli.main._model_flow_api_key_provider",
        lambda config, provider_id, current_model="": calls.append(provider_id),
    )
    from elidia_cli import main as elidia_main

    elidia_main._model_flow_elidia({})

    assert calls == ["aiutils"]


def test_legacy_oauth_session_is_ignored(fake_keyring, oauth_forbidden, monkeypatch):
    """A stale providers.elidia OAuth session must not route to the dead endpoint."""
    monkeypatch.setattr(
        "elidia_cli.auth.get_provider_auth_state",
        lambda provider: {"access_token": "legacy-oauth-token"},
    )
    key_store.store("ak-dev-existingkey02")
    calls = []
    monkeypatch.setattr(
        "elidia_cli.main._model_flow_api_key_provider",
        lambda config, provider_id, current_model="": calls.append(provider_id),
    )
    from elidia_cli import main as elidia_main

    elidia_main._model_flow_elidia({})

    assert calls == ["aiutils"]


# ── Key prompt inside the model picker ─────────────────────────────────────


def _aiutils_pconfig():
    from elidia_cli.auth import PROVIDER_REGISTRY

    return PROVIDER_REGISTRY["aiutils"]


def test_first_time_aiutils_key_goes_to_keychain_not_env_file(fake_keyring, monkeypatch):
    saved_env = []
    monkeypatch.setattr("elidia_cli.config.save_env_value", lambda k, v: saved_env.append((k, v)))
    monkeypatch.setattr("elidia_cli.secret_prompt.masked_secret_prompt", lambda prompt: "ak-dev-typedin12345")
    from elidia_cli import main as elidia_main

    key, abort = elidia_main._prompt_api_key(_aiutils_pconfig(), "", provider_id="aiutils")

    assert (key, abort) == ("ak-dev-typedin12345", False)
    assert key_store.load_from_keyring() == "ak-dev-typedin12345"
    assert saved_env == []


def test_first_time_aiutils_key_with_wrong_format_is_not_saved(fake_keyring, monkeypatch, capsys):
    saved_env = []
    monkeypatch.setattr("elidia_cli.config.save_env_value", lambda k, v: saved_env.append((k, v)))
    monkeypatch.setattr("elidia_cli.secret_prompt.masked_secret_prompt", lambda prompt: "sk-openai-notours")
    from elidia_cli import main as elidia_main

    key, abort = elidia_main._prompt_api_key(_aiutils_pconfig(), "", provider_id="aiutils")

    assert abort is True
    assert key_store.load_from_keyring() is None
    assert saved_env == []
    assert "Not saved" in capsys.readouterr().out


def test_replacing_aiutils_key_updates_keychain(fake_keyring, monkeypatch):
    key_store.store("ak-dev-oldkeyvalue01")
    monkeypatch.setattr("builtins.input", lambda prompt="": "r")
    monkeypatch.setattr("elidia_cli.secret_prompt.masked_secret_prompt", lambda prompt: "ak-dev-newkeyvalue01")
    from elidia_cli import main as elidia_main

    key, abort = elidia_main._prompt_api_key(_aiutils_pconfig(), "ak-dev-oldkeyvalue01", provider_id="aiutils")

    assert (key, abort) == ("ak-dev-newkeyvalue01", False)
    assert key_store.load() == "ak-dev-newkeyvalue01"


def test_clearing_aiutils_key_removes_it_from_keychain(fake_keyring, monkeypatch):
    key_store.store("ak-dev-tobecleared01")
    monkeypatch.setattr("builtins.input", lambda prompt="": "c")
    monkeypatch.setattr("elidia_cli.config.save_env_value", lambda k, v: None)
    from elidia_cli import main as elidia_main

    key, abort = elidia_main._prompt_api_key(_aiutils_pconfig(), "ak-dev-tobecleared01", provider_id="aiutils")

    assert (key, abort) == ("", True)
    assert key_store.load() is None


def test_other_providers_still_save_to_env_file(fake_keyring, monkeypatch):
    saved_env = []
    monkeypatch.setattr("elidia_cli.config.save_env_value", lambda k, v: saved_env.append((k, v)))
    monkeypatch.setattr("elidia_cli.secret_prompt.masked_secret_prompt", lambda prompt: "zai-key-123")
    from elidia_cli import main as elidia_main
    from elidia_cli.auth import PROVIDER_REGISTRY

    key, abort = elidia_main._prompt_api_key(PROVIDER_REGISTRY["zai"], "", provider_id="zai")

    assert (key, abort) == ("zai-key-123", False)
    assert saved_env == [("GLM_API_KEY", "zai-key-123")]
    assert key_store.load_from_keyring() is None


# ── `elidia portal info` ───────────────────────────────────────────────────


def test_portal_info_reports_keychain_key_as_logged_in(fake_keyring, capsys):
    key_store.store("ak-dev-statuscheck01")
    from elidia_cli import portal_cli

    assert portal_cli._cmd_status(None) == 0

    out = capsys.readouterr().out
    assert "✓ AiUtils Developer API key" in out
    assert "ak-dev-s…" in out and "ak-dev-statuscheck01" not in out, "never print the full key"
    assert "https://developer-api.aiutils.io/v1" in out


def test_portal_info_without_key_points_to_real_api_keys_page(fake_keyring, capsys):
    from elidia_cli import portal_cli

    portal_cli._cmd_status(None)

    out = capsys.readouterr().out
    assert "no AiUtils Developer API key" in out
    assert "https://developer.aiutils.io/api-keys" in out
    assert "manage-subscription" not in out
