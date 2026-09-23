"""Test that ELIDIA_SESSION_ID is set via ContextVar on agent init."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from gateway.session_context import _SESSION_ID, _UNSET, get_session_env
from run_agent import AIAgent


@pytest.fixture(autouse=True)
def _cleanup_env():
    """Remove ELIDIA_SESSION_ID from env and reset ContextVar before/after."""
    os.environ.pop("ELIDIA_SESSION_ID", None)
    _SESSION_ID.set(_UNSET)
    yield
    os.environ.pop("ELIDIA_SESSION_ID", None)
    _SESSION_ID.set(_UNSET)


def test_session_id_contextvar_set_on_init():
    """AIAgent.__init__ sets ELIDIA_SESSION_ID in the ContextVar."""
    agent = AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    assert get_session_env("ELIDIA_SESSION_ID") == agent.session_id
    assert len(agent.session_id) > 0


def test_session_id_contextvar_uses_provided_id():
    """When session_id is passed explicitly, the ContextVar reflects it."""
    custom_id = "20260511_120000_abc12345"
    agent = AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        session_id=custom_id,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    assert get_session_env("ELIDIA_SESSION_ID") == custom_id
    assert agent.session_id == custom_id


def test_session_id_no_process_global_write():
    """set_current_session_id no longer writes os.environ (AIUT-3078 B1)."""
    custom_id = "20260511_130000_def67890"
    AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        session_id=custom_id,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    assert os.environ.get("ELIDIA_SESSION_ID") is None
    assert get_session_env("ELIDIA_SESSION_ID") == custom_id
