"""Tests for the AiUtils Developer API provider plugin.

The plugin lives at ``plugins/model-providers/aiutils/`` and is auto-discovered
by ``providers`` and auto-wired into ``elidia_cli.auth.PROVIDER_REGISTRY``
(api-key profiles with ``env_vars`` are extended automatically — no manual
registry edit). These tests pin that contract.
"""

import pytest

from providers import get_provider_profile, list_providers


def _aiutils_profile():
    profile = get_provider_profile("aiutils")
    assert profile is not None, "aiutils provider profile not discovered"
    return profile


class TestAiUtilsProviderProfile:
    def test_discovered_in_registry(self):
        names = {p.name for p in list_providers()}
        assert "aiutils" in names

    def test_identity_fields(self):
        p = _aiutils_profile()
        assert p.name == "aiutils"
        assert p.auth_type == "api_key"
        assert p.api_mode == "chat_completions"

    def test_base_url_targets_v1_chat(self):
        p = _aiutils_profile()
        assert p.base_url == "https://developer-api.aiutils.io/v1"

    def test_env_vars(self):
        p = _aiutils_profile()
        # All three AiUtils Developer API key names resolve to this provider.
        assert p.env_vars == ("ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY")

    def test_api_version_header(self):
        p = _aiutils_profile()
        assert p.default_headers.get("API-Version") == "2026-07-01"

    def test_alias_resolves(self):
        p = _aiutils_profile()
        assert get_provider_profile("aiutils-dev") is p

    def test_fetch_models_returns_none(self):
        # The Developer API /v1/models lists generative + async research-agent
        # models, not chat-completion LLMs — so fetch must decline and let
        # callers fall back to fallback_models.
        p = _aiutils_profile()
        assert p.fetch_models(api_key="ak-dev-test-key") is None

    def test_fallback_models_cover_chat_vendors(self):
        p = _aiutils_profile()
        models = set(p.fallback_models)
        # Anthropic / DeepSeek / OpenAI chat models the gateway actually routes.
        assert {"claude-opus-5", "deepseek-v4-pro", "gpt-5.4"} <= models
        assert len(p.fallback_models) >= 10


class TestAiUtilsAutoRegistration:
    def test_provider_registry_entry(self):
        from elidia_cli.auth import PROVIDER_REGISTRY

        cfg = PROVIDER_REGISTRY.get("aiutils")
        assert cfg is not None
        assert cfg.name == "AiUtils Developer API"
        assert cfg.auth_type == "api_key"
        assert cfg.inference_base_url == "https://developer-api.aiutils.io/v1"
        assert cfg.api_key_env_vars == ("ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY")

    def test_provider_model_ids_falls_back(self):
        from elidia_cli.models import provider_model_ids

        ids = provider_model_ids("aiutils")
        assert "claude-opus-5" in ids
        assert "deepseek-v4-pro" in ids
        assert "gpt-5.4" in ids

    @pytest.mark.parametrize("var", ["ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY"])
    def test_any_aiutils_key_auto_resolves_to_aiutils(self, monkeypatch, var):
        """Setting any of the three Developer-API key names auto-selects ``aiutils``.

        Regression guard: ``ELIDIA_KEY`` / ``ELIDIA_API_KEY`` previously mapped to
        the OAuth ``elidia`` provider (or fell through to "no provider configured").
        They must resolve to the AiUtils Developer API (``aiutils``).
        """
        from elidia_cli import auth as auth_mod

        monkeypatch.setattr(auth_mod, "_load_auth_store", lambda: {})
        for k in ("ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY",
                  "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv(var, "ak-dev-test")

        assert auth_mod.resolve_provider() == "aiutils"


class TestAiUtilsLegacyProviderBridge:
    """The legacy elidia_cli.providers registry bridges plugin providers.

    Regression guard: ``get_provider('aiutils')`` / ``resolve_provider_full``
    used to return None (the plugin registry wasn't consulted), which made
    ``elidia model`` print "Unknown provider 'aiutils'" and fall back to
    auto-detect. The bridge must resolve ``aiutils`` to a real ProviderDef.
    """

    def test_get_provider_resolves_aiutils(self):
        from elidia_cli.providers import get_provider

        pdef = get_provider("aiutils")
        assert pdef is not None, "aiutils must bridge from the plugin registry"
        assert pdef.id == "aiutils"
        assert pdef.name == "AiUtils Developer API"
        assert pdef.transport == "openai_chat"
        assert pdef.base_url == "https://developer-api.aiutils.io/v1"
        assert pdef.api_key_env_vars == ("ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY")
        assert pdef.source == "plugin"

    def test_resolve_provider_full_resolves_aiutils(self):
        from elidia_cli.providers import resolve_provider_full

        pdef = resolve_provider_full("aiutils", None, None)
        assert pdef is not None
        assert pdef.id == "aiutils"

    def test_determine_api_mode_aiutils(self):
        from elidia_cli.providers import determine_api_mode

        assert determine_api_mode("aiutils") == "chat_completions"

    def test_unknown_provider_still_none(self):
        from elidia_cli.providers import get_provider, resolve_provider_full

        assert get_provider("nonexistent-xyz-provider") is None
        assert resolve_provider_full("nonexistent-xyz-provider", None, None) is None
