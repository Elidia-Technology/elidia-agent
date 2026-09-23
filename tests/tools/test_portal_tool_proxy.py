"""Unit tests for ``tools.portal_tool_proxy`` mapping + catalog fetch.

AIUT-3286 — the proxy must forward an explicit ``model`` (the FAL endpoint_id
the user picked from ``list_media_models``) to the portal's media tools, and
must map ``generate_3d`` so 3D generation is billed to portal credits. These
tests pin the pure mapping/formatting functions and the read-only catalog
fetch without any network or portal-mode config.
"""
from __future__ import annotations

import json

import pytest

from tools import portal_tool_proxy as px


# ── Tool-name mapping ───────────────────────────────────────────────


def test_map_tool_name_maps_all_four_media_tools():
    assert px._map_tool_name("image_generate") == "generate_image"
    assert px._map_tool_name("video_generate") == "generate_video"
    assert px._map_tool_name("text_to_speech") == "generate_audio"
    assert px._map_tool_name("generate_3d") == "generate_3d"
    assert px._map_tool_name("web_search") is None


def test_proxied_tools_includes_generate_3d():
    assert "generate_3d" in px._PROXIED_TOOLS
    assert {"image_generate", "video_generate", "text_to_speech", "generate_3d"} <= px._PROXIED_TOOLS


# ── Argument mapping (model pass-through) ───────────────────────────


def test_map_arguments_forwards_explicit_model_for_image():
    args = {"prompt": "a cat", "aspect_ratio": "portrait", "model": "fal-ai/flux-2-pro"}
    mapped = px._map_arguments("image_generate", args)
    assert mapped["model"] == "fal-ai/flux-2-pro"
    assert mapped["prompt"] == "a cat"
    assert mapped["aspect_ratio"] == "portrait"
    assert mapped["quality"] == "standard"


def test_map_arguments_omits_model_when_absent():
    mapped = px._map_arguments("image_generate", {"prompt": "a cat"})
    assert "model" not in mapped


def test_map_arguments_for_video_and_tts_and_3d():
    assert px._map_arguments("video_generate", {"prompt": "p", "model": "m1"})["model"] == "m1"
    # text_to_speech: text -> prompt, and model forwarded
    tts = px._map_arguments("text_to_speech", {"text": "hello", "model": "m2", "audio_type": "music"})
    assert tts["prompt"] == "hello"
    assert tts["model"] == "m2"
    assert tts["audio_type"] == "music"
    assert px._map_arguments("generate_3d", {"prompt": "p", "model": "m3"})["model"] == "m3"


def test_map_arguments_unknown_tool_returns_args_unchanged():
    args = {"query": "x"}
    assert px._map_arguments("web_search", args) == args


# ── Result formatting ───────────────────────────────────────────────


def test_format_result_for_generate_3d():
    result = px._format_result("generate_3d", {"status": "completed", "urls": ["https://cdn/m.glb"]})
    parsed = json.loads(result)
    assert parsed["success"] is True
    assert parsed["model_3d"] == "https://cdn/m.glb"


def test_format_result_error():
    result = px._format_result("image_generate", {"status": "error", "error": "Insufficient credits"})
    parsed = json.loads(result)
    assert parsed["success"] is False
    assert parsed["error"] == "Insufficient credits"


# ── fetch_media_models ──────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        return self._body


def test_fetch_media_models_returns_data_on_200(monkeypatch):
    monkeypatch.setattr(px, "_is_portal_mode", lambda: True)
    monkeypatch.setattr(px, "_get_gateway_token", lambda: "tok")
    captured = {}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResponse(200, body={"data": {"image": [{"id": "x"}]}})

    import httpx
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    data = px.fetch_media_models()
    assert data == {"image": [{"id": "x"}]}
    assert captured["url"].endswith("/agent-v2/v1/media/models")
    assert captured["headers"]["X-Gateway-Token"] == "tok"


def test_fetch_media_models_returns_none_when_not_portal_mode(monkeypatch):
    monkeypatch.setattr(px, "_is_portal_mode", lambda: False)
    assert px.fetch_media_models() is None


def test_fetch_media_models_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(px, "_is_portal_mode", lambda: True)
    monkeypatch.setattr(px, "_get_gateway_token", lambda: "tok")

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers):
            return _FakeResponse(500, body=None, text="boom")

    import httpx
    monkeypatch.setattr(httpx, "Client", _FakeClient)

    assert px.fetch_media_models() is None


