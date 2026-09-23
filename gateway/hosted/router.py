"""Portal OAuth JWT verification → tenant identity.

Verifies the ``Authorization: Bearer`` token against the Portal OAuth JWKS
(RS256) and returns the authenticated tenant id. This is the trust boundary
for the process-per-tenant gateway: an unverifiable token is rejected here,
so no request ever reaches a backend without a confirmed tenant.

Live JWKS discovery against ``developer.aiutils.io`` is exercised end-to-end
by the OAuth ticket (#3070); this module's verification logic is unit-tested
against a locally-generated RSA key served as a JWKS.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient


class JwtError(Exception):
    """Raised when a token cannot be verified or lacks the required claims."""


@dataclass(frozen=True)
class JwtConfig:
    """Configuration for Portal OAuth JWT verification."""

    jwks_url: str
    audience: str
    issuer: str = ""
    algorithms: tuple = ("RS256",)
    tenant_claim: str = "sub"
    required_scope: str = "agent_dashboard:access"


class TenantResolver:
    """Resolve a verified Bearer token to a tenant id."""

    def __init__(self, config: JwtConfig):
        if not config.jwks_url:
            raise ValueError("jwks_url is required")
        self._config = config
        # cache_keys=True keeps the fetched key set warm and re-fetches on an
        # unknown kid, so rotation does not require a restart.
        self._jwks = PyJWKClient(config.jwks_url, cache_keys=True)

    def resolve(self, authorization_header: str) -> str:
        """Return the tenant id for a valid ``Authorization: Bearer`` header.

        Raises :class:`JwtError` on a missing/malformed header, a signature or
        claim verification failure, a missing required scope, or a missing
        tenant claim.
        """
        token = self._extract_token(authorization_header)
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            options = {
                "verify_signature": True,
                "verify_aud": True,
                "verify_iss": bool(self._config.issuer),
                "verify_exp": True,
            }
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self._config.algorithms),
                audience=self._config.audience,
                issuer=self._config.issuer or None,
                options=options,
            )
        except jwt.PyJWTError as exc:
            raise JwtError(f"token verification failed: {exc}") from exc

        scopes = (claims.get("scope") or "").split()
        if self._config.required_scope not in scopes:
            raise JwtError(
                f"token missing required scope {self._config.required_scope!r}"
            )

        tenant_id = claims.get(self._config.tenant_claim)
        if not tenant_id or not isinstance(tenant_id, str):
            raise JwtError(
                f"token missing tenant claim {self._config.tenant_claim!r}"
            )
        return tenant_id

    @staticmethod
    def _extract_token(authorization_header: str) -> str:
        if not authorization_header or not isinstance(authorization_header, str):
            raise JwtError("missing Authorization header")
        parts = authorization_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise JwtError("Authorization header must be 'Bearer <token>'")
        token = parts[1].strip()
        if not token:
            raise JwtError("empty bearer token")
        return token
