"""Tool results reach SSE clients so a browser can render real media widgets.

AIUT-3307 — ``_on_tool_complete`` used to emit only ``{tool, toolCallId,
status}``. A frontend therefore never learned the URL of a generated asset and
could only show whatever the model happened to write into its prose; a
generated video arrived as markdown *image* syntax and rendered broken.

These tests pin the extractor that decides what is safe to put on the wire.
"""
from __future__ import annotations

import json

import pytest

from gateway.platforms.api_server import (
    MAX_FORWARDED_RESULT_BYTES,
    _extract_tool_result_for_sse,
)


# ── The whitelist ───────────────────────────────────────────────────


@pytest.mark.parametrize("tool", [
    "image_generate", "video_generate", "text_to_speech", "generate_3d", "portal_tool_open",
])
def test_whitelisted_tools_are_forwarded(tool):
    out = _extract_tool_result_for_sse(
        tool, json.dumps({"success": True, "image": "https://cdn/a.jpg"}),
    )
    assert out is not None


@pytest.mark.parametrize("tool", ["web_search", "read_file", "bash", "portal_deck_publish"])
def test_unlisted_tools_are_never_forwarded(tool):
    """Most tool results are large and none of them drive a UI widget."""
    out = _extract_tool_result_for_sse(
        tool, json.dumps({"success": True, "content": "x" * 50}),
    )
    assert out is None


# ── URL extraction ──────────────────────────────────────────────────


def test_single_media_key_becomes_a_urls_list():
    out = _extract_tool_result_for_sse(
        "video_generate", json.dumps({"success": True, "video": "https://cdn/v.mp4"}),
    )
    assert out["urls"] == ["https://cdn/v.mp4"]


def test_explicit_urls_list_is_preferred_and_kept_whole():
    out = _extract_tool_result_for_sse(
        "image_generate",
        json.dumps({
            "success": True,
            "image": "https://cdn/a.jpg",
            "urls": ["https://cdn/a.jpg", "https://cdn/b.jpg", "https://cdn/c.jpg"],
        }),
    )
    assert out["urls"] == ["https://cdn/a.jpg", "https://cdn/b.jpg", "https://cdn/c.jpg"]


def test_non_http_values_are_dropped_from_urls():
    """A relative path or a sandbox path must not reach the browser as a src."""
    out = _extract_tool_result_for_sse(
        "image_generate",
        json.dumps({"success": True, "urls": ["/tmp/local.jpg", "https://cdn/ok.jpg", 42, None]}),
    )
    assert out["urls"] == ["https://cdn/ok.jpg"]


def test_credits_and_model_ride_along():
    out = _extract_tool_result_for_sse(
        "image_generate",
        json.dumps({
            "success": True, "image": "https://cdn/a.jpg",
            "credits_used": 0.03344, "model": "fal/flux-schnell",
        }),
    )
    assert out["credits_used"] == 0.03344
    assert out["model"] == "fal/flux-schnell"


def test_an_error_result_is_forwarded_so_the_ui_can_show_it():
    out = _extract_tool_result_for_sse(
        "image_generate",
        json.dumps({"success": False, "error": "Insufficient credits"}),
    )
    assert out == {"success": False, "error": "Insufficient credits"}


def test_portal_tool_open_redirect_fields_survive():
    out = _extract_tool_result_for_sse(
        "portal_tool_open",
        json.dumps({
            "action": "open_url", "url": "https://aiutils.io/tools/x",
            "name": "Face Swap", "description": "Swap faces", "credit_cost": 2,
        }),
    )
    assert out["action"] == "open_url"
    assert out["url"] == "https://aiutils.io/tools/x"
    assert out["credit_cost"] == 2


def test_unknown_keys_are_dropped():
    """A field added to a tool result later must not start leaking by default."""
    out = _extract_tool_result_for_sse(
        "image_generate",
        json.dumps({
            "success": True, "image": "https://cdn/a.jpg",
            "internal_api_key": "sk-secret", "raw_provider_response": {"a": 1},
        }),
    )
    assert "internal_api_key" not in out
    assert "raw_provider_response" not in out


# ── Robustness: this runs inside the stream that carries the answer ──


@pytest.mark.parametrize("bad", ["not json at all", "[1,2,3]", '"a string"', "", None, 17])
def test_malformed_results_return_none_instead_of_raising(bad):
    assert _extract_tool_result_for_sse("image_generate", bad) is None


def test_dict_results_are_accepted_without_a_json_round_trip():
    out = _extract_tool_result_for_sse(
        "image_generate", {"success": True, "image": "https://cdn/a.jpg"},
    )
    assert out["urls"] == ["https://cdn/a.jpg"]


def test_an_oversized_result_is_dropped_rather_than_streamed():
    huge = ["https://cdn/" + ("x" * 200) + f"/{i}.jpg" for i in range(100)]
    out = _extract_tool_result_for_sse(
        "image_generate", json.dumps({"success": True, "urls": huge}),
    )
    assert out is None
    assert len(json.dumps({"urls": huge})) > MAX_FORWARDED_RESULT_BYTES


def test_a_result_with_nothing_useful_is_not_forwarded():
    assert _extract_tool_result_for_sse("image_generate", json.dumps({})) is None


# ── Wiring: the emit path actually calls the extractor ──────────────


def test_on_tool_complete_attaches_the_result():
    """Pins the wiring, not just the helper — the bug was a discarded argument."""
    from pathlib import Path

    src = Path("gateway/platforms/api_server.py").read_text()
    complete = src[src.index("def _on_tool_complete("):]
    complete = complete[: complete.index("_stream_q.put((\"__tool_progress__\", payload))")]
    assert "_extract_tool_result_for_sse(function_name, function_result)" in complete, (
        "function_result must be passed to the extractor, not discarded"
    )
    assert 'payload["result"] = result' in complete
