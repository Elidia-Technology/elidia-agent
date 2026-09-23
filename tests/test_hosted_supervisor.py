"""Tests for the process-per-tenant supervisor.

These exercise the supervisor's lifecycle mechanics — spawn, environment
isolation, health-check, and reap — against a minimal stdlib HTTP backend.
The real ``cli.py --gateway`` backend is not booted here (it needs model
providers); that integration is covered by the DT wiring tickets.
"""

import json
import sys
import time
import urllib.request

import pytest

from gateway.hosted.supervisor import Supervisor, SupervisorConfig

# A tiny HTTP backend that binds the port the supervisor assigns and echoes
# its ELIDIA_HOME / API_SERVER_PORT so the test can prove env isolation.
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
                "aiutils_api_key": os.environ.get("AIUTILS_API_KEY"),
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


def _make_supervisor(tmp_path, **overrides):
    cfg = dict(
        tenants_dir=tmp_path / "tenants",
        port_range=(49100, 49120),
        health_timeout=10.0,
        health_interval=0.05,
        idle_ttl=3600.0,
        backend_cmd=[sys.executable, "-c", BACKEND_SCRIPT],
    )
    cfg.update(overrides)
    return Supervisor(SupervisorConfig(**cfg))


def _health(host, port):
    with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2.0) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class _StubProvisioner:
    """Duck-typed stand-in for ``KeyProvisioner``; records provision calls."""

    def __init__(self, key="ak-dev-stub"):
        self.key = key
        self.calls = 0

    @property
    def enabled(self):
        return True

    def provision(self, tenant_id):
        self.calls += 1
        return self.key


def test_spawn_isolates_tenants(tmp_path):
    sup = _make_supervisor(tmp_path)
    try:
        alice = sup.acquire("alice")
        bob = sup.acquire("bob")

        # Distinct ports, homes, and keys.
        assert alice.port != bob.port
        assert alice.home != bob.home
        assert alice.api_key != bob.api_key

        # Both healthy, each reporting its own isolated home and port.
        status_a, body_a = _health("127.0.0.1", alice.port)
        status_b, body_b = _health("127.0.0.1", bob.port)
        assert status_a == 200 and body_a["elidia_home"] == str(alice.home)
        assert status_b == 200 and body_b["elidia_home"] == str(bob.home)
        assert body_a["api_server_port"] == str(alice.port)
        assert body_b["api_server_port"] == str(bob.port)
        assert body_a["elidia_home"] != body_b["elidia_home"]

        # Homes are physically distinct directories on disk.
        assert alice.home.is_dir() and bob.home.is_dir()
        assert alice.home.resolve() != bob.home.resolve()
    finally:
        sup.shutdown()


def test_acquire_is_idempotent(tmp_path):
    sup = _make_supervisor(tmp_path)
    try:
        first = sup.acquire("alice")
        second = sup.acquire("alice")
        assert first.port == second.port
        assert first.process is second.process
    finally:
        sup.shutdown()


def test_tenant_config_enables_only_api_server(tmp_path):
    sup = _make_supervisor(tmp_path)
    try:
        backend = sup.acquire("alice")
        config_path = backend.home / "config.yaml"
        assert config_path.exists()

        import yaml

        with open(config_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        platforms = data["platforms"]
        assert platforms == {"api_server": {"enabled": True}}
    finally:
        sup.shutdown()


def test_release_terminates_backend(tmp_path):
    sup = _make_supervisor(tmp_path)
    try:
        backend = sup.acquire("alice")
        port = backend.port
        sup.release("alice")
        assert sup.get("alice") is None
        assert backend.process.poll() is not None  # exited
    finally:
        sup.shutdown()


def test_reap_idle_terminates_stale(tmp_path):
    sup = _make_supervisor(tmp_path, idle_ttl=0.3)
    try:
        backend = sup.acquire("alice")
        time.sleep(0.6)
        reaped = sup.reap_idle()
        assert reaped == ["alice"]
        assert backend.process.poll() is not None
    finally:
        sup.shutdown()


def test_rejects_unsafe_tenant_id(tmp_path):
    sup = _make_supervisor(tmp_path)
    try:
        with pytest.raises(ValueError):
            sup.acquire("../escape")
        with pytest.raises(ValueError):
            sup.acquire("a/b")
        with pytest.raises(ValueError):
            sup.acquire("")
    finally:
        sup.shutdown()


def test_provisions_aiutils_key_into_backend_env(tmp_path):
    stub = _StubProvisioner("ak-dev-alice")
    sup = _make_supervisor(tmp_path, provisioner=stub)
    try:
        backend = sup.acquire("alice")
        status, body = _health("127.0.0.1", backend.port)
        assert status == 200
        assert body["aiutils_api_key"] == "ak-dev-alice"
        assert stub.calls == 1
    finally:
        sup.shutdown()


def test_provision_key_is_cached_across_respawn(tmp_path):
    stub = _StubProvisioner("ak-dev-alice")
    sup = _make_supervisor(tmp_path, provisioner=stub)
    try:
        sup.acquire("alice")
        sup.release("alice")
        sup.acquire("alice")  # respawns; key must not be re-provisioned
        assert stub.calls == 1
    finally:
        sup.shutdown()


def test_no_provisioner_injects_no_aiutils_key(tmp_path):
    sup = _make_supervisor(tmp_path)  # no provisioner configured
    try:
        backend = sup.acquire("alice")
        status, body = _health("127.0.0.1", backend.port)
        assert status == 200
        assert body["aiutils_api_key"] is None
    finally:
        sup.shutdown()
