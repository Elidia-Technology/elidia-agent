"""The hosted gateway must discover MCP tools (AIUT-3313).

Only the CLI gateway (gateway/run.py) and the interactive CLI ever called
`discover_mcp_tools()`. The hosted gateway — the process that serves the web
portal — never did, so configuring `mcp_servers` in config.yaml had no effect
there and web users had no MCP tools at all.

Verified on production before the fix: with four servers configured, enabled
and individually probed as working, the agent still answered
"TOOL NOT AVAILABLE" when asked to call one.
"""
from __future__ import annotations

from pathlib import Path

import pytest


SRC = Path("gateway/hosted/run.py").read_text()


class TestDiscoveryIsWired:

    def test_hosted_main_starts_mcp_discovery(self):
        assert "start_background_mcp_discovery" in SRC

    def test_discovery_runs_before_the_server_starts_serving(self):
        """Tools registered after run_app would never reach an agent turn."""
        assert SRC.index("start_background_mcp_discovery") < SRC.index("web.run_app(")

    def test_discovery_failure_cannot_stop_the_gateway(self):
        block = SRC[SRC.index("start_background_mcp_discovery"):]
        block = block[: block.index("auth_mode")]
        assert "except Exception:" in block

    def test_it_uses_the_background_helper_not_a_blocking_call(self):
        """discover_mcp_tools() blocks up to 120s; a hung server must not
        prevent the gateway from serving. Comments may name it; code may not."""
        code_lines = [
            line for line in SRC.splitlines()
            if "discover_mcp_tools()" in line and not line.lstrip().startswith("#")
        ]
        assert code_lines == [], f"blocking call found: {code_lines}"


class TestHelperContract:
    """Pin the behaviour the wiring relies on."""

    def test_helper_is_idempotent_and_non_blocking(self):
        helper = Path("elidia_cli/mcp_startup.py").read_text()
        assert "daemon=True" in helper
        assert "_mcp_discovery_started" in helper

    def test_helper_skips_when_no_servers_configured(self):
        helper = Path("elidia_cli/mcp_startup.py").read_text()
        assert "_has_configured_mcp_servers" in helper

    def test_helper_accepts_the_arguments_the_gateway_passes(self):
        from elidia_cli.mcp_startup import start_background_mcp_discovery
        import inspect

        params = inspect.signature(start_background_mcp_discovery).parameters
        assert "logger" in params and "thread_name" in params
