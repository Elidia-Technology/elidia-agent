"""Every npm workspace must have an entry in the root lockfile.

`npm ci` refuses to install when package-lock.json disagrees with the workspace
manifests, and it fails in all three desktop build jobs at once — the slowest,
noisiest place to discover a one-line omission.

This has now happened twice: once bumping apps/desktop to 2.0.10 without
regenerating the lock, and once adding apps/mobile as a new workspace. Both were
found only after a full CI round trip. The check costs milliseconds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text())


def workspace_dirs() -> list[str]:
    """Directories matching the root package.json `workspaces` globs."""
    patterns = _load("package.json").get("workspaces", [])
    found: list[str] = []
    for pattern in patterns:
        if pattern.endswith("/*"):
            parent = ROOT / pattern[:-2]
            if not parent.is_dir():
                continue
            found += [
                str(child.relative_to(ROOT))
                for child in sorted(parent.iterdir())
                if (child / "package.json").is_file()
            ]
        elif (ROOT / pattern / "package.json").is_file():
            found.append(pattern)
    return found


def test_there_are_workspaces_to_check():
    """Guard the guard: a glob that silently matches nothing would make every
    assertion below vacuously true."""
    assert workspace_dirs(), "no npm workspaces resolved — the pattern logic is wrong"


def test_every_workspace_is_in_the_lockfile():
    lock = _load("package-lock.json").get("packages", {})
    missing = [d for d in workspace_dirs() if d not in lock]
    assert not missing, (
        f"package-lock.json has no entry for {missing}. "
        "Run `npm install --package-lock-only` and commit the result — "
        "`npm ci` will fail in every build job without it."
    )


def test_lockfile_versions_match_the_manifests():
    """A version bumped in package.json but not the lock fails `npm ci` too."""
    lock = _load("package-lock.json").get("packages", {})
    mismatched = []
    for d in workspace_dirs():
        manifest_version = _load(f"{d}/package.json").get("version")
        lock_version = lock.get(d, {}).get("version")
        if manifest_version and lock_version and manifest_version != lock_version:
            mismatched.append(f"{d}: manifest {manifest_version} != lock {lock_version}")
    assert not mismatched, "; ".join(mismatched)
