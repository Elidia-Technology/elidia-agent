"""Auxiliary calls must identify the portal user (AIUT-3310).

The portal resolves the billing user from `X-Portal-User-Id` and authenticates
with `X-Gateway-Token`. The main client sets both; the auxiliary client — used
by `vision_analyze` — did not, so the portal answered

    400 user_id required (body field or X-Portal-User-Id header)

and the agent reported to the user that it could not see their attached image.
"""
from __future__ import annotations

import pytest

from agent.auxiliary_client import _portal_default_headers


class TestPortalHeaders:

    def test_gateway_token_is_sent(self):
        assert _portal_default_headers("tok-123")["X-Gateway-Token"] == "tok-123"

    def test_no_token_yields_no_token_header(self):
        assert "X-Gateway-Token" not in _portal_default_headers("")

    def test_user_id_comes_from_the_session(self, monkeypatch):
        import gateway.session_context as sc

        monkeypatch.setattr(
            sc, "get_session_env",
            lambda key, default="": "4" if key == "ELIDIA_SESSION_USER_ID" else default,
        )
        assert _portal_default_headers("tok")["X-Portal-User-Id"] == "4"

    def test_absent_session_user_is_omitted_not_faked(self, monkeypatch):
        import gateway.session_context as sc

        monkeypatch.setattr(sc, "get_session_env", lambda key, default="": "")
        assert "X-Portal-User-Id" not in _portal_default_headers("tok")

    def test_never_raises(self, monkeypatch):
        """This runs while building a client mid-conversation."""
        import gateway.session_context as sc

        def boom(key, default=""):
            raise RuntimeError("no session")

        monkeypatch.setattr(sc, "get_session_env", boom)
        out = _portal_default_headers("tok")
        assert out == {"X-Gateway-Token": "tok"}, (
            "a session-context failure must not take down the tool being run"
        )


class TestWiring:
    """The bug was a missing branch, so pin both construction sites."""

    def test_both_auxiliary_sites_handle_the_portal_provider(self):
        from pathlib import Path

        src = Path("agent/auxiliary_client.py").read_text()
        assert src.count('elif provider_id == "portal":') == 2
        assert src.count("_portal_default_headers(api_key)") == 2


class TestClientFunnelInjection:
    """`vision_analyze` builds its client through `resolve_vision_provider_client`,
    not the provider pool, so fixing the pool sites alone left it broken. This
    module has 14 `OpenAI(...)` construction sites; they all pass through the
    module's lazy proxy, which is where the headers are added.
    """

    def _inject(self, **kwargs):
        from agent.auxiliary_client import _inject_portal_headers
        _inject_portal_headers(kwargs)
        return kwargs

    def test_a_portal_client_gets_the_headers(self, monkeypatch):
        import gateway.session_context as sc
        monkeypatch.setattr(
            sc, "get_session_env",
            lambda key, default="": "4" if key == "ELIDIA_SESSION_USER_ID" else default,
        )
        out = self._inject(api_key="tok", base_url="http://127.0.0.1:8000/agent-v2/v1")
        assert out["default_headers"]["X-Portal-User-Id"] == "4"
        assert out["default_headers"]["X-Gateway-Token"] == "tok"

    def test_a_non_portal_client_is_untouched(self):
        out = self._inject(api_key="sk-x", base_url="https://api.openai.com/v1")
        assert "default_headers" not in out

    def test_no_base_url_is_untouched(self):
        assert "default_headers" not in self._inject(api_key="sk-x")

    def test_existing_headers_are_never_overridden(self, monkeypatch):
        import gateway.session_context as sc
        monkeypatch.setattr(sc, "get_session_env", lambda key, default="": "4")
        out = self._inject(
            api_key="tok",
            base_url="http://127.0.0.1:8000/agent-v2/v1",
            default_headers={"X-Portal-User-Id": "99", "X-Custom": "keep"},
        )
        assert out["default_headers"]["X-Portal-User-Id"] == "99", "caller wins"
        assert out["default_headers"]["X-Custom"] == "keep"

    def test_injection_never_raises(self, monkeypatch):
        """It runs on every client construction in this module."""
        import agent.auxiliary_client as ac
        monkeypatch.setattr(ac, "_portal_default_headers", lambda k: 1 / 0)
        out = self._inject(api_key="tok", base_url="http://127.0.0.1:8000/agent-v2/v1")
        assert "default_headers" not in out

    def test_the_proxy_calls_the_injector(self):
        from pathlib import Path
        src = Path("agent/auxiliary_client.py").read_text()
        call = src[src.index("class _OpenAIProxy:"):]
        call = call[: call.index("def __instancecheck__")]
        assert "_inject_portal_headers(kwargs)" in call


class TestAsyncClientKeepsPortalHeaders:
    """The async client is rebuilt from the sync client's key and base url and
    reconstructs `default_headers` from scratch, dropping anything the sync
    client carried. `vision_analyze` runs on the async client, so it kept
    failing after every sync-side fix.
    """

    def test_the_async_builder_injects_before_constructing(self):
        from pathlib import Path

        src = Path("agent/auxiliary_client.py").read_text()
        tail = src[: src.index("return AsyncOpenAI(**async_kwargs), model")]
        assert "_inject_portal_headers(async_kwargs)" in tail[-600:], (
            "portal headers must be re-applied on the async client"
        )

    def test_injection_is_applied_to_async_kwargs_shape(self, monkeypatch):
        import gateway.session_context as sc
        from agent.auxiliary_client import _inject_portal_headers

        monkeypatch.setattr(sc, "get_session_env", lambda key, default="": "4")
        kwargs = {"api_key": "tok", "base_url": "http://127.0.0.1:8000/agent-v2/v1"}
        _inject_portal_headers(kwargs)
        assert kwargs["default_headers"] == {
            "X-Portal-User-Id": "4", "X-Gateway-Token": "tok",
        }
