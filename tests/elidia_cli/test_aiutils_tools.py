"""Tests for the AiUtils tool handlers (generate/estimate/get/tool/embed).

Handlers are exercised directly with a fake AiUtils client injected through
``aiutils_client``; no network or real SDK is involved. The central guarantee
under test: a billed call is never made when the credit guard refuses.
"""

import json
import types

import pytest

from tools import aiutils_client
from tools import aiutils_generate, aiutils_tool, aiutils_embed


class _FakeGenerations:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def create(self, model, parameters, wait_for_completion=False):
        self.calls.append(
            {"model": model, "parameters": parameters, "wait_for_completion": wait_for_completion}
        )
        return self.result

    def get(self, generation_id):
        self.calls.append({"get": generation_id})
        return self.result


class _FakeWallet:
    def estimate_cost(self, model, parameters=None):
        return types.SimpleNamespace(estimated_dt=7, estimated_usd=0.003)

    def balance(self):
        return types.SimpleNamespace(balance_dt=100)


class _FakeTools:
    def __init__(self):
        self.last_execute = None

    def genres(self):
        return {"genres": ["image", "video"]}

    def execute(self, tool_slug, **params):
        self.last_execute = (tool_slug, params)
        return {"ok": True, "slug": tool_slug}


class _FakeEmbeddings:
    def create(self, model, input):
        return types.SimpleNamespace(
            model=model,
            data=[types.SimpleNamespace(embedding=[0.1, 0.2, 0.3])],
        )


class _FakeClient:
    def __init__(self):
        gen_result = types.SimpleNamespace(
            id="g1",
            status="processing",
            model="m",
            download_urls=[],
            dt_consumed=None,
            dt_reserved=None,
            error=None,
        )
        self.generations = _FakeGenerations(gen_result)
        self.wallet = _FakeWallet()
        self.tools = _FakeTools()
        self.embeddings = _FakeEmbeddings()


