"""The Developer API is the authority on billing — the agent must relay it.

The server meters each call and answers HTTP 402 with required/available/
shortfall when the wallet cannot cover it; the SDK raises that as
InsufficientDTError. Before this wiring the tools caught bare Exception and
flattened it to "Generation failed: <str>", so a balance problem was
indistinguishable from a network blip and the user was never told to top up.

The client-side guard is an optimisation, not the gate: a balance can be spent
by another session between check and call, and a call can cost more than its
estimate. The server's answer is the one that counts.
"""

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("/Users/mac/WorkSpace/AiUtils.io/developer/sdk")))

from aiutils_sdk.exceptions import (  # noqa: E402
    AuthenticationError,
    ForbiddenError,
    InsufficientDTError,
    RateLimitError,
)

from tools import aiutils_client, aiutils_generate, aiutils_rag  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ELIDIA_HOME", str(tmp_path))


class TestInsufficientBalanceIsRelayed:
    def test_402_is_reported_as_a_balance_problem_not_a_generic_failure(self):
        detail = "Insufficient DT balance. Required: 5000 DT, Available: 120 DT."
        message = aiutils_client.handle_sdk_error(
            InsufficientDTError(detail), action="generation"
        )

        assert message is not None
        assert "Out of DT balance" in message
        assert "5000 DT" in message and "120 DT" in message, "the shortfall must survive"
        assert "top up" in message.lower()

    def test_402_names_where_to_top_up(self):
        message = aiutils_client.handle_sdk_error(InsufficientDTError("x"), action="generation")
        assert "developer.aiutils.io/billing" in message

    def test_402_writes_a_resume_record(self, tmp_path):
        """A server-side stop should be as resumable as a client-side one."""
        message = aiutils_client.handle_sdk_error(
            InsufficientDTError("out of DT"), action="video generation"
        )
        saved = list((tmp_path / "paused-jobs").glob("*.json"))
        assert saved, "a 402 must leave resumable state"

        record = json.loads(saved[0].read_text())
        assert record["pending_step"] == "video generation"
        assert "out of DT" in record["extra"]["server_detail"]
        assert "Paused" in message

    def test_bookkeeping_failure_does_not_swallow_the_message(self, monkeypatch):
        """If the pause record cannot be written, the user must still be told
        they are out of balance."""
        import tools.spend_pause as sp

        monkeypatch.setattr(sp, "record_pause", lambda **kw: (_ for _ in ()).throw(OSError("nope")))
        message = aiutils_client.handle_sdk_error(InsufficientDTError("broke"), action="generation")
        assert "Out of DT balance" in message


class TestOtherServerErrorsAreDistinguished:
    """Each needs a different response from the user — conflating them sends
    someone to the billing page over a bad API key."""

    def test_auth_error_is_not_confused_with_billing(self):
        message = aiutils_client.handle_sdk_error(AuthenticationError("bad key"), action="generation")
        assert "not a balance problem" in message
        assert "ELIDIA_KEY" in message

    def test_rate_limit_is_marked_temporary(self):
        message = aiutils_client.handle_sdk_error(RateLimitError("slow down"), action="generation")
        assert "temporary" in message.lower()

    def test_scope_error_names_the_cause(self):
        message = aiutils_client.handle_sdk_error(ForbiddenError("no scope"), action="generation")
        assert "scope" in message.lower()

    def test_unrecognised_errors_fall_through(self):
        """Returning None lets the caller keep its own wording rather than
        mislabelling an unrelated failure."""
        assert aiutils_client.handle_sdk_error(ValueError("weird"), action="generation") is None


class TestToolsSurfaceItEndToEnd:
    def _client_raising(self, exc):
        class _Gen:
            def create(self, **kw):
                raise exc

        class _Wallet:
            def estimate_cost(self, model, parameters=None):
                return types.SimpleNamespace(estimated_dt=10)

            def balance(self):
                return types.SimpleNamespace(balance_dt=50_000)

        return types.SimpleNamespace(generations=_Gen(), wallet=_Wallet())

    def test_generate_relays_a_server_402(self, monkeypatch):
        """The guard passes (balance looks fine) and the SERVER still refuses —
        the exact race the client-side check cannot cover."""
        fake = self._client_raising(InsufficientDTError("Required: 900 DT, Available: 10 DT"))
        monkeypatch.setattr(aiutils_client, "get_client", lambda base_url=None: fake)

        result = json.loads(aiutils_generate._handle_generate({"model": "m"}))

        assert "Out of DT balance" in result["error"]
        assert "900 DT" in result["error"]

    def test_rag_search_relays_a_server_402(self, monkeypatch):
        class _RAG:
            def search(self, **kw):
                raise InsufficientDTError("Required: 40 DT, Available: 0 DT")

        monkeypatch.setattr(
            aiutils_client, "get_client",
            lambda base_url=None: types.SimpleNamespace(rag=_RAG()),
        )
        result = json.loads(aiutils_rag._handle_search({"query": "q"}))
        assert "Out of DT balance" in result["error"]

    def test_unrelated_failures_keep_their_own_wording(self, monkeypatch):
        fake = self._client_raising(RuntimeError("connection reset"))
        monkeypatch.setattr(aiutils_client, "get_client", lambda base_url=None: fake)

        result = json.loads(aiutils_generate._handle_generate({"model": "m"}))
        assert "Generation failed" in result["error"]
        assert "connection reset" in result["error"]

class TestDTWalletIsSeparateFromPortalCredits:
    """Owner directive 2026-08-23: the DT wallet lives on the Developer Console
    side only. It is unrelated to Portal credits, and is topped up in the
    Developer Console — never on a Portal billing page."""

    def test_top_up_points_at_the_developer_console(self):
        message = aiutils_client.handle_sdk_error(
            InsufficientDTError("out of DT"), action="generation"
        )
        assert "developer.aiutils.io" in message
        assert "portal.aiutils.io" not in message

    def test_message_states_the_separation(self):
        message = aiutils_client.handle_sdk_error(
            InsufficientDTError("out of DT"), action="generation"
        )
        assert "separate from Portal credits" in message

    def test_servers_own_top_up_url_wins_over_the_fallback(self):
        """The API knows where its billing lives; the constant is only a
        fallback for an older server that sends no details."""
        exc = InsufficientDTError(
            "short", required_dt=900, available_dt=10,
            top_up_url="https://developer.aiutils.io/billing/top-up?plan=pro",
        )
        message = aiutils_client.handle_sdk_error(exc, action="generation")
        assert "plan=pro" in message

    def test_shortfall_is_stated_when_the_server_supplies_it(self):
        exc = InsufficientDTError("short", required_dt=900, available_dt=10)
        assert exc.shortfall_dt == 890, "derived when not sent explicitly"
        message = aiutils_client.handle_sdk_error(exc, action="generation")
        assert "890 DT short" in message

    def test_older_style_error_without_details_still_works(self):
        """Backward compatibility: str(exc) is unchanged and nothing requires
        the new fields."""
        exc = InsufficientDTError("plain message")
        assert str(exc) == "plain message"
        assert exc.shortfall_dt is None
        assert "Out of DT balance" in aiutils_client.handle_sdk_error(exc, action="generation")
