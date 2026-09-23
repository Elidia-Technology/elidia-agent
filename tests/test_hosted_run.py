"""Tests for the hosted gateway run entry point (config resolution + app build)."""

from pathlib import Path

import pytest

from gateway.hosted.run import (
    DEFAULT_PORT,
    DEFAULT_SCOPE,
    ConfigError,
    HostedGatewayConfig,
    build_app,
    load_config,
)

JWKS = "https://identity.example/.well-known/jwks.json"


def _env(**overrides):
    env = {
        "HOSTED_GATEWAY_JWKS_URL": JWKS,
        "HOSTED_GATEWAY_AUDIENCE": "aud",
        "HOSTED_GATEWAY_TENANTS_DIR": "/tmp/hosted-tenants",
    }
    env.update(overrides)
    return env


def test_requires_jwks_and_audience():
    with pytest.raises(ConfigError) as exc:
        load_config({})
    msg = str(exc.value)
    assert "HOSTED_GATEWAY_JWKS_URL" in msg
    assert "HOSTED_GATEWAY_AUDIENCE" in msg


def test_requires_audience_when_only_jwks_present():
    with pytest.raises(ConfigError):
        load_config({"HOSTED_GATEWAY_JWKS_URL": JWKS})


def test_applies_defaults():
    cfg = load_config(_env())
    assert cfg.jwks_url == JWKS
    assert cfg.audience == "aud"
    assert cfg.issuer == ""
    assert cfg.scope == DEFAULT_SCOPE
    assert cfg.host == "127.0.0.1"
    assert cfg.port == DEFAULT_PORT
    assert cfg.tenants_dir == Path("/tmp/hosted-tenants")
    assert cfg.backend_port_range == (48000, 49000)
    assert cfg.model_name == ""


def test_overrides():
    cfg = load_config(
        _env(
            HOSTED_GATEWAY_ISSUER="https://identity.example",
            HOSTED_GATEWAY_SCOPE="other:scope",
            HOSTED_GATEWAY_PORT="47123",
            HOSTED_GATEWAY_BACKEND_PORT_MIN="50000",
            HOSTED_GATEWAY_BACKEND_PORT_MAX="50100",
            API_SERVER_MODEL_NAME="some-model",
        )
    )
    assert cfg.issuer == "https://identity.example"
    assert cfg.scope == "other:scope"
    assert cfg.port == 47123
    assert cfg.backend_port_range == (50000, 50100)
    assert cfg.model_name == "some-model"


def test_rejects_non_integer_port():
    with pytest.raises(ConfigError) as exc:
        load_config(_env(HOSTED_GATEWAY_PORT="not-a-port"))
    assert "HOSTED_GATEWAY_PORT" in str(exc.value)


def test_rejects_inverted_port_range():
    with pytest.raises(ConfigError):
        load_config(
            _env(
                HOSTED_GATEWAY_BACKEND_PORT_MIN="60000",
                HOSTED_GATEWAY_BACKEND_PORT_MAX="50000",
            )
        )


def test_rejects_out_of_range_port():
    with pytest.raises(ConfigError):
        load_config(
            _env(
                HOSTED_GATEWAY_BACKEND_PORT_MIN="1",
                HOSTED_GATEWAY_BACKEND_PORT_MAX="70000",
            )
        )


def test_build_app_registers_proxy_route(tmp_path):
    cfg = HostedGatewayConfig(
        jwks_url=JWKS,
        audience="aud",
        tenants_dir=tmp_path / "tenants",
    )
    app = build_app(cfg)
    routes = list(app.router.routes())
    assert len(routes) == 1
    assert routes[0].method == "*"


def test_provision_pair_parses_when_both_set():
    cfg = load_config(
        _env(
            HOSTED_GATEWAY_PROVISION_URL="http://portal.internal/api/keys/internal/provision",
            PROVISION_INTERNAL_TOKEN="prov-secret",
        )
    )
    assert cfg.provision_url == "http://portal.internal/api/keys/internal/provision"
    assert cfg.provision_token == "prov-secret"


def test_provision_pair_defaults_to_empty():
    cfg = load_config(_env())
    assert cfg.provision_url == ""
    assert cfg.provision_token == ""


def test_provision_url_without_token_is_rejected():
    with pytest.raises(ConfigError) as exc:
        load_config(_env(HOSTED_GATEWAY_PROVISION_URL="http://portal.internal/"))
    assert "PROVISION_INTERNAL_TOKEN" in str(exc.value)


def test_provision_token_without_url_is_rejected():
    with pytest.raises(ConfigError) as exc:
        load_config(_env(PROVISION_INTERNAL_TOKEN="prov-secret"))
    assert "HOSTED_GATEWAY_PROVISION_URL" in str(exc.value)
