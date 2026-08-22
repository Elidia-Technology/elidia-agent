"""Elidia Portal provider profile."""

from typing import Any

from agent.portal_tags import elidia_portal_tags
from providers import register_provider
from providers.base import ProviderProfile


class ElidiaProfile(ProviderProfile):
    """Elidia Portal — product tags, reasoning with Elidia-specific omission."""

    def build_extra_body(
        self, *, session_id: str | None = None, **context
    ) -> dict[str, Any]:
        return {"tags": elidia_portal_tags()}

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        supports_reasoning: bool = False,
        **context,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Elidia: passes full reasoning_config, but OMITS when disabled."""
        extra_body = {}
        if supports_reasoning:
            if reasoning_config is not None:
                rc = dict(reasoning_config)
                if rc.get("enabled") is False:
                    pass  # Elidia omits reasoning when disabled
                else:
                    extra_body["reasoning"] = rc
            else:
                extra_body["reasoning"] = {"enabled": True, "effort": "medium"}
        return extra_body, {}


elidia = ElidiaProfile(
    name="elidia",
    aliases=("elidia-portal",),
    env_vars=("ELIDIA_KEY", "ELIDIA_API_KEY"),
    display_name="AiUtils",
    description="AiUtils — Elidia model family",
    signup_url="https://aiutils.io/",
    fallback_models=(
        "hermes-3-405b",
        "hermes-3-70b",
    ),
    base_url="https://inference.aiutils.io/v1",
    auth_type="oauth_device_code",
)

register_provider(elidia)
