"""Tests for the Portal OAuth JWT → tenant resolver.

Verifies the router against a locally-generated RSA key served as a JWKS
(not the live ``developer.aiutils.io`` JWKS — that end-to-end check is #3070).
"""

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from gateway.hosted.router import JwtConfig, JwtError, TenantResolver

AUDIENCE = "test-audience"
ISSUER = "https://developer.aiutils.io"
KID = "test-key"
SCOPE = "agent_dashboard:access"


def _b64url_int(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url_int(pub.n),
                "e": _b64url_int(pub.e),
            }
        ]
    }
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return {"jwks": jwks, "private_pem": private_pem}


@pytest.fixture(scope="module")
def jwks_url(keypair):
    body = json.dumps(keypair["jwks"]).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/.well-known/jwks.json":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/.well-known/jwks.json"
    server.shutdown()


def _sign(keypair, claims, headers=None):
    return jwt.encode(
        claims,
        keypair["private_pem"],
        algorithm="RS256",
        headers=headers or {"kid": KID},
    )


def _resolver(jwks_url) -> TenantResolver:
    return TenantResolver(
        JwtConfig(jwks_url=jwks_url, audience=AUDIENCE, issuer=ISSUER)
    )


def _valid_claims(**overrides):
    claims = {
        "sub": "alice",
        "scope": SCOPE,
        "aud": AUDIENCE,
        "iss": ISSUER,
        "exp": time.time() + 3600,
    }
    claims.update(overrides)
    return claims


def test_resolves_tenant(jwks_url, keypair):
    token = _sign(keypair, _valid_claims())
    assert _resolver(jwks_url).resolve("Bearer " + token) == "alice"


def test_rejects_expired(jwks_url, keypair):
    token = _sign(keypair, _valid_claims(exp=time.time() - 60))
    with pytest.raises(JwtError):
        _resolver(jwks_url).resolve("Bearer " + token)


def test_rejects_wrong_scope(jwks_url, keypair):
    token = _sign(keypair, _valid_claims(scope="other:scope"))
    with pytest.raises(JwtError):
        _resolver(jwks_url).resolve("Bearer " + token)


def test_rejects_wrong_audience(jwks_url, keypair):
    token = _sign(keypair, _valid_claims(aud="wrong-audience"))
    with pytest.raises(JwtError):
        _resolver(jwks_url).resolve("Bearer " + token)


def test_rejects_tampered_signature(jwks_url, keypair):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    token = jwt.encode(
        _valid_claims(), other_pem, algorithm="RS256", headers={"kid": KID}
    )
    with pytest.raises(JwtError):
        _resolver(jwks_url).resolve("Bearer " + token)


def test_rejects_missing_header(jwks_url):
    with pytest.raises(JwtError):
        _resolver(jwks_url).resolve("")


def test_rejects_missing_tenant_claim(jwks_url, keypair):
    token = _sign(keypair, _valid_claims(sub=""))
    with pytest.raises(JwtError):
        _resolver(jwks_url).resolve("Bearer " + token)
