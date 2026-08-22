"""Tests for the AiUtils tool-layer client helper + credit guard.

These never touch the network: ``_import_sdk`` is monkeypatched with a fake
module so we can exercise the fail-closed requirement checks and the
DT-balance credit guard in isolation.
"""

import types

import pytest

from tools import aiutils_client


def _clear_keys(monkeypatch):
    for var in aiutils_client.API_KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _set_key(monkeypatch, value="ak-dev-test"):
    _clear_keys(monkeypatch)
    monkeypatch.setenv(aiutils_client.API_KEY_ENV_VARS[-1], value)


class _FakeWallet:
    def __init__(self, estimate_dt=0, balance_dt=100):
        self.estimate_dt = estimate_dt
        self.balance_dt = balance_dt

    def estimate_cost(self, model, parameters=None):
        if getattr(self, "raise_on_estimate", False):
            raise RuntimeError("pricing unavailable")
        return types.SimpleNamespace(estimated_dt=self.estimate_dt, estimated_usd=0.0)

    def balance(self):
        return types.SimpleNamespace(balance_dt=self.balance_dt)


class _FakeClient:
    def __init__(self, estimate_dt=0, balance_dt=100):
        self.wallet = _FakeWallet(estimate_dt, balance_dt)
        self.last_constructed_kwargs = None


def _install_sdk(monkeypatch, client=None):
    captured = {}

    def _ctor(api_key, base_url=None):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        return client

    monkeypatch.setattr(
        aiutils_client,
        "_import_sdk",
        lambda: types.SimpleNamespace(AiUtils=_ctor),
    )
    return captured


class TestCheckAiUtilsRequirements:
    def test_false_without_api_key(self, monkeypatch):
        _clear_keys(monkeypatch)
        assert aiutils_client.check_aiutils_requirements() is False

    def test_false_without_sdk(self, monkeypatch):
        _set_key(monkeypatch)
        monkeypatch.setattr(
            aiutils_client, "_import_sdk", _raise_import_error
        )
        assert aiutils_client.check_aiutils_requirements() is False

    def test_true_when_both_present(self, monkeypatch):
        _set_key(monkeypatch)
        monkeypatch.setattr(aiutils_client, "_import_sdk", lambda: object())
        assert aiutils_client.check_aiutils_requirements() is True


def _raise_import_error():
    raise ImportError("aiutils_sdk not installed")


class TestGetClient:
    def test_constructs_from_env_and_default_base(self, monkeypatch):
        _set_key(monkeypatch)
        captured = _install_sdk(monkeypatch, client=_FakeClient())
        aiutils_client.get_client()
        assert captured["api_key"] == "ak-dev-test"
        assert captured["base_url"] == aiutils_client.DEFAULT_BASE_URL

    def test_raises_without_key(self, monkeypatch):
        _clear_keys(monkeypatch)
        with pytest.raises(RuntimeError):
            aiutils_client.get_client()


class TestCheckCreditBeforeSpend:
    def test_ok_when_balance_covers_estimate(self, monkeypatch):
        _set_key(monkeypatch)
        client = _FakeClient(estimate_dt=10, balance_dt=100)
        _install_sdk(monkeypatch, client=client)
        guard = aiutils_client.check_credit_before_spend("m", {"prompt": "x"})
        assert guard["ok"] is True
        assert guard["estimated_dt"] == 10
        assert guard["balance_dt"] == 100
        assert guard["client"] is client

    def test_insufficient_balance_fails_closed(self, monkeypatch):
        _set_key(monkeypatch)
        client = _FakeClient(estimate_dt=10, balance_dt=5)
        _install_sdk(monkeypatch, client=client)
        guard = aiutils_client.check_credit_before_spend("m", {})
        assert guard["ok"] is False
        assert "Insufficient DT balance" in guard["error"]

    def test_estimate_error_fails_closed(self, monkeypatch):
        _set_key(monkeypatch)
        client = _FakeClient(estimate_dt=0, balance_dt=100)
        client.wallet.raise_on_estimate = True
        _install_sdk(monkeypatch, client=client)
        guard = aiutils_client.check_credit_before_spend("m", {})
        assert guard["ok"] is False
        assert "Could not verify wallet balance" in guard["error"]


class TestApiKeyResolution:
    """The three AiUtils Developer API key names are equivalent aliases."""

    def test_returns_none_when_no_keys(self, monkeypatch):
        _clear_keys(monkeypatch)
        assert aiutils_client.api_key() is None

    def test_prefers_elidia_key(self, monkeypatch):
        _clear_keys(monkeypatch)
        monkeypatch.setenv("AIUTILS_API_KEY", "ak-dev-a")
        monkeypatch.setenv("ELIDIA_API_KEY", "ak-dev-b")
        monkeypatch.setenv("ELIDIA_KEY", "ak-dev-c")
        assert aiutils_client.api_key() == "ak-dev-c"

    def test_falls_back_to_aiutils_key(self, monkeypatch):
        _clear_keys(monkeypatch)
        monkeypatch.setenv("AIUTILS_API_KEY", "ak-dev-a")
        assert aiutils_client.api_key() == "ak-dev-a"

    def test_env_vars_contract(self):
        assert aiutils_client.API_KEY_ENV_VARS == (
            "ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY",
        )
