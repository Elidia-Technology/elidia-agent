"""Tests for the observed-cost memory (B15).

The point of this module is that running something once should make its cost
known from then on. So the tests are about what the agent can say to the user
*after* a call, not about the storage format.
"""

import json
import types

import pytest

from tools import aiutils_client, aiutils_cost_memory as cm


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ELIDIA_HOME", str(tmp_path))
    yield


class TestRecording:
    def test_a_single_run_makes_a_tool_priceable(self):
        """The whole point: /v1/pricing/estimate 404s on tool slugs, so before
        this the hundredth run knew no more than the first."""
        key = cm.tool_key("bg-remove")
        assert cm.estimate(key) is None

        cm.record(key, 42)

        est = cm.estimate(key)
        assert est["dt"] == 42 and est["samples"] == 1

    def test_median_not_mean_so_one_outlier_does_not_move_it(self):
        key = cm.model_key("flux-pro")
        for dt in (10, 11, 12, 9, 4000):   # one huge input
            cm.record(key, dt)
        assert cm.estimate(key)["dt"] == 11

    def test_range_is_reported_so_precision_is_not_implied(self):
        key = cm.tool_key("t")
        for dt in (5, 50):
            cm.record(key, dt)
        est = cm.estimate(key)
        assert (est["low"], est["high"]) == (5, 50)
        assert "5–50 DT" in cm.describe(key)

    def test_identical_runs_are_described_as_certain(self):
        key = cm.tool_key("fixed-price")
        cm.record(key, 7)
        cm.record(key, 7)
        assert "same on all 2 previous run(s)" in cm.describe(key)

    def test_missing_header_is_not_recorded_as_free(self):
        """None means the response carried no X-DT-Consumed — an older gateway
        or an unbilled endpoint. Storing it as 0 would teach the agent that a
        billed tool costs nothing."""
        key = cm.tool_key("unknown-cost")
        cm.record(key, None)
        assert cm.estimate(key) is None

    def test_zero_is_recorded_because_free_is_a_real_answer(self):
        key = cm.tool_key("free-tool")
        cm.record(key, 0)
        assert cm.estimate(key)["dt"] == 0

    def test_models_and_tools_do_not_pool_observations(self):
        cm.record(cm.model_key("shared-name"), 1000)
        cm.record(cm.tool_key("shared-name"), 5)
        assert cm.estimate(cm.tool_key("shared-name"))["dt"] == 5

    def test_sample_window_is_bounded(self):
        key = cm.tool_key("busy")
        for dt in range(cm.MAX_SAMPLES + 30):
            cm.record(key, dt)
        est = cm.estimate(key)
        assert est["samples"] == cm.MAX_SAMPLES
        assert est["observations"] == cm.MAX_SAMPLES + 30, "the total is still counted"

    def test_recent_samples_win_so_a_price_change_is_picked_up(self):
        key = cm.tool_key("repriced")
        for _ in range(cm.MAX_SAMPLES):
            cm.record(key, 10)
        for _ in range(cm.MAX_SAMPLES):
            cm.record(key, 90)
        assert cm.estimate(key)["dt"] == 90


class TestResilience:
    def test_a_corrupt_cache_does_not_break_a_billed_call(self, tmp_path):
        (tmp_path / cm.COST_FILE).write_text("{ this is not json")
        assert cm.estimate(cm.tool_key("x")) is None
        cm.record(cm.tool_key("x"), 5)   # must not raise

    def test_unwritable_home_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(cm, "_save", lambda data: (_ for _ in ()).throw(OSError("ro")))
        cm.record(cm.tool_key("x"), 5)   # swallowed

    def test_negative_cost_is_rejected(self):
        cm.record(cm.tool_key("weird"), -5)
        assert cm.estimate(cm.tool_key("weird")) is None

    def test_record_from_client_tolerates_an_older_sdk(self):
        """An SDK without last_dt_consumed should cost the agent its learning,
        not the call."""
        assert cm.record_from_client(cm.tool_key("x"), types.SimpleNamespace()) is None
        assert cm.estimate(cm.tool_key("x")) is None

    def test_record_from_client_reads_the_sdk_property(self):
        client = types.SimpleNamespace(last_dt_consumed=88)
        assert cm.record_from_client(cm.tool_key("y"), client) == 88
        assert cm.estimate(cm.tool_key("y"))["dt"] == 88


