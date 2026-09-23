"""Unit tests for the portal-only media tools (AIUT-3286).

``generate_3d`` and ``list_media_models`` exist only in portal provider mode:
their ``check_fn`` returns False outside it, ``generate_3d``'s handler returns
a clear error (the proxy intercepts it in portal mode), and
``list_media_models`` is a read-only pass-through to ``fetch_media_models``.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def module():
    import importlib
    import tools.portal_media_tools as mod
    importlib.reload(mod)
    return mod


def test_check_fn_returns_false_when_not_portal_mode(module):
    assert module.check_portal_media_requirements() is False


def test_generate_3d_handler_errors_without_prompt(module):
    # tool_error returns {"error": "..."} (no `success` key).
    result = json.loads(module._handle_generate_3d({"prompt": ""}))
    assert "prompt is required" in result["error"]


def test_generate_3d_handler_errors_in_non_portal_mode(module):
    # Without the proxy intercepting, the handler must fail clearly (no native 3D).
    result = json.loads(module._handle_generate_3d({"prompt": "a dragon"}))
    assert result["success"] is False
    assert "portal" in result["error"].lower()


def test_generate_3d_schema_shape(module):
    assert module.GENERATE_3D_SCHEMA["name"] == "generate_3d"
    assert "prompt" in module.GENERATE_3D_SCHEMA["parameters"]["properties"]
    assert "model" in module.GENERATE_3D_SCHEMA["parameters"]["properties"]
    assert module.GENERATE_3D_SCHEMA["parameters"]["required"] == ["prompt"]


def test_list_media_models_returns_catalog(module, monkeypatch):
    fake = {"image": [{"id": "fal-ai/flux-2-pro", "tier": "premium"}], "video": [], "audio": [], "3d": []}
    monkeypatch.setattr(
        "tools.portal_tool_proxy.fetch_media_models", lambda: fake
    )
    result = json.loads(module._handle_list_media_models({}))
    assert result["media_models"] == fake


def test_list_media_models_filters_by_media_type(module, monkeypatch):
    fake = {"image": [{"id": "i"}], "video": [{"id": "v"}], "audio": [], "3d": []}
    monkeypatch.setattr(
        "tools.portal_tool_proxy.fetch_media_models", lambda: fake
    )
    result = json.loads(module._handle_list_media_models({"media_type": "video"}))
    assert result["media_models"] == {"video": [{"id": "v"}]}


def test_list_media_models_errors_when_portal_unreachable(module, monkeypatch):
    monkeypatch.setattr(
        "tools.portal_tool_proxy.fetch_media_models", lambda: None
    )
    result = module._handle_list_media_models({})
    # tool_error returns an error string, not a {"media_models": ...} blob.
    assert "Could not load" in result
