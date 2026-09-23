"""Tests for the hosted gateway run module (AIUT-3078 B5).

Verifies config loading, validation, and app building.
"""

import pytest

from gateway.hosted.run import (
    ConfigError,
    HostedGatewayConfig,
    load_config,
    build_app,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCOPE,
    DEFAULT_MAX_WORKERS,
)


# ═══════════════════════════════════════════════════════════════════════
# Config loading
# ═══════════════════════════════════════════════════════════════════════


class TestLoadConfig:

    _BASE_ENV = {
        "HOSTED_GATEWAY_JWKS_URL": "https://auth.example.com/.well-known/jwks.json",
        "HOSTED_GATEWAY_AUDIENCE": "agent-v2",
    }

    def test_minimal_valid_config(self):
        cfg = load_config(self._BASE_ENV)
        assert cfg.jwks_url == "https://auth.example.com/.well-known/jwks.json"
        assert cfg.audience == "agent-v2"
        assert cfg.host == DEFAULT_HOST
        assert cfg.port == DEFAULT_PORT
        assert cfg.max_workers == DEFAULT_MAX_WORKERS
        assert cfg.scope == DEFAULT_SCOPE

    def test_missing_jwks_url_raises(self):
        with pytest.raises(ConfigError, match="HOSTED_GATEWAY_JWKS_URL"):
            load_config({"HOSTED_GATEWAY_AUDIENCE": "aud"})

    def test_missing_audience_raises(self):
        with pytest.raises(ConfigError, match="HOSTED_GATEWAY_AUDIENCE"):
            load_config({"HOSTED_GATEWAY_JWKS_URL": "https://x"})

    def test_custom_port(self):
        env = {**self._BASE_ENV, "HOSTED_GATEWAY_PORT": "9000"}
        cfg = load_config(env)
        assert cfg.port == 9000

    def test_invalid_port_raises(self):
        env = {**self._BASE_ENV, "HOSTED_GATEWAY_PORT": "not-a-number"}
        with pytest.raises(ConfigError, match="integer"):
            load_config(env)

    def test_custom_max_workers(self):
        env = {**self._BASE_ENV, "HOSTED_GATEWAY_MAX_WORKERS": "16"}
        cfg = load_config(env)
        assert cfg.max_workers == 16

    def test_provision_url_without_token_raises(self):
        env = {**self._BASE_ENV, "HOSTED_GATEWAY_PROVISION_URL": "http://x"}
        with pytest.raises(ConfigError, match="together"):
            load_config(env)

    def test_provision_token_without_url_raises(self):
        env = {**self._BASE_ENV, "PROVISION_INTERNAL_TOKEN": "secret"}
        with pytest.raises(ConfigError, match="together"):
            load_config(env)

    def test_provision_both_set(self):
        env = {
            **self._BASE_ENV,
            "HOSTED_GATEWAY_PROVISION_URL": "http://x",
            "PROVISION_INTERNAL_TOKEN": "secret",
        }
        cfg = load_config(env)
        assert cfg.provision_url == "http://x"
        assert cfg.provision_token == "secret"

    def test_model_name_from_env(self):
        env = {**self._BASE_ENV, "API_SERVER_MODEL_NAME": "elidia-agent-v2"}
        cfg = load_config(env)
        assert cfg.model_name == "elidia-agent-v2"

    def test_cors_origins_from_env(self):
        env = {**self._BASE_ENV, "API_SERVER_CORS_ORIGINS": "https://app.example.com"}
        cfg = load_config(env)
        assert cfg.cors_origins == "https://app.example.com"


# ═══════════════════════════════════════════════════════════════════════
# App building
# ═══════════════════════════════════════════════════════════════════════


class TestBuildApp:

    def test_build_app_returns_web_application(self):
        cfg = HostedGatewayConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            audience="agent-v2",
        )
        app = build_app(cfg)
        assert isinstance(app, __import__("aiohttp").web.Application)
        app["worker_pool"].shutdown()

    def test_build_app_has_worker_pool(self):
        cfg = HostedGatewayConfig(
            jwks_url="https://x",
            audience="y",
            max_workers=4,
        )
        app = build_app(cfg)
        pool = app["worker_pool"]
        h = pool.health()
        assert h["pool_size"] == 4
        pool.shutdown()

    def test_build_app_has_api_server_adapter(self):
        cfg = HostedGatewayConfig(
            jwks_url="https://x",
            audience="y",
        )
        app = build_app(cfg)
        from gateway.platforms.api_server import APIServerAdapter
        assert isinstance(app["api_server_adapter"], APIServerAdapter)
        app["worker_pool"].shutdown()

    def test_build_app_api_server_is_gateway_trusted(self):
        cfg = HostedGatewayConfig(
            jwks_url="https://x",
            audience="y",
        )
        app = build_app(cfg)
        adapter = app["api_server_adapter"]
        assert adapter._gateway_trusted is True
        app["worker_pool"].shutdown()
