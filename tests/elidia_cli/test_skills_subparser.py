"""Test that skills subparser doesn't conflict (regression test for #898)."""

import argparse


def test_no_duplicate_skills_subparser():
    """Ensure 'skills' subparser is only registered once to avoid Python 3.11+ crash.

    Python 3.11 changed argparse to raise an exception on duplicate subparser
    names instead of silently overwriting (see CPython #94331).

    This test will fail with:
        argparse.ArgumentError: argument command: conflicting subparser: skills

    if the duplicate 'skills' registration is reintroduced.
    """
    # Force a fresh import of the module where the parser is constructed. If
    # there are duplicate 'skills' subparsers, this raises argparse.ArgumentError
    # at module load time.
    #
    # `reimported` restores both sys.modules AND the elidia_cli.main package
    # attribute afterwards. Restoring only sys.modules leaves the attribute
    # pointing at the new module, which is exactly where
    # monkeypatch.setattr("elidia_cli.main.x", ...) lands in other test files —
    # see tests/elidia_cli/conftest.py::reimported.
    from tests.elidia_cli.conftest import reimported

    try:
        with reimported("elidia_cli.main"):
            pass
    except argparse.ArgumentError as e:
        if "conflicting subparser" in str(e):
            raise AssertionError(
                f"Duplicate subparser detected: {e}. "
                "See issue #898 for details."
            ) from e
        raise
