"""Tests for the interactive-tool handoff (B9).

The behaviour under test: a tool that needs a human at a canvas must never be
pushed through headless execution, and the link the user gets must be one they
can actually click on whatever surface they are using.
"""

import json
import types

import pytest

from tools import aiutils_redirect, aiutils_tool, run_context


CATALOG = {
    "genres": {
        "image": {
            "label": "Image",
            "tools": [
                {"slug": "image-editor", "name": "Image Editor",
                 "execution_mode": "redirect", "output_type": "image",
                 "description": "Layers, masks and live preview."},
                {"slug": "bg-remove", "name": "Background Remover",
                 "execution_mode": "call", "output_type": "image"},
            ],
        },
        "audio_media": {
            "label": "Audio",
            "tools": [
                {"slug": "music-studio", "name": "AI Music Studio",
                 "execution_mode": "redirect", "output_type": "audio"},
            ],
        },
    }
}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    aiutils_redirect._catalog_cache["tools"] = {}
    aiutils_redirect._catalog_cache["fetched_at"] = 0.0
    monkeypatch.delenv(aiutils_redirect.PORTAL_WEB_URL_ENV, raising=False)
    token = run_context.set_run_context(None)
    yield
    run_context._run_context.reset(token)
    aiutils_redirect._catalog_cache["tools"] = {}
    aiutils_redirect._catalog_cache["fetched_at"] = 0.0


def _client(payload=CATALOG, calls=None):
    class _Tools:
        def genres(self):
            if calls is not None:
                calls.append(1)
            if isinstance(payload, Exception):
                raise payload
            return payload

        def execute(self, slug, **params):
            raise AssertionError(f"execute() must not be called for {slug}")

    return types.SimpleNamespace(tools=_Tools())


class TestUrlBuilding:
    def test_url_is_absolute(self):
        assert aiutils_redirect.tool_url("image-editor") == (
            "https://aiutils.io/tools/image-editor"
        )

    def test_server_supplied_relative_path_is_made_absolute(self):
        """A site-relative path is meaningless in a terminal or a chat message;
        there is no origin there to resolve it against."""
        assert aiutils_redirect.tool_url("x", "/tools/x") == "https://aiutils.io/tools/x"

    def test_server_supplied_absolute_url_wins_untouched(self):
        assert aiutils_redirect.tool_url(
            "x", "https://staging.aiutils.io/studio/x"
        ) == "https://staging.aiutils.io/studio/x"

    def test_portal_origin_is_overridable(self, monkeypatch):
        monkeypatch.setenv(aiutils_redirect.PORTAL_WEB_URL_ENV, "https://staging.aiutils.io/")
        assert aiutils_redirect.tool_url("y") == "https://staging.aiutils.io/tools/y"


class TestModeDetection:
    def test_redirect_tool_is_detected(self):
        assert aiutils_redirect.is_redirect_tool("image-editor", client=_client()) is True

    def test_call_tool_is_not_a_redirect(self):
        assert aiutils_redirect.is_redirect_tool("bg-remove", client=_client()) is False

    def test_unknown_tool_is_not_treated_as_redirect(self):
        """An unreachable or incomplete catalog must not start blocking tools
        that were working — unknown means unknown, not 'needs a browser'."""
        assert aiutils_redirect.is_redirect_tool("who-knows", client=_client()) is False

    def test_catalog_failure_does_not_raise(self):
        broken = _client(payload=RuntimeError("gateway down"))
        assert aiutils_redirect.load_catalog(client=broken) == {}
        assert aiutils_redirect.is_redirect_tool("image-editor", client=broken) is False

    def test_catalog_is_cached_not_refetched_per_lookup(self):
        calls = []
        client = _client(calls=calls)
        for _ in range(5):
            aiutils_redirect.is_redirect_tool("image-editor", client=client)
        assert len(calls) == 1, "the catalog must not be fetched once per lookup"

    def test_malformed_catalog_entries_are_skipped(self):
        payload = {"genres": {"a": {"tools": [None, {"no_slug": 1}, {"slug": "ok"}]}, "b": "nope"}}
        assert list(aiutils_redirect.load_catalog(client=_client(payload))) == ["ok"]


