"""Tests for the AiUtils GPU API provider plugin.

The plugin lives at ``plugins/model-providers/gpu-api/`` and is auto-discovered
by ``providers`` and auto-wired into ``elidia_cli.auth.PROVIDER_REGISTRY``
(api-key profiles with ``env_vars`` are extended automatically). These tests pin
that contract — the same surface as ``test_aiutils_provider.py``.
"""

import pytest

from providers import get_provider_profile, list_providers


def _gpu_profile():
    profile = get_provider_profile("gpu-api")
    assert profile is not None, "gpu-api provider profile not discovered"
    return profile


class TestGpuApiProviderProfile:
    def test_discovered_in_registry(self):
        names = {p.name for p in list_providers()}
        assert "gpu-api" in names

    def test_identity_fields(self):
        p = _gpu_profile()
        assert p.name == "gpu-api"
        assert p.auth_type == "api_key"
        assert p.api_mode == "chat_completions"

    def test_base_url_targets_api_v1(self):
        p = _gpu_profile()
        # Endpoints are mounted under /api/v1, so base_url must end there for
        # the transport to append /chat/completions correctly.
        assert p.base_url == "http://localhost:9000/api/v1"

    def test_env_vars(self):
        p = _gpu_profile()
        # The aiutils_gpu SDK's canonical env vars: key + base URL.
        assert p.env_vars == ("GPU_API_KEY", "GPU_API_URL")

    def test_aliases(self):
        p = _gpu_profile()
        assert get_provider_profile("aiutils-gpu") is p
        assert get_provider_profile("gpuapi") is p
        assert get_provider_profile("gpu") is p

    def test_streaming_enabled(self):
        # The GPU API streams chat via SSE on POST /chat/completions.
        p = _gpu_profile()
        assert p.supports_streaming is True

    def test_fallback_models_cover_verified_ollama_set(self):
        p = _gpu_profile()
        models = set(p.fallback_models)
        assert {"mistral:7b", "llama3.1:8b", "qwen2.5:7b"} <= models
        assert len(p.fallback_models) >= 5


class TestGpuApiAutoRegistration:
    def test_provider_registry_entry(self):
        from elidia_cli.auth import PROVIDER_REGISTRY

        cfg = PROVIDER_REGISTRY.get("gpu-api")
        assert cfg is not None
        assert cfg.auth_type == "api_key"
        assert cfg.inference_base_url == "http://localhost:9000/api/v1"
        # `GPU_API_URL` ends in `_URL`, so the registry auto-extends it as the
        # base_url override (mirrors LM_BASE_URL handling).
        assert cfg.api_key_env_vars == ("GPU_API_KEY",)
        assert cfg.base_url_env_var == "GPU_API_URL"

    def test_explicit_resolution(self):
        from elidia_cli import auth as auth_mod

        assert auth_mod.resolve_provider("gpu-api") == "gpu-api"
        assert auth_mod.resolve_provider("aiutils-gpu") == "gpu-api"

    def test_gpu_api_key_auto_resolves(self, monkeypatch):
        """Setting GPU_API_KEY auto-selects ``gpu-api`` (no other key set)."""
        from elidia_cli import auth as auth_mod

        monkeypatch.setattr(auth_mod, "_load_auth_store", lambda: {})
        for k in ("GPU_API_KEY", "ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY",
                  "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GLM_API_KEY", "ZAI_API_KEY",
                  "KIMI_API_KEY", "MINIMAX_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("GPU_API_KEY", "gpuapi-test")

        assert auth_mod.resolve_provider() == "gpu-api"


class TestGpuApiFetchModels:
    def test_maps_gpu_registry_shape(self, monkeypatch):
        """The GPU API returns ``{"models": [{id, slug, ...}]}`` — map id/slug/name."""
        p = _gpu_profile()

        import json
        import urllib.request

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({
                    "models": [
                        {"id": "mistral:7b", "slug": "mistral-7b"},
                        {"slug": "llama3.1:8b"},
                        {"name": "qwen2.5:7b"},
                    ]
                }).encode()

        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _Resp())

        assert p.fetch_models(api_key="gpuapi-test") == [
            "mistral:7b", "llama3.1:8b", "qwen2.5:7b",
        ]

    def test_maps_openai_shape(self, monkeypatch):
        p = _gpu_profile()

        import json
        import urllib.request

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"data": [{"id": "deepseek-r1:7b"}]}).encode()

        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _Resp())

        assert p.fetch_models(api_key="gpuapi-test") == ["deepseek-r1:7b"]

    def test_returns_none_on_unreachable(self, monkeypatch):
        p = _gpu_profile()

        import urllib.request

        def _boom(req, timeout=None):
            raise OSError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", _boom)

        assert p.fetch_models(api_key="gpuapi-test") is None
