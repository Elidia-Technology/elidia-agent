"""Regression guard for AIUT-3283: the SEQUENTIAL tool path must consult the
portal tool proxy.

The portal tool proxy (``tools.portal_tool_proxy.maybe_proxy_tool``) redirects
media-generation tools (``image_generate`` / ``video_generate`` /
``text_to_speech`` / ``generate_3d``) to the portal's ``/agent-v2/v1/tools/execute``
endpoint so the user's portal credits are charged, instead of the native FAL
handler (which has no FAL key on the hosted gateway).

Historically the proxy was wired ONLY into the CONCURRENT path
(``agent._invoke_tool`` → ``invoke_tool`` → ``maybe_proxy_tool``). The hosted web
gateway executes tools on the SEQUENTIAL path (``execute_tool_calls_sequential``),
which calls ``handle_function_call`` directly and never consulted the proxy — so a
web image request hit the native FAL handler and died with "no FAL key, no managed
image-gen provider set up".

This suite pins the fix at two levels:

1. Unit tests for the extracted ``_portal_proxy_result`` helper (returns the
   proxied result, or None when the proxy declines / raises).
2. A source-level guard that ``execute_tool_calls_sequential`` actually calls the
   helper before its local dispatch chain — so removing the call fails the test.
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

from agent.tool_executor import _portal_proxy_result


# ── Unit tests: _portal_proxy_result helper ──────────────────────────


def test_portal_proxy_result_returns_proxy_output():
    """A non-None proxy result is returned verbatim."""
    expected = '{"success": true, "image": "https://cdn.example/img.png"}'
    with patch(
        "tools.portal_tool_proxy.maybe_proxy_tool",
        return_value=expected,
    ) as mock_proxy:
        result = _portal_proxy_result(
            "image_generate", {"prompt": "a sunset", "quality": "standard"}
        )

    assert result == expected
    mock_proxy.assert_called_once_with(
        "image_generate", {"prompt": "a sunset", "quality": "standard"}
    )


def test_portal_proxy_result_returns_none_when_proxy_declines():
    """When the proxy declines (returns None), the helper returns None so the
    caller falls through to local dispatch."""
    with patch("tools.portal_tool_proxy.maybe_proxy_tool", return_value=None):
        assert _portal_proxy_result("web_search", {"query": "x"}) is None


def test_portal_proxy_result_returns_none_on_exception():
    """A proxy failure must never take the whole turn down — return None and
    let the normal (local) handler run."""
    def _boom(*_a, **_k):
        raise RuntimeError("portal unreachable")

    with patch("tools.portal_tool_proxy.maybe_proxy_tool", side_effect=_boom):
        assert _portal_proxy_result("image_generate", {"prompt": "x"}) is None


# ── Source-level guard: the sequential executor calls the helper ─────


def test_sequential_executor_consults_portal_proxy_helper():
    """Guard that ``execute_tool_calls_sequential`` calls ``_portal_proxy_result``.

    A revert that removes the call fails this test, mirroring the existing
    ``test_run_agent_concurrent_executor_wraps_submit_with_copy_context``
    source-level guard.
    """
    from agent import tool_executor as module

    source = inspect.getsource(module.execute_tool_calls_sequential)
    assert "_portal_proxy_result(function_name, function_args)" in source, (
        "execute_tool_calls_sequential no longer consults the portal tool proxy "
        "helper. Media generation on the web (sequential path) would regress to "
        "the native FAL handler and fail with 'no FAL key'. Re-add the "
        "`_portal_proxy_result` call before the dispatch chain (AIUT-3283)."
    )

    # The helper must exist and be importable from the module.
    assert callable(module._portal_proxy_result)


# ── Behavioral test: proxied result is used, local dispatch skipped ──


@pytest.mark.parametrize(
    "tool_name,args",
    [
        ("image_generate", {"prompt": "a robot"}),
        ("video_generate", {"prompt": "a rocket", "duration": 5}),
        ("text_to_speech", {"text": "hello", "audio_type": "speech"}),
    ],
)
def test_sequential_executor_uses_proxied_result(tool_name, args):
    """End-to-end: a proxied media tool returns the portal result and never
    reaches ``handle_function_call``."""
    import json
    import types
    from unittest.mock import MagicMock

    from agent import tool_executor as executor_module

    proxied = json.dumps({"success": True, "url": "https://cdn.example/out"})

    # ── Fake assistant message with one tool call ──
    tc = MagicMock()
    tc.id = "call_1"
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args)

    assistant_msg = MagicMock()
    assistant_msg.tool_calls = [tc]

    # ── Fake agent: identity pass-throughs so the result stays a real string
    # through the post-processing chain, and the real (heavy) hooks are stubbed.
    agent = MagicMock()
    agent._interrupt_requested = False
    agent.quiet_mode = True  # skip print branches
    agent.verbose_logging = False
    agent.log_prefix = ""
    agent.session_id = ""
    agent._current_turn_id = ""
    agent._current_api_request_id = ""
    agent._current_tool = None
    agent.valid_tool_names = []
    agent.enabled_toolsets = None
    agent.disabled_toolsets = None
    agent._memory_manager = None
    agent._context_engine_tool_names = None
    agent._todo_store = MagicMock()
    agent.tool_delay = 0

    # Guardrail: allow execution.
    decision = types.SimpleNamespace(allows_execution=True, message=None)
    agent._tool_guardrails.before_call = MagicMock(return_value=decision)

    # Checkpoint manager: disabled.
    agent._checkpoint_mgr = MagicMock()
    agent._checkpoint_mgr.enabled = False

    # Keep the result a real string through guardrail observation + subdir hint
    # + multimodal unwrap.
    agent._append_guardrail_observation = MagicMock(
        side_effect=lambda name, a, result, failed=False: result
    )
    agent._subdirectory_hints = MagicMock()
    agent._subdirectory_hints.check_tool_call = MagicMock(return_value=None)
    agent._tool_result_content_for_active_model = MagicMock(
        side_effect=lambda name, result: result
    )

    # Stub the remaining real post-processing helpers that would otherwise
    # touch stores / emit hooks against a MagicMock agent.
    with patch.object(
        executor_module, "maybe_persist_tool_result",
        side_effect=lambda content, tool_name, tool_use_id, env: content,
    ), patch(
        "agent.agent_runtime_helpers.agent_runtime_owns_post_tool_hook",
        return_value=False,
    ), patch(
        "tools.portal_tool_proxy.maybe_proxy_tool", return_value=proxied
    ) as mock_proxy, patch(
        "run_agent.handle_function_call", return_value="SHOULD_NOT_RUN"
    ) as mock_handle:
        messages: list = []
        executor_module.execute_tool_calls_sequential(
            agent, assistant_msg, messages, "default"
        )

    # The proxy was consulted with the tool name + args.
    mock_proxy.assert_called_once_with(tool_name, args)
    # The local dispatch was never reached.
    mock_handle.assert_not_called()
    # Exactly one tool result message was appended, carrying the proxied result.
    assert len(messages) == 1
    assert messages[0]["role"] == "tool"
    assert proxied in messages[0]["content"]
