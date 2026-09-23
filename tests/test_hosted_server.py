"""End-to-end test of the hosted gateway: JWT → tenant → spawn → proxy."""

import base64
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from gateway.hosted.router import JwtConfig, TenantResolver
from gateway.hosted.server import create_gateway_app
from gateway.hosted.supervisor import Supervisor, SupervisorConfig

AUDIENCE = "test-audience"
ISSUER = "https://developer.aiutils.io"
KID = "test-key"

# Minimal backend (subprocess) that echoes its ELIDIA_HOME on /health, so the
# test proves the request reached a real spawned process in the right home.
BACKEND_SCRIPT = r"""
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({
                "ok": True,
                "elidia_home": os.environ.get("ELIDIA_HOME"),
                "api_server_port": os.environ.get("API_SERVER_PORT"),
            }).encode("utf-8")
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

HTTPServer(("127.0.0.1", int(os.environ["API_SERVER_PORT"])), Handler).serve_forever()
"""


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


def _sign(keypair, claims):
    return jwt.encode(claims, keypair["private_pem"], algorithm="RS256",
                      headers={"kid": KID})


def _make_gateway(tmp_path, jwks_url, port_start):
    supervisor = Supervisor(SupervisorConfig(
        tenants_dir=tmp_path / "tenants",
        port_range=(port_start, port_start + 20),
        backend_cmd=[sys.executable, "-c", BACKEND_SCRIPT],
        health_timeout=10.0,
        health_interval=0.05,
    ))
    resolver = TenantResolver(
        JwtConfig(jwks_url=jwks_url, audience=AUDIENCE, issuer=ISSUER)
    )
    return supervisor, create_gateway_app(supervisor, resolver)


def _valid_claims(**overrides):
    claims = {
        "sub": "alice",
        "scope": "agent_dashboard:access",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "exp": time.time() + 3600,
    }
    claims.update(overrides)
    return claims


@pytest.mark.asyncio
async def test_gateway_end_to_end(tmp_path, jwks_url, keypair):
    supervisor, app = _make_gateway(tmp_path, jwks_url, 49200)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        token = _sign(keypair, _valid_claims())
        resp = await client.get("/health", headers={"Authorization": "Bearer " + token})
        assert resp.status == 200
        body = await resp.json()
        assert body["elidia_home"] == str(tmp_path / "tenants" / "alice")
    finally:
        await client.close()
        supervisor.shutdown()


@pytest.mark.asyncio
async def test_gateway_rejects_unauthorized(tmp_path, jwks_url, keypair):
    supervisor, app = _make_gateway(tmp_path, jwks_url, 49230)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/health")  # no Authorization header
        assert resp.status == 401
    finally:
        await client.close()
        supervisor.shutdown()


@pytest.mark.asyncio
async def test_gateway_isolates_two_tenants(tmp_path, jwks_url, keypair):
    supervisor, app = _make_gateway(tmp_path, jwks_url, 49260)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        alice = _sign(keypair, _valid_claims(sub="alice"))
        bob = _sign(keypair, _valid_claims(sub="bob"))
        ra = await client.get("/health", headers={"Authorization": "Bearer " + alice})
        rb = await client.get("/health", headers={"Authorization": "Bearer " + bob})
        ba = await ra.json()
        bb = await rb.json()
        assert ba["elidia_home"] == str(tmp_path / "tenants" / "alice")
        assert bb["elidia_home"] == str(tmp_path / "tenants" / "bob")
        assert ba["elidia_home"] != bb["elidia_home"]
        assert ba["api_server_port"] != bb["api_server_port"]
    finally:
        await client.close()
        supervisor.shutdown()
