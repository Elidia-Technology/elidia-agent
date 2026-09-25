from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from setuptools import setup


REPO_ROOT = Path(__file__).parent.resolve()

# Bare data directories (no __init__.py) shipped into the wheel under
# ``...data/data/<name>/`` and resolved at runtime by
# elidia_constants._get_packaged_data_dir() via
# ``sysconfig.get_path("data")/<name>``. These are invisible to packages.find
# (not packages) and to package-data (which only attaches to a package), so
# they must be listed as data-files here — and ONLY here.
#
# A ``[tool.setuptools.data-files]`` table in pyproject.toml *replaces* this
# setup.py ``data_files`` kwarg rather than merging with it. Mixing the two
# silently dropped skills/optional-skills from every wheel while locales
# (declared only in pyproject) survived, leaving fresh installs with
# "Skill 'elidia-agent' not found" (#3415). Keep all data-files in this one
# list; the sdist side is grafted in MANIFEST.in.
DATA_DIRS = (
    "locales",
    "skills",
    "optional-skills",
    "optional-mcps",
)


def _data_file_tree(root_name: str) -> list[tuple[str, list[str]]]:
    root = REPO_ROOT / root_name
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(REPO_ROOT)
        grouped[str(rel_path.parent)].append(str(rel_path))
    return sorted(grouped.items())


setup(
    data_files=[
        entry
        for name in DATA_DIRS
        for entry in _data_file_tree(name)
    ]
)
