"""
Portal Tool Proxy — redirect billed tool calls to the portal model API.

When the Hermes gateway runs in portal provider mode (``provider: portal``
in config.yaml), media-generation tools must be executed through the portal's
tool execution endpoint so the user's portal credits are charged.  Without
this proxy the gateway would call FAL/PiAPI directly using the shared API key
and the user would not be billed.

Called from ``agent_runtime_helpers.invoke_tool()`` — if this returns a
non-None result, that result is used directly and the normal tool handler
is skipped.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PROXIED_TOOLS = frozenset({
    "image_generate",
    "video_generate",
    "text_to_speech",
    "generate_3d",
})

_PORTAL_BASE_URL = os.environ.get(
    "PORTAL_API_BASE_URL", "http://127.0.0.1:8000"
).rstrip("/")


def _is_portal_mode() -> bool:
    """Check if the gateway is running in portal provider mode."""
    logger.debug("Entered into _is_portal_mode")
    try:
        from elidia_cli.config import load_config
        cfg = load_config()
        model_cfg = cfg.get("model") if isinstance(cfg, dict) else None
        if isinstance(model_cfg, dict):
            return model_cfg.get("provider") == "portal"
    except Exception:
        pass
    return False


def _get_portal_user_id() -> Optional[str]:
    """Resolve the portal user ID from the session context."""
    try:
        from gateway.session_context import get_session_env
        uid = get_session_env("ELIDIA_SESSION_USER_ID", "")
        if uid:
            return str(uid)
    except ImportError:
        pass
    return None


def _get_gateway_token() -> Optional[str]:
    """Get the gateway auth token for portal API calls."""
    return os.environ.get("GATEWAY_INTERNAL_TOKEN") or os.environ.get(
        "HOSTED_GATEWAY_SHARED_SECRET"
    )


def _map_tool_name(gateway_name: str) -> Optional[str]:
    """Map gateway tool names to portal tool names."""
    mapping = {
        "image_generate": "generate_image",
        "video_generate": "generate_video",
        "text_to_speech": "generate_audio",
        "generate_3d": "generate_3d",
    }
    return mapping.get(gateway_name)


def _map_arguments(gateway_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Translate gateway tool arguments to portal tool arguments.

    An explicit ``model`` (the FAL ``endpoint_id`` the user picked from the
    model-list tool) is forwarded verbatim so the portal bills the exact model
    the user chose; when absent the portal auto-picks by quality tier.
    """
    if gateway_name == "image_generate":
        mapped = {
            "prompt": args.get("prompt", ""),
            "aspect_ratio": args.get("aspect_ratio", "square"),
            "quality": args.get("quality", "standard"),
        }
        # Forwarded only when the agent asked for more than the default, so a
        # portal that has not yet learned the parameter keeps its own default
        # (AIUT-3307).
        num_images = args.get("num_images")
        if num_images:
            mapped["num_images"] = num_images
    elif gateway_name == "video_generate":
        mapped = {
            "prompt": args.get("prompt", ""),
            "duration": args.get("duration", 5),
            "aspect_ratio": args.get("aspect_ratio", "16:9"),
            "quality": args.get("quality", "standard"),
        }
    elif gateway_name == "text_to_speech":
        mapped = {
            "prompt": args.get("text") or args.get("prompt", ""),
            "audio_type": args.get("audio_type", "speech"),
            "quality": args.get("quality", "standard"),
        }
    elif gateway_name == "generate_3d":
        mapped = {
            "prompt": args.get("prompt", ""),
            "quality": args.get("quality", "standard"),
        }
    else:
        return args

    model = args.get("model")
    if model:
        mapped["model"] = model
    return mapped


# Must exceed the portal's worst-case media call. The portal allows FAL up to
# 300s for video and 3D, then bills and re-uploads to the CDN (itself up to
# 180s for a video download) before replying. A matching 300s here gave zero
# margin: the gateway gave up exactly while the portal was still charging, and
# the request fell through to local execution, so the user was charged and got
# nothing, then charged again on the agent's retry (AIUT-3317).
_PORTAL_TOOL_TIMEOUT_SECONDS = float(
    os.getenv("ELIDIA_PORTAL_TOOL_TIMEOUT_SECONDS", "600")
)


def _portal_failed(gateway_name: str, reason: str) -> str:
    """Report a portal-side failure instead of falling back to local execution.

    Returning ``None`` here hands the call to the agent's local dispatcher.
    On the hosted gateway that path has no FAL credentials, so it fails
    confusingly — and worse, the portal may already have charged for a
    generation whose result we timed out waiting for. Re-running it would
    charge a second time. An explicit failure stops that: the agent reports it
    and does not silently retry a paid operation.
    """
    logger.warning("Portal tool %s failed, not falling back locally: %s",
                   gateway_name, reason)
    return json.dumps({
        "success": False,
        "error": (
            f"The media service could not complete this request ({reason}). "
            "It may still have been charged — check your usage before retrying."
        ),
    }, indent=2)


