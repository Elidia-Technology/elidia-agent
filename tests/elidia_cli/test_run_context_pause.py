"""Tests for run context in pause records.

A pause record exists for one purpose: letting someone pick up a job that
stopped because the DT wallet ran out. A record that says only "balance 0"
serves that purpose no better than no record at all — so these tests are about
whether the *content* is usable, not whether a file was written.
"""

import json
import types

import pytest

from tools import aiutils_client, run_context, spend_pause


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ELIDIA_HOME", str(tmp_path))
    token = run_context.set_run_context(None)
    yield
    run_context._run_context.reset(token)


def _tool_msg(name):
    return {"role": "tool", "name": name, "tool_name": name, "content": "ok"}


def _client(balance_dt):
    class _Wallet:
        def balance(self):
            return types.SimpleNamespace(balance_dt=balance_dt)

        def estimate_cost(self, model, parameters=None):
            return types.SimpleNamespace(estimated_dt=5)

    return types.SimpleNamespace(wallet=_Wallet())


class TestStepDerivation:
    def test_steps_come_from_the_live_message_list(self):
        """The loop appends to the list it handed over; the context must see
        those appends, or the record describes the turn as it began rather than
        where it stopped."""
        messages = [{"role": "user", "content": "make a poster"}]
        ctx = run_context.RunContext(task="make a poster", messages=messages)

        assert ctx.completed_steps() == []

        messages.append(_tool_msg("web_search"))
        messages.append(_tool_msg("image_generate"))

        assert [s["tool"] for s in ctx.completed_steps()] == ["web_search", "image_generate"]

    def test_only_completed_calls_count(self):
        """A tool-result message exists only once the call returned, so a
        dispatched-but-unfinished call must not appear as completed."""
        messages = [
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        ]
        ctx = run_context.RunContext(messages=messages)
        assert ctx.completed_steps() == []

    def test_malformed_entries_do_not_break_the_pause(self):
        messages = [None, 42, {"role": "tool", "name": "terminal", "content": "x"}, object()]
        ctx = run_context.RunContext(messages=messages)
        assert [s["tool"] for s in ctx.completed_steps()] == ["terminal"]

    def test_step_list_is_capped_keeping_the_most_recent(self):
        messages = [_tool_msg(f"t{i}") for i in range(run_context.MAX_STEPS + 20)]
        steps = run_context.RunContext(messages=messages).completed_steps()
        assert len(steps) == run_context.MAX_STEPS
        assert steps[-1]["tool"] == f"t{run_context.MAX_STEPS + 19}", "must keep the newest"

    def test_long_task_is_truncated_but_marked(self):
        ctx = run_context.RunContext(task="x" * 9000)
        task = ctx.as_pause_context()["task"]
        assert len(task) < 9000
        assert "9000 chars" in task, "a truncated task must say it was truncated"


class TestPauseRecordContent:
    def test_exhausted_wallet_records_what_was_running(self):
        run_context.set_run_context(run_context.RunContext(
            session_id="sess-1",
            task="render the product video",
            task_id="task-9",
            turn_id="sess-1:task-9:abcd",
            messages=[_tool_msg("storyboard"), _tool_msg("tts")],
        ))

        guard = aiutils_client.check_spend_allowed("flux-pro", client=_client(0))

        assert guard["ok"] is False and guard["paused"] is True
        record = json.loads(open(guard["state_file"]).read())

        assert record["task"] == "render the product video"
        assert record["session_id"] == "sess-1"
        assert [s["tool"] for s in record["completed_steps"]] == ["storyboard", "tts"]
        assert record["pending_step"] == "billed call to flux-pro"
        assert record["extra"]["task_id"] == "task-9"
        assert record["extra"]["turn_id"] == "sess-1:task-9:abcd"

    def test_message_names_the_work_not_just_the_balance(self):
        run_context.set_run_context(run_context.RunContext(
            task="render the product video", messages=[_tool_msg("storyboard")],
        ))
        guard = aiutils_client.check_spend_allowed("flux-pro", client=_client(0))

        assert "billed call to flux-pro" in guard["error"]
        assert "Completed 1 step" in guard["error"]

    def test_pause_still_works_with_no_run_context(self):
        """Direct SDK use and tests run outside a conversation turn; the pause
        must still stop the run and write a record."""
        guard = aiutils_client.check_spend_allowed("m", client=_client(0))

        assert guard["ok"] is False and guard["paused"] is True
        record = json.loads(open(guard["state_file"]).read())
        assert record["task"] is None
        assert record["completed_steps"] == []