@pytest.fixture
def client(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(aiutils_client, "get_client", lambda base_url=None: fake)
    return fake


def _parse(result):
    return json.loads(result)


class TestAiUtilsGenerate:
    def test_missing_model(self, client):
        result = _parse(aiutils_generate._handle_generate({"model": ""}))
        assert "error" in result
        assert "model is required" in result["error"]

    def test_credit_guard_refusal_means_no_charge(self, monkeypatch, client):
        monkeypatch.setattr(
            aiutils_client,
            "check_credit_before_spend",
            lambda model, parameters=None: {
                "ok": False, "error": "Insufficient DT balance",
            },
        )
        result = _parse(aiutils_generate._handle_generate({"model": "m"}))
        assert "Insufficient DT balance" in result["error"]
        assert client.generations.calls == []  # nothing billed

    def test_ok_submits_async(self, monkeypatch, client):
        monkeypatch.setattr(
            aiutils_client,
            "check_credit_before_spend",
            lambda model, parameters=None: {
                "ok": True, "estimated_dt": 7, "balance_dt": 100, "client": client,
            },
        )
        result = _parse(
            aiutils_generate._handle_generate({"model": "m", "parameters": {"prompt": "x"}})
        )
        assert result["id"] == "g1"
        assert result["status"] == "processing"
        assert client.generations.calls == [
            {
                "model": "m",
                "parameters": {"prompt": "x"},
                "wait_for_completion": False,
            }
        ]


class TestAiUtilsEstimate:
    def test_returns_estimate_and_balance(self, client):
        result = _parse(aiutils_generate._handle_estimate({"model": "m"}))
        assert result["estimated_dt"] == 7
        assert result["balance_dt"] == 100
        assert result["model"] == "m"


class TestAiUtilsGenerationGet:
    def test_polls_by_id(self, client):
        result = _parse(
            aiutils_generate._handle_generation_get({"generation_id": "g1"})
        )
        assert result["id"] == "g1"
        assert client.generations.calls == [{"get": "g1"}]


class TestAiUtilsTool:
    def test_genres(self, client):
        result = _parse(aiutils_tool._handle_genres({}))
        assert result["genres"] == ["image", "video"]

    def test_execute_requires_slug(self, client):
        result = _parse(aiutils_tool._handle_execute({"tool_slug": ""}))
        assert "tool_slug is required" in result["error"]

    def test_execute_passes_inputs(self, client):
        result = _parse(
            aiutils_tool._handle_execute(
                {"tool_slug": "img-resize", "inputs": {"width": 100}}
            )
        )
        assert result["ok"] is True
        assert client.tools.last_execute == ("img-resize", {"width": 100})


class TestAiUtilsEmbed:
    def test_embed_requires_input(self, client):
        result = _parse(aiutils_embed._handle_embed({"input": ""}))
        assert "input is required" in result["error"]

    def test_embed_returns_dimensions(self, client):
        result = _parse(aiutils_embed._handle_embed({"input": "hello", "model": "e3"}))
        assert result["dimensions"] == 3
        assert result["vectors"] == 1
        assert result["model"] == "e3"


class TestSpendGuardCoversEveryBilledPath:
    """AIUT-2948 regression tests.

    ``aiutils_tool_execute`` and ``aiutils_embed`` both spend DT — portal tool
    execution is billed server-side ("Portal handles credit deduction" in the
    gateway proxy) and embeddings bill on token usage — but neither consulted
    the credit guard. These tests assert the billed call is not merely reported
    as refused, but *never made*.
    """

    @staticmethod
    def _broke_wallet():
        class _Wallet:
            def estimate_cost(self, model, parameters=None):
                return types.SimpleNamespace(estimated_dt=50)

            def balance(self):
                return types.SimpleNamespace(balance_dt=0)

        return _Wallet()

    def test_tool_execute_refuses_on_empty_wallet_and_makes_no_call(self, client):
        client.wallet = self._broke_wallet()

        result = _parse(aiutils_tool._handle_execute({"tool_slug": "image-generator"}))

        assert "error" in result
        # An exhausted wallet now PAUSES the run and writes resume state rather
        # than reporting "insufficient" (owner directive 2026-08-23). Still
        # refuses, still makes no billed call — the mechanism changed, not the
        # guarantee.
        assert "Paused" in result["error"]
        assert client.tools.last_execute is None, "billed tool call must not be made"

    def test_embed_refuses_on_empty_wallet(self, client):
        client.wallet = self._broke_wallet()
        calls = []
        client.embeddings.create = lambda model, input: calls.append(model)

        result = _parse(aiutils_embed._handle_embed({"input": "hello"}))

        assert "error" in result
        assert "Paused" in result["error"]  # see note above — pause, not "insufficient"
        assert calls == [], "billed embedding call must not be made"

    def test_unreadable_wallet_refuses_rather_than_assuming_funds(self, client):
        class _Wallet:
            def estimate_cost(self, model, parameters=None):
                raise RuntimeError("boom")

            def balance(self):
                raise RuntimeError("network down")

        client.wallet = _Wallet()

        result = _parse(aiutils_tool._handle_execute({"tool_slug": "image-generator"}))

        assert "error" in result
        assert "Could not verify wallet balance" in result["error"]
        assert client.tools.last_execute is None

    def test_unpriceable_slug_degrades_to_balance_check_not_a_refusal(self, client):
        """A tool slug 404s on /v1/pricing/estimate — that must not block a
        funded wallet, or every tool call would break."""

        class _Wallet:
            def estimate_cost(self, model, parameters=None):
                raise RuntimeError("404 Model not found")

            def balance(self):
                return types.SimpleNamespace(balance_dt=250)

        client.wallet = _Wallet()

        result = _parse(aiutils_tool._handle_execute({"tool_slug": "image-generator"}))

        assert "error" not in result
        assert client.tools.last_execute is not None, "funded wallet must still run the tool"

    def test_guard_reports_inexact_when_cost_could_not_be_priced(self, client):
        class _Wallet:
            def estimate_cost(self, model, parameters=None):
                raise RuntimeError("404 Model not found")

            def balance(self):
                return types.SimpleNamespace(balance_dt=250)

        client.wallet = _Wallet()

        guard = aiutils_client.check_spend_allowed("some-slug", client=client)

        assert guard["ok"] is True
        assert guard["exact"] is False
        assert guard["estimated_dt"] is None
        assert guard["balance_dt"] == 250

    def test_guard_is_exact_when_model_is_priceable(self, client):
        guard = aiutils_client.check_spend_allowed("real-model", client=client)

        assert guard["ok"] is True
        assert guard["exact"] is True
        assert guard["estimated_dt"] == 7