def test_fetch_media_models_returns_none_on_exception(monkeypatch):
    monkeypatch.setattr(px, "_is_portal_mode", lambda: True)
    monkeypatch.setattr(px, "_get_gateway_token", lambda: "tok")

    def _boom(*a, **k):
        raise RuntimeError("unreachable")

    import httpx
    monkeypatch.setattr(httpx, "Client", _boom)

    assert px.fetch_media_models() is None


# ── credits_used forwarding (AIUT-3292) ──────────────────────────────
# The four media branches used to build their payload from `urls` only, so the
# portal's `credits_used` was dropped and the agent could never tell the user
# what a generation cost.


@pytest.mark.parametrize(
    "gateway_name,media_key",
    [
        ("image_generate", "image"),
        ("video_generate", "video"),
        ("text_to_speech", "audio"),
        ("generate_3d", "model_3d"),
    ],
)
def test_format_result_forwards_credits_used(gateway_name, media_key):
    result = json.loads(
        px._format_result(
            gateway_name,
            {
                "status": "completed",
                "urls": ["https://cdn/out.bin"],
                "credits_used": 0.324,
            },
        )
    )
    assert result["success"] is True
    assert result[media_key] == "https://cdn/out.bin"
    assert result["credits_used"] == 0.324


def test_format_result_preserves_five_decimal_credits():
    """Sub-cent charges must survive the gateway hop, not be rounded away."""
    result = json.loads(
        px._format_result(
            "image_generate",
            {"status": "completed", "urls": ["https://cdn/a.png"], "credits_used": 0.00001},
        )
    )
    assert result["credits_used"] == 0.00001


@pytest.mark.parametrize(
    "gateway_name,media_key",
    [
        ("image_generate", "image"),
        ("video_generate", "video"),
        ("text_to_speech", "audio"),
        ("generate_3d", "model_3d"),
    ],
)
def test_format_result_omits_credits_used_when_absent(gateway_name, media_key):
    """No bare `null` should leak into the agent's context."""
    result = json.loads(
        px._format_result(
            gateway_name, {"status": "completed", "urls": ["https://cdn/out.bin"]}
        )
    )
    assert result["success"] is True
    assert result[media_key] == "https://cdn/out.bin"
    assert "credits_used" not in result


def test_format_result_error_still_has_no_credits():
    result = json.loads(
        px._format_result(
            "image_generate", {"status": "error", "error": "Insufficient credits"}
        )
    )
    assert result["success"] is False
    assert "credits_used" not in result


# ── Multi-asset results (AIUT-3307) ─────────────────────────────────
#
# `_media_payload` used to keep only `urls[0]`, so a generation that returned
# four images could never show more than one to the user, no matter what the
# UI did.


def test_format_result_carries_every_url_when_there_are_several():
    result = json.loads(
        px._format_result(
            "image_generate",
            {
                "status": "completed",
                "urls": [
                    "https://cdn/a.jpg",
                    "https://cdn/b.jpg",
                    "https://cdn/c.jpg",
                    "https://cdn/d.jpg",
                ],
            },
        )
    )
    assert result["image"] == "https://cdn/a.jpg", "single-url key stays first url"
    assert result["urls"] == [
        "https://cdn/a.jpg",
        "https://cdn/b.jpg",
        "https://cdn/c.jpg",
        "https://cdn/d.jpg",
    ]


def test_format_result_omits_urls_list_for_a_single_asset():
    """One asset needs no list; the existing single key already says it all."""
    result = json.loads(
        px._format_result("video_generate", {"status": "completed", "urls": ["https://cdn/v.mp4"]})
    )
    assert result["video"] == "https://cdn/v.mp4"
    assert "urls" not in result


def test_format_result_forwards_model_when_portal_reports_one():
    result = json.loads(
        px._format_result(
            "image_generate",
            {"status": "completed", "urls": ["https://cdn/a.jpg"], "model": "fal/flux-schnell"},
        )
    )
    assert result["model"] == "fal/flux-schnell"


def test_format_result_omits_model_when_portal_does_not_report_one():
    result = json.loads(
        px._format_result("image_generate", {"status": "completed", "urls": ["https://cdn/a.jpg"]})
    )
    assert "model" not in result


@pytest.mark.parametrize("urls_value", [None, "https://cdn/single.jpg"])
def test_format_result_survives_a_non_list_urls_field(urls_value):
    """A null or bare-string `urls` must not turn a display bug into a crash."""
    result = json.loads(
        px._format_result("image_generate", {"status": "completed", "urls": urls_value})
    )
    assert result["success"] is True
    assert result["image"] == (urls_value or None)