class TestChannelAwareRendering:
    def test_terminal_gets_a_plain_clickable_url(self):
        msg = aiutils_redirect.format_handoff("image-editor", name="Image Editor", platform="cli")
        assert "https://aiutils.io/tools/image-editor" in msg
        assert "\x1b" not in msg, "escape sequences would print as noise in a plain terminal"

    def test_remote_channels_get_no_terminal_formatting(self):
        # Real platforms from gateway/platforms/, plus one that does not exist
        # yet: an unknown platform must be treated as remote, not as a terminal.
        for channel in ("telegram", "whatsapp", "slack", "signal", "sms",
                        "dingtalk", "some-platform-added-next-year"):
            msg = aiutils_redirect.format_handoff("music-studio", platform=channel)
            assert "https://aiutils.io/tools/music-studio" in msg
            assert "\x1b" not in msg

    def test_programmatic_callers_get_a_parseable_line(self):
        msg = aiutils_redirect.format_handoff("image-editor", platform="api_server")
        assert msg == "OPEN_TOOL image-editor https://aiutils.io/tools/image-editor"

    def test_channel_is_taken_from_the_run_context_when_not_passed(self):
        run_context.set_run_context(run_context.RunContext(platform="api_server"))
        assert aiutils_redirect.format_handoff("image-editor").startswith("OPEN_TOOL")

    def test_unknown_platform_defaults_to_the_remote_wording(self):
        """Fails in the safe direction: a platform added to gateway/platforms/
        tomorrow gets browser wording, not 'open it here' as if the user were
        sitting at this machine."""
        msg = aiutils_redirect.format_handoff("image-editor", platform="qqbot")
        assert "opens in your browser" in msg

    def test_no_run_context_falls_back_to_prose(self):
        msg = aiutils_redirect.format_handoff("image-editor")
        assert not msg.startswith("OPEN_TOOL")
        assert "https://aiutils.io/tools/image-editor" in msg


class TestExecuteHandoff:
    def test_execute_hands_off_instead_of_calling_a_studio(self, monkeypatch):
        """The point of the ticket: a redirect tool must not be POSTed to
        /execute, where it can only fail."""
        client = _client()   # its execute() asserts if reached
        monkeypatch.setattr(aiutils_redirect, "load_catalog",
                            lambda **kw: {t["slug"]: t for t in
                                          aiutils_redirect._iter_catalog_tools(CATALOG)})

        result = json.loads(aiutils_tool._handle_execute({"tool_slug": "image-editor"}))

        assert result["action"] == "open_url"
        assert result["url"] == "https://aiutils.io/tools/image-editor"
        assert result["name"] == "Image Editor"

    def test_handoff_happens_before_the_wallet_is_read(self, monkeypatch):
        """A balance check for work that cannot happen is a round trip spent to
        reach the same refusal — and it would refuse on an empty wallet, hiding
        the link behind a billing error for a page that costs nothing."""
        monkeypatch.setattr(aiutils_redirect, "load_catalog",
                            lambda **kw: {t["slug"]: t for t in
                                          aiutils_redirect._iter_catalog_tools(CATALOG)})

        def _must_not_run(*a, **kw):
            raise AssertionError("credit guard ran for a page that costs nothing")

        monkeypatch.setattr(aiutils_tool.aiutils_client, "check_spend_allowed", _must_not_run)
        result = json.loads(aiutils_tool._handle_execute({"tool_slug": "music-studio"}))
        assert result["action"] == "open_url"

    def test_call_tools_still_execute_normally(self, monkeypatch):
        monkeypatch.setattr(aiutils_redirect, "load_catalog",
                            lambda **kw: {t["slug"]: t for t in
                                          aiutils_redirect._iter_catalog_tools(CATALOG)})

        class _Tools:
            def execute(self, slug, **params):
                return {"ran": slug, "params": params}

        monkeypatch.setattr(
            aiutils_tool.aiutils_client, "check_spend_allowed",
            lambda **kw: {"ok": True, "client": types.SimpleNamespace(tools=_Tools())},
        )
        result = json.loads(aiutils_tool._handle_execute(
            {"tool_slug": "bg-remove", "inputs": {"image": "x.png"}}
        ))
        assert result == {"ran": "bg-remove", "params": {"image": "x.png"}}

    def test_catalog_outage_does_not_block_a_call_tool(self, monkeypatch):
        monkeypatch.setattr(aiutils_redirect, "load_catalog",
                            lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))

        class _Tools:
            def execute(self, slug, **params):
                return {"ran": slug}

        monkeypatch.setattr(
            aiutils_tool.aiutils_client, "check_spend_allowed",
            lambda **kw: {"ok": True, "client": types.SimpleNamespace(tools=_Tools())},
        )
        assert json.loads(aiutils_tool._handle_execute({"tool_slug": "bg-remove"})) == {
            "ran": "bg-remove"
        }