class TestSpendGuardUsesIt:
    def _client(self, balance_dt=10_000):
        class _Wallet:
            def balance(self):
                return types.SimpleNamespace(balance_dt=balance_dt)

            def estimate_cost(self, model, parameters=None):
                raise RuntimeError("404 Model not found")   # a tool slug

        return types.SimpleNamespace(wallet=_Wallet())

    def test_unpriceable_call_stays_unpriced_until_something_is_learned(self):
        guard = aiutils_client.check_spend_allowed("bg-remove", client=self._client())
        assert guard["ok"] is True
        assert guard["exact"] is False
        assert guard["estimated_dt"] is None

    def test_after_one_run_the_guard_has_a_number(self):
        cm.record(cm.tool_key("bg-remove"), 30)
        guard = aiutils_client.check_spend_allowed("bg-remove", client=self._client())

        assert guard["ok"] is True
        assert guard["estimated_dt"] == 30
        assert guard["exact"] is False, "observed is not the same as quoted"
        assert guard["learned"]["samples"] == 1

    def test_confirm_before_charge_can_now_fire_on_a_tool_slug(self, monkeypatch):
        """Previously impossible: with no number there was nothing to compare
        against the threshold, so an expensive tool ran silently."""
        from tools import confirm_context

        asked = []
        token = confirm_context.set_confirm_callback(
            lambda q, c: asked.append(q) or "yes"
        )
        try:
            cm.record(cm.tool_key("video-render"), 5_000)
            guard = aiutils_client.check_spend_allowed(
                "video-render", client=self._client()
            )
        finally:
            confirm_context._confirm_callback.reset(token)

        assert guard["ok"] is True
        assert len(asked) == 1
        assert "5000 DT" in asked[0]
        assert "previous run" in asked[0], "must read as an observation, not a quote"

    def test_declining_a_learned_estimate_still_refuses(self):
        from tools import confirm_context

        token = confirm_context.set_confirm_callback(lambda q, c: "no")
        try:
            cm.record(cm.tool_key("pricey"), 9_000)
            guard = aiutils_client.check_spend_allowed("pricey", client=self._client())
        finally:
            confirm_context._confirm_callback.reset(token)

        assert guard["ok"] is False and guard["declined"] is True

    def test_an_exhausted_wallet_still_pauses_before_any_of_this(self):
        cm.record(cm.tool_key("bg-remove"), 30)
        guard = aiutils_client.check_spend_allowed(
            "bg-remove", client=self._client(balance_dt=0)
        )
        assert guard["ok"] is False and guard["paused"] is True

    def test_catalog_pricing_still_wins_over_observation(self):
        """A real quote beats a guess from history."""
        cm.record(cm.model_key("flux-pro"), 999)

        class _Wallet:
            def balance(self):
                return types.SimpleNamespace(balance_dt=10_000)

            def estimate_cost(self, model, parameters=None):
                return types.SimpleNamespace(estimated_dt=12)

        guard = aiutils_client.check_spend_allowed(
            "flux-pro", client=types.SimpleNamespace(wallet=_Wallet())
        )
        assert guard["estimated_dt"] == 12
        assert guard["exact"] is True


class TestInspection:
    def test_all_known_lists_what_has_been_learned(self):
        cm.record(cm.tool_key("a"), 1)
        cm.record(cm.model_key("b"), 2)
        known = cm.all_known()
        assert set(known) == {"tool:a", "model:b"}

    def test_forget_drops_a_key_after_a_price_change(self):
        cm.record(cm.tool_key("a"), 1)
        assert cm.forget(cm.tool_key("a")) is True
        assert cm.estimate(cm.tool_key("a")) is None
        assert cm.forget(cm.tool_key("a")) is False

    def test_file_is_valid_json_a_human_can_read(self, tmp_path):
        cm.record(cm.tool_key("a"), 1)
        json.loads((tmp_path / cm.COST_FILE).read_text())


class TestSurfacedToTheModel:
    def test_model_info_reports_what_the_model_has_cost_before(self, monkeypatch):
        """The catalog gives a price; this gives the bill. They diverge once
        input size is involved, and the bill is the one a user recognises."""
        import types as _t

        from tools import aiutils_models

        cm.record(cm.model_key("flux-pro"), 40)
        cm.record(cm.model_key("flux-pro"), 60)

        info = _t.SimpleNamespace(
            id="flux-pro", description="d", input_schema=None, output_schema=None,
        )
        monkeypatch.setattr(aiutils_models, "_cached", lambda key, produce: info)

        payload = json.loads(aiutils_models._handle_model_info({"model_id": "flux-pro"}))
        assert "50 DT" in payload["observed_cost"]
        assert "40–60 DT" in payload["observed_cost"]

    def test_model_info_omits_the_field_when_nothing_is_known(self, monkeypatch):
        """Absent, not "unknown": a null field invites the model to say
        something about a cost it has no information on."""
        import types as _t

        from tools import aiutils_models

        info = _t.SimpleNamespace(
            id="never-run", description="d", input_schema=None, output_schema=None,
        )
        monkeypatch.setattr(aiutils_models, "_cached", lambda key, produce: info)

        payload = json.loads(aiutils_models._handle_model_info({"model_id": "never-run"}))
        assert "observed_cost" not in payload
