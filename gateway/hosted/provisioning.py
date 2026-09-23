"""Provision the aiutils API key for a hosted tenant.

After the router resolves a portal user (tenant id) from the OAuth token, the
supervisor needs an API key to hand to that tenant's agent process so its LLM
spend bills against the developer's wallet (plan §6.4 — developer-wallet
fallback). This module calls the portal's internal provision endpoint
(``apikey_svc`` → ``POST /api/keys/internal/provision``) and returns the
plaintext key exactly once.

Configuration (environment only — no secrets in code):

* ``HOSTED_GATEWAY_PROVISION_URL``  required — the internal provision endpoint
* ``PROVISION_INTERNAL_TOKEN``      required — the ``X-Provision-Token`` secret
                                    dedicated to key provisioning (NOT the
                                    platform-wide ``GATEWAY_INTERNAL_TOKEN``)

When either is unset the provisioner is disabled and the supervisor injects no
key (a degraded, non-billing state used only for local bring-up). ``run.py``
rejects a half-configured pair at startup rather than silently disabling it.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ProvisionError(RuntimeError):
    """Raised when a tenant's aiutils key cannot be provisioned."""


@dataclass(frozen=True)
class ProvisionerConfig:
    provision_url: str = ""
    provision_token: str = ""
    timeout: float = 5.0


class KeyProvisioner:
    """Calls the portal's internal provision endpoint for a tenant's API key."""

    def __init__(self, config: ProvisionerConfig):
        self._config = config

    @property
    def enabled(self) -> bool:
        return bool(self._config.provision_url and self._config.provision_token)

    def provision(self, tenant_id: str) -> str:
        """Return the plaintext aiutils API key for ``tenant_id``.

        The key is returned exactly once; the caller caches it server-side.
        Raises :class:`ProvisionError` when not configured, when the endpoint
        is unreachable or errors, or when the response lacks a key.
        """
        if not self.enabled:
            raise ProvisionError("hosted-gateway key provisioning is not configured")

        body = json.dumps({"portal_user_id": self._portal_user_id(tenant_id)}).encode("utf-8")
        request = urllib.request.Request(
            self._config.provision_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Provision-Token": self._config.provision_token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProvisionError(f"provision endpoint returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProvisionError(f"provision request failed: {exc}") from exc

        plaintext = payload.get("plaintext_key")
        if not plaintext:
            raise ProvisionError("provision response missing plaintext_key")
        return plaintext

    @staticmethod
    def _portal_user_id(tenant_id: str) -> int:
        # The portal issues ``sub`` as ``str(portal_user_id)``; only an ASCII
        # decimal string is a valid portal user id to provision for. ``isascii``
        # keeps Unicode digit lookalikes (e.g. superscript ²) out, which
        # ``isdigit()`` alone would admit and then ``int()`` would reject.
        if not (tenant_id.isascii() and tenant_id.isdigit()):
            raise ProvisionError(f"tenant id is not a numeric portal user id: {tenant_id!r}")
        return int(tenant_id)
