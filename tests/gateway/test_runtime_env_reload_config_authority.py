"""Regression tests for gateway per-turn env reload preserving config authority.

Issue #19158: startup bridges config.yaml agent.max_turns into
ELIDIA_MAX_ITERATIONS, but a later per-turn load_dotenv(..., override=True)
can restore a stale .env ELIDIA_MAX_ITERATIONS value before the next turn.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from gateway import run as gateway_run


def test_reload_runtime_env_preserves_config_max_turns(tmp_path: Path, monkeypatch) -> None:
    elidia_home = tmp_path / ".elidia"
    elidia_home.mkdir()
    (elidia_home / "config.yaml").write_text(
        yaml.safe_dump({"agent": {"max_turns": 9000}}),
        encoding="utf-8",
    )
    (elidia_home / ".env").write_text(
        "ELIDIA_MAX_ITERATIONS=90\nOPENROUTER_API_KEY=fresh-key\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(gateway_run, "_elidia_home", elidia_home)
    monkeypatch.setenv("ELIDIA_MAX_ITERATIONS", "9000")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    gateway_run._reload_runtime_env_preserving_config_authority()

    assert os.environ["OPENROUTER_API_KEY"] == "fresh-key"
    assert os.environ["ELIDIA_MAX_ITERATIONS"] == "9000"


def test_reload_runtime_env_keeps_env_max_iterations_when_config_omits_key(
    tmp_path: Path, monkeypatch
) -> None:
    elidia_home = tmp_path / ".elidia"
    elidia_home.mkdir()
    (elidia_home / "config.yaml").write_text(yaml.safe_dump({"agent": {}}), encoding="utf-8")
    (elidia_home / ".env").write_text("ELIDIA_MAX_ITERATIONS=123\n", encoding="utf-8")

    monkeypatch.setattr(gateway_run, "_elidia_home", elidia_home)
    monkeypatch.delenv("ELIDIA_MAX_ITERATIONS", raising=False)

    gateway_run._reload_runtime_env_preserving_config_authority()

    assert os.environ["ELIDIA_MAX_ITERATIONS"] == "123"
