"""Tests for gateway restart-loop defenses (#30719).

Covers:
- Defense 1: gateway stop/restart refuse when _ELIDIA_GATEWAY=1
- Defense 2: cron create rejects prompts containing gateway lifecycle commands
- _contains_gateway_lifecycle_command pattern matching
"""

import os
from argparse import Namespace

import pytest

from elidia_cli.cron import (
    _contains_gateway_lifecycle_command,
    cron_command,
)


# ---------------------------------------------------------------------------
# Defense 2: _contains_gateway_lifecycle_command pattern tests
# ---------------------------------------------------------------------------

class TestGatewayLifecyclePattern:
    """Verify the regex catches gateway lifecycle commands."""

    @pytest.mark.parametrize("text", [
        "elidia gateway restart",
        "elidia gateway stop",
        "elidia gateway start",
        "elidia  gateway  restart",         # double spaces
        "Elidia Gateway Restart",           # mixed case (regex is (?i))
        "ELIDIA GATEWAY RESTART",           # uppercase
    ])
    def test_elidia_gateway_commands(self, text):
        assert _contains_gateway_lifecycle_command(text), f"Should match: {text!r}"

    @pytest.mark.parametrize("text", [
        "launchctl kickstart gui/501/ai.elidia.gateway",
        "launchctl unload ~/Library/LaunchAgents/ai.elidia.gateway.plist",
        "launchctl stop ai.elidia.gateway",
        "systemctl restart elidia-gateway",
        "systemctl stop elidia-gateway.service",
        "systemctl start elidia-gateway",
    ])
    def test_service_manager_commands(self, text):
        assert _contains_gateway_lifecycle_command(text), f"Should match: {text!r}"

    @pytest.mark.parametrize("text", [
        "kill elidia gateway process",
        "pkill -f elidia.*gateway",
    ])
    def test_kill_commands(self, text):
        assert _contains_gateway_lifecycle_command(text), f"Should match: {text!r}"

    @pytest.mark.parametrize("text", [
        "restart the server application",
        "elidia cron list",
        "elidia update",
        "elidia config set model claude",
        "echo 'just a normal cron job'",
        "run the backup script",
        "gateway is running fine",
        # Regression (#30728 follow-up): legit prompts that merely mention an
        # unrelated gateway + a restart must NOT be blocked.
        "Summarize the API gateway logs and report any restart events from last night",
        "Check if the payment gateway needs a restart after the deploy",
        "Monitor the gateway and tell me if a restart is recommended",
    ])
    def test_safe_commands(self, text):
        assert not _contains_gateway_lifecycle_command(text), f"Should NOT match: {text!r}"


