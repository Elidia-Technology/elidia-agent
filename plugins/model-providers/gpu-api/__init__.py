"""AiUtils GPU API provider profile.

The AiUtils GPU API is the OpenAI-compatible inference service that serves
open-source models (LLM via Ollama, plus embeddings, rerank, whisper STT,
TTS, OCR, diffusers and classification engines) from a GPU host. It is
authenticated with a ``gpuapi_*`` API key sent as either
``Authorization: Bearer gpuapi_...`` (what the OpenAI client uses) or
``X-API-Key: gpuapi_...`` (what the aiutils_gpu SDK uses) — the server's
``require_inference_access`` accepts both.

Endpoints are mounted under ``/api/v1`` (``POST /api/v1/chat/completions``,
``POST /api/v1/embeddings``, ``GET /api/v1/models``, …), so ``base_url`` must
end in ``/api/v1`` for the transport to append ``/chat/completions`` correctly.

Defaults follow the aiutils_gpu SDK: ``GPU_API_KEY`` + ``GPU_API_URL`` with a
``http://localhost:9000`` base. Point ``GPU_API_URL`` at your GPU host (e.g.
``http://192.168.31.82:9000/api/v1``) when the agent runs on a different
machine than the GPU host.

Model discovery: ``GET /api/v1/models`` returns the registry shape
``{"models": [{id, slug, ...}]}`` (installed models), not the OpenAI
``{"data": [{id}]}`` shape, so :meth:`GpuApiProfile.fetch_models` maps both
shapes and falls back to ``fallback_models`` (the verified Ollama LLM set)
when the catalog is unreachable or empty.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.error import URLError

from providers import register_provider
from providers.base import ProviderProfile, _profile_user_agent


class GpuApiProfile(ProviderProfile):
    """AiUtils GPU API — OpenAI-compatible chat over a GPU host."""

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """List served models from ``GET {base_url}/models``.

        The GPU API returns ``{"models": [{id, slug, ...}]}`` (a registry of
        installed models), which is not the OpenAI ``{"data": [{id}]}`` shape.
        Map both shapes; return ``None`` so callers fall back to
        ``fallback_models`` when the catalog is empty or unreachable.
        """
        url = (self.models_url or "").strip()
        if not url:
            if not self.base_url:
                return None
            url = self.base_url.rstrip("/") + "/models"

        req = urllib.request.Request(url)
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", _profile_user_agent())

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, TimeoutError, ValueError, OSError):
            return None

        items: list[dict] = []
        if isinstance(data, dict):
            # OpenAI shape: {"data": [{"id": ...}]}
            if isinstance(data.get("data"), list):
                items = [m for m in data["data"] if isinstance(m, dict)]
            # GPU API registry shape: {"models": [{"id"/"slug"/"name": ...}]}
            elif isinstance(data.get("models"), list):
                items = [m for m in data["models"] if isinstance(m, dict)]
        elif isinstance(data, list):
            items = [m for m in data if isinstance(m, dict)]

        ids: list[str] = []
        for m in items:
            for key in ("id", "slug", "name"):
                value = m.get(key)
                if isinstance(value, str) and value.strip():
                    ids.append(value.strip())
                    break
        return ids or None


gpu_api = GpuApiProfile(
    name="gpu-api",
    aliases=("aiutils-gpu", "gpuapi", "gpu"),
    display_name="AiUtils GPU API",
    description="AiUtils GPU API — local/hosted open-source LLM, vision, embeddings, audio, image",
    signup_url="https://aiutils.io/",
    # The aiutils_gpu SDK's canonical env vars: key + base URL. ``GPU_API_URL``
    # ends in ``_URL`` so the provider registry auto-extends it as the
    # ``base_url_env_var`` override, exactly like the LM Studio ``LM_BASE_URL``.
    env_vars=("GPU_API_KEY", "GPU_API_URL"),
    base_url="http://localhost:9000/api/v1",
    # The GPU API streams chat via SSE on POST /chat/completions.
    supports_streaming=True,
    # No Cloudflare WAF in front of a local GPU host; the OpenAI client's
    # default User-Agent is fine. No default_headers override needed.
    default_headers={},
    default_model="mistral:7b",
    # Verified Ollama LLM set from the GPU API handoff (all PASS-tested):
    # mistral:7b, phi4-mini, llama3.1:8b, qwen2.5:7b, deepseek-r1:7b.
    # Shown in the model picker when the live catalog is unreachable.
    fallback_models=(
        "mistral:7b",
        "phi4-mini",
        "llama3.1:8b",
        "qwen2.5:7b",
        "deepseek-r1:7b",
    ),
)

register_provider(gpu_api)
