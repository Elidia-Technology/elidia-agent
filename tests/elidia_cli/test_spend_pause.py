"""Tests for balance-exhaustion pause and resume.

Requirements these encode (owner, 2026-08-23):
  - automated runs spend freely; their ceiling is the wallet, not a prompt
  - when the balance runs out the run pauses and records resumable state
  - work already in flight is never killed — only NEW work is withheld
  - a negative balance is acceptable and settles at the next top-up
"""

import json
import types

import pytest

from tools import aiutils_client, confirm_context, spend_pause


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ELIDIA_HOME", str(tmp_path))
    token = confirm_context.set_confirm_callback(None)
    yield
    confirm_context._confirm_callback.reset(token)


def _client(estimated_dt, balance_dt):
    class _Wallet:
        def estimate_cost(self, model, parameters=None):
            return types.SimpleNamespace(estimated_dt=estimated_dt)

        def balance(self):
            return types.SimpleNamespace(balance_dt=balance_dt)

    return types.SimpleNamespace(wallet=_Wallet())


class TestAutomatedRunsSpendFreely:
    """No human at the keyboard must not mean no work gets done."""

    def test_large_unattended_spend_proceeds(self):
        assert confirm_context.is_interactive() is False
        guard = aiutils_client.check_spend_allowed("m", client=_client(50_000, 100_000))
        assert guard["ok"] is True, "automated runs must not be blocked by the absence of a prompt"

    def test_only_the_wallet_limits_an_automated_run(self):
        """Funded proceeds; exhausted pauses. The prompt is irrelevant either way."""
        assert aiutils_client.check_spend_allowed("m", client=_client(10, 5_000))["ok"] is True
        assert aiutils_client.check_spend_allowed("m", client=_client(10, 0))["ok"] is False


class TestPauseOnExhaustedBalance:
    def test_zero_balance_pauses_and_records_state(self):
        guard = aiutils_client.check_spend_allowed("m", client=_client(10, 0))

        assert guard["ok"] is False
        assert guard["paused"] is True
        assert guard["pause_id"]
        assert guard["state_file"], "a pause must be resumable"

    def test_pause_record_is_readable_and_complete(self):
        guard = aiutils_client.check_spend_allowed("m", client=_client(10, 0))
        record = json.loads(open(guard["state_file"]).read())

        assert record["reason"] == "balance_exhausted"
        assert record["balance_dt"] == 0
        assert record["pause_id"] == guard["pause_id"]
        assert record["paused_at"]

    def test_negative_balance_pauses_and_is_explained_as_expected(self):
        """The last call may overshoot; that must not read as a billing bug."""
        guard = aiutils_client.check_spend_allowed("m", client=_client(10, -250))

        assert guard["paused"] is True
        assert "overshot by 250 DT" in guard["error"]
        assert "next top-up" in guard["error"]

    def test_pause_message_tells_the_user_how_to_continue(self):
        guard = aiutils_client.check_spend_allowed("m", client=_client(10, 0))
        assert "Top up your balance" in guard["error"]

    def test_funded_wallet_does_not_pause(self):
        assert aiutils_client.check_spend_allowed("m", client=_client(10, 5_000))["ok"] is True

    def test_a_spend_larger_than_the_balance_is_allowed_to_overshoot(self):
        """Owner directive: work runs while the wallet has anything in it. The
        last call may exceed the balance and settle on the next top-up.
        Refusing here would stop a funded job because its final step happens to
        be the expensive one."""
        guard = aiutils_client.check_spend_allowed("m", client=_client(10_000, 1))
        assert guard["ok"] is True, "overshoot must be permitted, not refused"
        assert guard["estimated_dt"] == 10_000
        assert guard["balance_dt"] == 1

    def test_interactive_overshoot_is_disclosed_before_approval(self):
        """Allowed, but never silently — the user sees it before agreeing."""
        asked = []
        confirm_context.set_confirm_callback(lambda q, c: asked.append(q) or "yes")

        aiutils_client.check_spend_allowed("m", client=_client(10_000, 1))

        assert asked, "an overshoot above the threshold must be confirmed"
        assert "exceeds your balance by 9999 DT" in asked[0]
        assert "next top-up" in asked[0]


class TestInFlightWorkIsNotKilled:
    """The guard runs BEFORE new billed work, so anything already dispatched
    settles normally — that is what allows the overshoot in the first place."""

    def test_pause_withholds_new_work_rather_than_aborting(self):
        calls = []

        class _Wallet:
            def estimate_cost(self, model, parameters=None):
                calls.append("estimate")
                return types.SimpleNamespace(estimated_dt=10)

            def balance(self):
                return types.SimpleNamespace(balance_dt=0)

        guard = aiutils_client.check_spend_allowed(
            "m", client=types.SimpleNamespace(wallet=_Wallet())
        )
        assert guard["paused"] is True
        assert calls == [], "must not even price new work once paused"


class TestResumeRecords:
    def test_records_carry_the_task_and_progress(self):
        record = spend_pause.record_pause(
            balance_dt=0, task="Render 40 product images",
            completed_steps=["img-1", "img-2"], pending_step="img-3",
            spent_this_run_dt=4200, session_id="sess-1",
        )
        assert record["task"] == "Render 40 product images"
        assert record["pending_step"] == "img-3"
        assert len(record["completed_steps"]) == 2

    def test_listing_returns_saved_jobs_newest_first(self):
        spend_pause.record_pause(balance_dt=0, task="first")
        spend_pause.record_pause(balance_dt=0, task="second")
        jobs = spend_pause.list_paused_jobs()
        assert len(jobs) == 2
        assert {j["task"] for j in jobs} == {"first", "second"}

    def test_clearing_removes_a_record(self):
        record = spend_pause.record_pause(balance_dt=0, task="done")
        assert spend_pause.clear_paused_job(record["pause_id"]) is True
        assert spend_pause.list_paused_jobs() == []

    def test_progress_is_reported_so_work_done_is_not_assumed_lost(self):
        record = spend_pause.record_pause(
            balance_dt=0, completed_steps=["a", "b", "c"], pending_step="d"
        )
        message = spend_pause.format_pause_message(record)
        assert "Completed 3 step(s)" in message
        assert "work so far is kept" in message

    def test_unwritable_state_still_pauses_but_warns(self, monkeypatch):
        """A persistence failure must not swallow the pause itself."""
        def _boom(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(spend_pause.Path, "write_text", _boom)
        record = spend_pause.record_pause(balance_dt=0, task="x")

        assert record["state_file"] is None
        assert "cannot be continued automatically" in spend_pause.format_pause_message(record)

    def test_a_corrupt_record_does_not_hide_the_others(self, tmp_path):
        good = spend_pause.record_pause(balance_dt=0, task="good")
        (spend_pause._pause_dir() / "broken.json").write_text("{not json")
        jobs = spend_pause.list_paused_jobs()
        assert [j["task"] for j in jobs] == ["good"]
        assert good["pause_id"]