class TestCronCreateLifecycleBlock:
    """Verify cron create rejects gateway lifecycle prompts."""

    @pytest.fixture(autouse=True)
    def _setup_cron_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
        monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
        monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "output")

    def test_block_elidia_gateway_restart(self, capsys):
        args = Namespace(
            cron_command="create",
            schedule="30m",
            prompt="Upgrade elidia then run elidia gateway restart",
            name=None,
            deliver=None,
            repeat=None,
            skill=None,
            skills=None,
            script=None,
            workdir=None,
            profile=None,
            no_agent=False,
        )
        rc = cron_command(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "Blocked" in out
        assert "#30719" in out

    def test_block_launchctl_kickstart(self, capsys):
        args = Namespace(
            cron_command="create",
            schedule="0 9 * * *",
            prompt="Run launchctl kickstart -k gui/501/ai.elidia.gateway",
            name=None,
            deliver=None,
            repeat=None,
            skill=None,
            skills=None,
            script=None,
            workdir=None,
            profile=None,
            no_agent=False,
        )
        rc = cron_command(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "Blocked" in out

    def test_block_script_with_lifecycle_command(self, tmp_path, capsys):
        script = tmp_path / "restart.sh"
        script.write_text("#!/bin/bash\nelidia gateway restart\n")
        args = Namespace(
            cron_command="create",
            schedule="1h",
            prompt=None,
            name=None,
            deliver=None,
            repeat=None,
            skill=None,
            skills=None,
            script=str(script),
            workdir=None,
            profile=None,
            no_agent=False,
        )
        rc = cron_command(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "Blocked" in out

    def test_allow_safe_prompt(self, capsys):
        args = Namespace(
            cron_command="create",
            schedule="30m",
            prompt="Check server health and report status",
            name=None,
            deliver=None,
            repeat=None,
            skill=None,
            skills=None,
            script=None,
            workdir=None,
            profile=None,
            no_agent=False,
        )
        rc = cron_command(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Created job" in out

    def test_allow_empty_prompt(self, capsys):
        """Empty prompt (no lifecycle content) should pass the filter — the
        API will still reject it for lacking prompt+skill, but that's a
        separate validation, not the lifecycle guard."""
        args = Namespace(
            cron_command="create",
            schedule="30m",
            prompt=None,
            name=None,
            deliver=None,
            repeat=None,
            skill=None,
            skills=None,
            script=None,
            workdir=None,
            profile=None,
            no_agent=False,
        )
        rc = cron_command(args)
        # The lifecycle guard passes (no gateway command in prompt).
        # The API rejects it for "requires prompt or skill" → rc 1, but
        # the error message is about prompt/skill, NOT about "Blocked".
        out = capsys.readouterr().out
        assert "Blocked" not in out


# ---------------------------------------------------------------------------
# Defense 1: gateway stop/restart refuse inside gateway
# ---------------------------------------------------------------------------

class TestGatewaySelfTargetingGuard:
    """Verify elidia gateway stop/restart refuse when _ELIDIA_GATEWAY=1."""

    def test_stop_refuses_inside_gateway(self, monkeypatch):
        monkeypatch.setenv("_ELIDIA_GATEWAY", "1")
        from elidia_cli.gateway import gateway_command
        args = Namespace(gateway_command="stop", all=False, system=False)
        with pytest.raises(SystemExit) as exc_info:
            gateway_command(args)
        assert exc_info.value.code == 1

    def test_restart_refuses_inside_gateway(self, monkeypatch):
        monkeypatch.setenv("_ELIDIA_GATEWAY", "1")
        from elidia_cli.gateway import gateway_command
        args = Namespace(gateway_command="restart", all=False, system=False)
        with pytest.raises(SystemExit) as exc_info:
            gateway_command(args)
        assert exc_info.value.code == 1

    def test_stop_allows_outside_gateway(self, monkeypatch):
        # With the gateway marker unset, the self-targeting guard must NOT
        # fire. Prove control reaches the real stop path (rather than driving
        # real signal delivery, which would trip the live-system guard) by
        # short-circuiting the first downstream call with a sentinel.
        monkeypatch.delenv("_ELIDIA_GATEWAY", raising=False)
        import elidia_cli.gateway as gw

        class _Reached(Exception):
            pass

        def _sentinel(*a, **k):
            raise _Reached()

        monkeypatch.setattr(gw, "_dispatch_via_service_manager_if_s6", _sentinel)
        monkeypatch.setattr(gw, "_dispatch_all_via_service_manager_if_s6", _sentinel)
        args = Namespace(gateway_command="stop", all=False, system=False)
        with pytest.raises(_Reached):
            gw.gateway_command(args)

    def test_restart_allows_outside_gateway(self, monkeypatch):
        # Same as above for restart: guard must not fire when the marker is
        # unset. The first thing restart does after the guard is the s6
        # dispatch check — sentinel it so we never reach real signal delivery.
        monkeypatch.delenv("_ELIDIA_GATEWAY", raising=False)
        import elidia_cli.gateway as gw

        class _Reached(Exception):
            pass

        def _sentinel(*a, **k):
            raise _Reached()

        monkeypatch.setattr(gw, "_dispatch_via_service_manager_if_s6", _sentinel)
        monkeypatch.setattr(gw, "_dispatch_all_via_service_manager_if_s6", _sentinel)
        args = Namespace(gateway_command="restart", all=False, system=False)
        with pytest.raises(_Reached):
            gw.gateway_command(args)
