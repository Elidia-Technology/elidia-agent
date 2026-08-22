"""AiUtils Developer API provider profile.

The AiUtils Developer API (https://developer-api.aiutils.io) is the default
inference provider for Elidia Agent V2. It exposes an OpenAI-compatible
``POST /v1/chat/completions`` endpoint (Bearer ``ak-dev-*`` keys) with
per-call DT-credit billing handled server-side, plus a dedicated
``POST /v1/chat/completions/stream`` for SSE.

Chat-model discovery: the gateway's ``GET /v1/models`` returns the
*generative* catalog (image/video/audio/3D + async research agents), NOT the
chat-completion LLM models. There is no REST catalog of chat models, so
:meth:`AiUtilsProfile.fetch_models` returns ``None`` and the picker falls
back to ``fallback_models`` below — the verified set the gateway routes to its
openai/anthropic/deepseek adapters (source of truth:
``developer/provider_adapters/*_adapter.py`` pricing tables).
"""

from __future__ import annotations

from providers import register_provider
from providers.base import ProviderProfile


class AiUtilsProfile(ProviderProfile):
    """AiUtils Developer API — OpenAI-compatible chat + server-side DT billing."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Return None — the Developer API has no chat-model REST catalog.

        ``GET /v1/models`` lists generative (image/video/audio/3D) and async
        research-agent models only; it does not enumerate the chat-completion
        LLM models. Callers fall back to ``fallback_models``.
        """
        return None


aiutils = AiUtilsProfile(
    name="aiutils",
    aliases=("aiutils-dev",),
    display_name="AiUtils Developer API",
    description="AiUtils Developer API — Claude, GPT, DeepSeek + DT-credit billing",
    signup_url="https://developer.aiutils.io/",
    # The AiUtils Developer API key is exposed under three env-var names.
    # All three resolve to this provider: ``ELIDIA_KEY`` / ``ELIDIA_API_KEY``
    # (legacy Elidia names) and ``AIUTILS_API_KEY`` (Developer-console name).
    # Order is the auto-detection priority in resolve_provider().
    env_vars=("ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY"),
    base_url="https://developer-api.aiutils.io/v1",
    # The Developer API only streams on a dedicated POST /v1/chat/completions/stream
    # endpoint; POST /v1/chat/completions returns a single non-stream object even
    # when stream=true (which the OpenAI SDK then yields as 0 chunks → empty reply).
    # Force non-streaming so the standard /chat/completions path is used.
    supports_streaming=False,
    default_headers={
        "API-Version": "2026-07-01",
        # Cloudflare WAF in front of developer-api.aiutils.io returns HTTP 403
        # "Your request was blocked." for the OpenAI SDK's default User-Agent
        # ("OpenAI/Python <ver>"). Override it so the bundled OpenAI client in
        # run_agent.py sends an identifiable, non-blocked UA instead.
        "User-Agent": "ElidiaAgent/2.0.0",
    },
    # The Developer API has no chat-model catalog, so the model picker falls
    # back to `fallback_models`. When a user authenticates but never runs
    # `elidia model`, default to this model instead of sending an empty model
    # string (which the gateway rejects with HTTP 400).
    default_model="deepseek-v4-flash",
    fallback_models=(
        # Anthropic (current agentic line)
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "claude-fable-5",
        # DeepSeek (current)
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        # OpenAI (gpt-5 family)
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.2",
        "gpt-5.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
    ),
)

register_provider(aiutils)