def _format_result(gateway_name: str, portal_result: Dict[str, Any]) -> str:
    """Convert portal API response to the format the agent expects."""
    if portal_result.get("status") == "error":
        return json.dumps({
            "success": False,
            "error": portal_result.get("error", "Tool execution failed"),
        }, indent=2)

    # Normalised here because callers below take len(): the portal sends a
    # list, but a null would have turned a display bug into a TypeError.
    urls = portal_result.get("urls") or []
    if not isinstance(urls, list):
        urls = [urls]

    def _media_payload(key: str) -> str:
        """Media envelope the agent expects, carrying the portal's charge.

        `credits_used` was previously dropped here, so the agent could never
        tell the user what a generation cost (AIUT-3292). It is omitted rather
        than sent as null when the portal did not report one, so no bare
        `None` leaks into the agent's context.

        `key` stays a single URL because that is what the agent's prompt and
        every existing consumer read. The full `urls` list is carried
        alongside it so a multi-image generation does not lose every result
        after the first, which is what happened before (AIUT-3307). `model`
        rides along so the UI can name what produced the asset.
        """
        payload = {"success": True, key: urls[0] if urls else None}
        if len(urls) > 1:
            payload["urls"] = list(urls)
        credits_used = portal_result.get("credits_used")
        if credits_used is not None:
            payload["credits_used"] = credits_used
        model = portal_result.get("model")
        if model:
            payload["model"] = model
        # The portal sets `note` whenever it changed what the user asked for —
        # a duration snapped to what the model accepts, or fewer images than
        # requested. Dropping it here meant a user billed for an 8s video they
        # asked to be 5s got no explanation, and the agent could not give one
        # because it never saw the note either (AIUT-3317).
        note = portal_result.get("note")
        if note:
            payload["note"] = note
        return json.dumps(payload, indent=2)

    if gateway_name == "image_generate":
        return _media_payload("image")
    elif gateway_name == "video_generate":
        return _media_payload("video")
    elif gateway_name == "text_to_speech":
        return _media_payload("audio")
    elif gateway_name == "generate_3d":
        return _media_payload("model_3d")

    return json.dumps(portal_result, indent=2)


def maybe_proxy_tool(
    function_name: str,
    function_args: Dict[str, Any],
) -> Optional[str]:
    """Proxy a tool call to the portal if in portal mode.

    Returns the tool result string if proxied, or None if the tool
    should be executed locally.
    """
    if function_name not in _PROXIED_TOOLS:
        return None

    if not _is_portal_mode():
        return None

    user_id = _get_portal_user_id()
    if not user_id:
        logger.warning(
            "Portal tool proxy: no user_id available for %s, falling back to local",
            function_name,
        )
        return None

    portal_tool_name = _map_tool_name(function_name)
    if not portal_tool_name:
        return None

    gateway_token = _get_gateway_token()
    if not gateway_token:
        logger.warning(
            "Portal tool proxy: no gateway token for %s, falling back to local",
            function_name,
        )
        return None

    logger.info(
        "Portal tool proxy: routing %s → portal %s (user_id=%s)",
        function_name, portal_tool_name, user_id,
    )

    portal_args = _map_arguments(function_name, function_args)
    url = f"{_PORTAL_BASE_URL}/agent-v2/v1/tools/execute"
    payload = {
        "tool_name": portal_tool_name,
        "arguments": portal_args,
        "user_id": int(user_id),
    }
    headers = {
        "Content-Type": "application/json",
        "X-Gateway-Token": gateway_token,
        "X-Portal-User-Id": str(user_id),
    }

    import httpx

    try:
        with httpx.Client(timeout=_PORTAL_TOOL_TIMEOUT_SECONDS) as client:
            resp = client.post(url, json=payload, headers=headers)

        if resp.status_code == 402:
            return json.dumps({
                "success": False,
                "error": "Insufficient portal credits. Please top up your balance.",
            }, indent=2)

        if resp.status_code != 200:
            logger.error(
                "Portal tool proxy failed: HTTP %s — %s",
                resp.status_code, resp.text[:300],
            )
            return _portal_failed(
                function_name,
                f"the media service returned HTTP {resp.status_code}",
            )

        portal_result = resp.json()
        return _format_result(function_name, portal_result)

    except Exception as exc:
        logger.error(
            "Portal tool proxy error for %s: %s", function_name, exc,
            exc_info=True,
        )
        return _portal_failed(function_name, str(exc)[:200])


def fetch_media_models() -> Optional[Dict[str, Any]]:
    """Fetch the portal's active media-model catalog (``GET /media/models``).

    Returns the parsed ``data`` mapping (``image``/``video``/``audio``/``3d``
    → list of model entries) on success, or ``None`` when the portal is
    unreachable or auth fails. Read-only and unbilled — the portal catalog
    endpoint does not charge.
    """
    logger.debug("Entered into fetch_media_models")
    if not _is_portal_mode():
        return None

    gateway_token = _get_gateway_token()
    if not gateway_token:
        logger.warning("Portal media models: no gateway token, skipping")
        return None

    url = f"{_PORTAL_BASE_URL}/agent-v2/v1/media/models"
    headers = {
        "Content-Type": "application/json",
        "X-Gateway-Token": gateway_token,
    }

    import httpx

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=headers)

        if resp.status_code != 200:
            logger.error(
                "Portal media models failed: HTTP %s — %s",
                resp.status_code, resp.text[:300],
            )
            return None

        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        return data if isinstance(data, dict) else None

    except Exception as exc:
        logger.error("Portal media models error: %s", exc, exc_info=True)
        return None
