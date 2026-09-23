"""Tests for the hosted gateway's key provisioner (plan §6.4).

``KeyProvisioner`` is the boundary between the gateway and the portal's internal
provision endpoint (``POST /api/keys/internal/provision``). These tests pin the
contract against a real local HTTP server:

  * the exact request shape — POST, JSON ``{"portal_user_id": int}``, and the
    dedicated ``X-Provision-Token`` header (not the platform-wide gateway token)
  * the plaintext key is read from the response and returned once
  * a non-numeric tenant id is rejected before any HTTP call
  * HTTP errors and a missing key in the response raise ``ProvisionError``
  * ``enabled`` is True only when both ``provision_url`` and ``provision_token``
    are set; a half-configured provisioner never silently provisions
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gateway.hosted.provisioning import (
    KeyProvisioner,
    ProvisionError,
    ProvisionerConfig,
)


class _ProvisionHandler(BaseHTTPRequestHandler):
    last_body: dict | None = None
    last_token: str | None = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _ProvisionHandler.last_body = json.loads(self.rfile.read(length).decode("utf-8"))
        _ProvisionHandler.last_token = self.headers.get("X-Provision-Token")

        if self.path == "/ok":
            body = json.dumps({"plaintext_key": "ak-dev-test-key"}).encode("utf-8")
            self.send_response(201)
        elif self.path == "/missing-key":
            body = json.dumps({"developer_id": "some-id"}).encode("utf-8")
            self.send_response(201)
        elif self.path == "/error":
            body = json.dumps({"error": "boom"}).encode("utf-8")
            self.send_response(500)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _ProvisionHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        _ProvisionHandler.last_body = None
        _ProvisionHandler.last_token = None
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _provisioner(base_url, **overrides):
    cfg = dict(provision_url=f"{base_url}/ok", provision_token="tok")
    cfg.update(overrides)
    return KeyProvisioner(ProvisionerConfig(**cfg))


def test_provision_posts_portal_user_id_and_dedicated_token(server):
    key = _provisioner(server).provision("12345")

    assert key == "ak-dev-test-key"
    assert _ProvisionHandler.last_body == {"portal_user_id": 12345}
    assert _ProvisionHandler.last_token == "tok"


def test_provision_rejects_non_numeric_tenant_id_before_any_call(server):
    with pytest.raises(ProvisionError):
        _provisioner(server).provision("not-a-number")
    assert _ProvisionHandler.last_body is None  # no HTTP call was made


def test_provision_rejects_unicode_digit_lookalike(server):
    # "²" is isdigit()-True but not an ASCII decimal; int("²") would raise.
    with pytest.raises(ProvisionError):
        _provisioner(server).provision("²")
    assert _ProvisionHandler.last_body is None  # no HTTP call was made


def test_provision_raises_on_http_error(server):
    p = _provisioner(server, provision_url=f"{server}/error")
    with pytest.raises(ProvisionError):
        p.provision("12345")


def test_provision_raises_when_response_missing_key(server):
    p = _provisioner(server, provision_url=f"{server}/missing-key")
    with pytest.raises(ProvisionError):
        p.provision("12345")


def test_provision_raises_when_not_configured():
    with pytest.raises(ProvisionError):
        KeyProvisioner(ProvisionerConfig()).provision("12345")


def test_enabled_requires_both_fields():
    assert KeyProvisioner(ProvisionerConfig()).enabled is False
    assert KeyProvisioner(ProvisionerConfig(provision_url="u")).enabled is False
    assert KeyProvisioner(ProvisionerConfig(provision_token="t")).enabled is False
    assert KeyProvisioner(ProvisionerConfig(provision_url="u", provision_token="t")).enabled is True
