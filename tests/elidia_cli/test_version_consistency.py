"""Every variant must ship the same version.

They had drifted: the CLI was 2.0.10 while the desktop and VS Code extension
were both 2.0.0. So aiutils.io/elidia offered "Elidia-Agent-2.0.0" for an app
that bootstraps a 2.0.10 CLI, and a bug report naming a version could mean two
different builds.

This is the same failure the SDK hit at 0.5.0, where the wheel's __version__
disagreed with its own metadata because the version lived in two places. The
answer both times is the same: one source of truth, checked.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def canonical_version() -> str:
    """pyproject.toml is the single source of truth."""
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def _json_version(relative: str) -> str:
    return json.loads((ROOT / relative).read_text())["version"]


def test_python_package_matches_pyproject():
    """A wheel whose __version__ disagrees with its metadata reports the wrong
    version to anyone who asks it at runtime."""
    source = (ROOT / "elidia_cli" / "__init__.py").read_text()
    match = re.search(r'__version__\s*=\s*"([^"]+)"', source)
    assert match, "elidia_cli/__init__.py declares no __version__"
    assert match.group(1) == canonical_version()


@pytest.mark.parametrize(
    "manifest",
    [
        "apps/desktop/package.json",
        "apps/vscode/package.json",
        "acp_registry/agent.json",
    ],
)
def test_variant_matches_the_cli(manifest: str):
    """Desktop installers, the VS Code extension and the ACP registry entry all
    carry a version a user can see — in a filename, a Marketplace listing, or an
    editor's agent picker. They must name the same release."""
    path = ROOT / manifest
    if not path.exists():
        pytest.skip(f"{manifest} is not present in this checkout")
    assert _json_version(manifest) == canonical_version(), (
        f"{manifest} is {_json_version(manifest)} but the CLI is {canonical_version()}"
    )