class TestServerDeclinedPath:
    def _exc(self, **kwargs):
        from aiutils_sdk.exceptions import InsufficientDTError

        return InsufficientDTError("Insufficient DT balance", **kwargs)

    def test_402_records_the_balance_the_server_reported(self):
        """Not a hardcoded 0 — that would put a number in the record that was
        never true, and a resume would show the wrong shortfall."""
        run_context.set_run_context(run_context.RunContext(
            task="upscale the batch", messages=[_tool_msg("image_generate")],
        ))

        message = aiutils_client.handle_sdk_error(
            self._exc(required_dt=900, available_dt=110,
                      top_up_url="https://developer.aiutils.io/billing/top-up"),
            action="image generation",
        )

        assert "You are 790 DT short" in message
        records = spend_pause.list_paused_jobs()
        assert len(records) == 1
        assert records[0]["balance_dt"] == 110
        assert records[0]["task"] == "upscale the batch"
        assert records[0]["pending_step"] == "image generation"
        assert records[0]["extra"]["declined_by"] == "server"

    def test_explicit_caller_fields_win_over_ambient(self):
        run_context.set_run_context(run_context.RunContext(task="ambient task"))

        aiutils_client.handle_sdk_error(
            self._exc(required_dt=10, available_dt=0),
            action="a call",
            task="explicit task",
        )

        assert spend_pause.list_paused_jobs()[0]["task"] == "explicit task"

    def test_extra_is_merged_not_replaced(self):
        """Two sides contribute to `extra`; whichever wrote last must not erase
        the other, or the server detail and the turn ids become exclusive."""
        run_context.set_run_context(run_context.RunContext(
            task="t", task_id="task-3",
        ))

        aiutils_client.handle_sdk_error(
            self._exc(required_dt=10, available_dt=0), action="a call",
            extra={"caller_note": "from the tool"},
        )

        extra = spend_pause.list_paused_jobs()[0]["extra"]
        assert extra["task_id"] == "task-3"          # ambient
        assert extra["declined_by"] == "server"      # handler
        assert extra["caller_note"] == "from the tool"  # caller


class TestContextIsolation:
    def test_context_does_not_leak_between_turns(self):
        import contextvars

        run_context.set_run_context(run_context.RunContext(task="turn one"))

        def _other():
            return run_context.get_run_context()

        assert contextvars.Context().run(_other) is None
        assert run_context.get_run_context().task == "turn one"

    def test_worker_thread_sees_the_parents_live_messages(self):
        """Tools dispatch through a thread pool. `propagate_context_to_thread`
        copies the context, so the worker holds the same list object and a
        pause taken there reflects steps the loop appended."""
        import concurrent.futures

        from tools.thread_context import propagate_context_to_thread

        messages = [_tool_msg("first")]
        run_context.set_run_context(run_context.RunContext(
            task="threaded", messages=messages,
        ))
        messages.append(_tool_msg("second"))

        def _in_worker():
            ctx = run_context.get_run_context()
            return [s["tool"] for s in ctx.completed_steps()] if ctx else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(propagate_context_to_thread(_in_worker)).result()

        assert result == ["first", "second"]


class TestPublishedByARealTurn:
    """The unit tests above set the context by hand. This one runs an actual
    conversation turn, because the wiring in run_conversation is the part that
    would silently do nothing — every test would still pass while every real
    pause record came out empty."""

    def test_run_conversation_publishes_the_context_mid_turn(self):
        from unittest.mock import MagicMock, patch

        seen = {}

        def _capture(*args, **kwargs):
            # Read it from inside the turn: that is when a spend guard fires.
            ctx = run_context.get_run_context()
            seen["task"] = getattr(ctx, "task", None)
            seen["session_id"] = getattr(ctx, "session_id", None)
            seen["task_id"] = getattr(ctx, "task_id", None)
            seen["messages_is_live_list"] = getattr(ctx, "messages", None) is not None

            choice = MagicMock()
            choice.message.content = "done"
            choice.message.tool_calls = None
            choice.message.refusal = None
            choice.message.reasoning_content = None
            choice.finish_reason = "stop"
            response = MagicMock()
            response.choices = [choice]
            response.usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
            response.model = "test-model"
            response.id = "test-id"
            return response

        with patch("run_agent.AIAgent._build_system_prompt", return_value="sys"), \
             patch("run_agent.AIAgent._interruptible_streaming_api_call", side_effect=_capture), \
             patch("run_agent.AIAgent._interruptible_api_call", side_effect=_capture):
            from run_agent import AIAgent

            agent = AIAgent(
                model="test/model", api_key="test-key",
                base_url="http://localhost:1234/v1",
                quiet_mode=True, skip_memory=True, skip_context_files=True,
            )
            agent.client = MagicMock()
            agent.run_conversation(user_message="build me a landing page",
                                   conversation_history=[])

        assert seen["task"] == "build me a landing page", (
            "the run context was not published during the turn — pause records "
            "would come out empty in production"
        )
        assert seen["task_id"], "task_id must be set so a resume can be correlated"
        assert seen["messages_is_live_list"] is True