class TestOpenToolTool:
    def test_open_tool_returns_a_payload_a_gui_can_use(self, monkeypatch):
        monkeypatch.setattr(aiutils_redirect, "load_catalog",
                            lambda **kw: {t["slug"]: t for t in
                                          aiutils_redirect._iter_catalog_tools(CATALOG)})
        result = json.loads(aiutils_tool._handle_open_tool({"tool_slug": "image-editor"}))

        # url separate from message, so desktop/VS Code/mobile can put it on a
        # button rather than printing it into a chat bubble.
        assert result["url"] == "https://aiutils.io/tools/image-editor"
        assert result["message"] and result["url"] in result["message"]
        assert result["output_type"] == "image"

    def test_open_tool_requires_a_slug(self):
        assert "required" in aiutils_tool._handle_open_tool({"tool_slug": "  "}).lower()

    def test_unknown_slug_still_yields_a_usable_link(self, monkeypatch):
        """The catalog can lag a newly shipped tool. A link built from the known
        route beats refusing to answer."""
        monkeypatch.setattr(aiutils_redirect, "load_catalog", lambda **kw: {})
        result = json.loads(aiutils_tool._handle_open_tool({"tool_slug": "brand-new"}))
        assert result["url"] == "https://aiutils.io/tools/brand-new"

    def test_tool_is_registered_in_the_aiutils_toolset(self):
        from tools.registry import registry

        assert "aiutils_open_tool" in registry.get_all_tool_names()
        assert registry.get_toolset_for_tool("aiutils_open_tool") == "aiutils"


class TestPromptGuidance:
    """The model has to reach for the tool for it to matter. The portal ships a
    system-prompt rule for exactly this reason — tool descriptions alone were
    not enough to stop models recommending Photoshop."""

    def _guidance_for(self, tool_names):
        import types as _t

        from agent import system_prompt

        agent = _t.SimpleNamespace(
            valid_tool_names=set(tool_names), model="test", _task_completion_guidance=False,
            _tool_use_enforcement=False, _kanban_worker_guidance=None, _memory_store=None,
        )
        from agent.prompt_builder import AIUTILS_OPEN_TOOL_GUIDANCE

        return AIUTILS_OPEN_TOOL_GUIDANCE, agent, system_prompt

    def test_guidance_names_the_tools_not_a_hardcoded_catalog(self):
        """Not a copy of the portal rule, which inlines ~40 tool URLs: fetching
        the catalog at prompt-build time would block on the network and change
        the cached prefix every time a tool ships."""
        from agent.prompt_builder import AIUTILS_OPEN_TOOL_GUIDANCE

        assert "aiutils_open_tool" in AIUTILS_OPEN_TOOL_GUIDANCE
        assert "aiutils_tool_genres" in AIUTILS_OPEN_TOOL_GUIDANCE
        assert "https://" not in AIUTILS_OPEN_TOOL_GUIDANCE, "no baked-in URLs"

    def test_guidance_is_gated_on_the_toolset_being_loaded(self):
        """A stock Elidia install has no portal catalog; guidance for tools that
        are not there invites calls the model cannot make."""
        import inspect

        from agent import system_prompt

        src = inspect.getsource(system_prompt)
        assert 'if "aiutils_open_tool" in agent.valid_tool_names:' in src
