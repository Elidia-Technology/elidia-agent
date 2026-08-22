"""Resolve ELIDIA_HOME for standalone skill scripts.

Skill scripts may run outside the Elidia process (e.g. system Python,
nix env, CI) where ``elidia_constants`` is not importable.  This module
provides the same ``get_elidia_home()`` and ``display_elidia_home()``
contracts as ``elidia_constants`` without requiring it on ``sys.path``.

When ``elidia_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``elidia_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``ELIDIA_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from elidia_constants import display_elidia_home as display_elidia_home
    from elidia_constants import get_elidia_home as get_elidia_home
except (ModuleNotFoundError, ImportError):

    def get_elidia_home() -> Path:
        """Return the Elidia home directory (default: ~/.elidia).

        Mirrors ``elidia_constants.get_elidia_home()``."""
        val = os.environ.get("ELIDIA_HOME", "").strip()
        return Path(val) if val else Path.home() / ".elidia"

    def display_elidia_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``elidia_constants.display_elidia_home()``."""
        home = get_elidia_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
