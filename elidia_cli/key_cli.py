"""``elidia key`` — move the AiUtils Developer API key out of the environment.

See :mod:`elidia_cli.key_store` for why that matters: this agent starts terminal
commands, code sandboxes and MCP servers by design, and every one of them
inherits ``os.environ``.
"""

from __future__ import annotations

import getpass
import logging
import sys

from elidia_cli import key_store

logger = logging.getLogger(__name__)


def _masked(key: str) -> str:
    """Enough to recognise which key it is, not enough to use it."""
    if len(key) <= 12:
        return key[:4] + "…"
    return f"{key[:11]}…{key[-4:]}"


def cmd_key_status(args) -> int:  # noqa: ANN001
    logger.debug("Entered into cmd_key_status")
    source = key_store.source()
    backend = key_store.backend_name()

    print()
    print("◆ AiUtils Developer API key")
    if source == "not-configured":
        print("  Status:   ✗ not configured")
        print("  Get one:  https://developer.aiutils.io")
        print("  Then:     elidia key store")
        return 0

    key = key_store.load()
    print(f"  Status:   ✓ configured  ({_masked(key or '')})")
    if source == "os-keychain":
        print(f"  Stored:   {backend} keychain")
        print("  Reach:    this process only — not inherited by subprocesses")
    else:
        print("  Stored:   environment / ~/.elidia/.env")
        print("  Reach:    inherited by every command, sandbox and MCP server")

    hint = key_store.migration_hint()
    if hint:
        print()
        print(f"  {hint}")
    return 0


def cmd_key_store(args) -> int:  # noqa: ANN001
    logger.debug("Entered into cmd_key_store")
    if not key_store.backend_available():
        print(
            "No OS credential store is available here, so there is nowhere "
            "safer to put the key than the file it is already in.",
            file=sys.stderr,
        )
        return 1

    key = getattr(args, "key", None)
    if not key:
        # getpass, not input: the key must not land in the terminal scrollback
        # or the shell history of whoever is watching.
        key = getpass.getpass("Paste your AiUtils Developer API key (ak-dev-…): ")

    ok, problem = key_store.validate(key)
    if not ok:
        print(f"Not stored: {problem}", file=sys.stderr)
        return 1

    stored, problem = key_store.store(key)
    if not stored:
        print(f"Not stored: {problem}", file=sys.stderr)
        return 1

    print(f"✓ Stored in the {key_store.backend_name()} keychain.")
    if key_store.load_from_env():
        # Never delete it for them — the file may be deployment-managed or
        # shared with the gateway, and quietly removing someone's credential
        # is not a fix.
        print()
        print(
            "  Note: a key is still set in your environment (~/.elidia/.env). "
            "The keychain takes precedence, but the env copy is still "
            "inherited by subprocesses until you remove it yourself."
        )
    return 0


def cmd_key_remove(args) -> int:  # noqa: ANN001
    logger.debug("Entered into cmd_key_remove")
    if key_store.delete():
        print("✓ Removed from the OS keychain.")
        if key_store.load_from_env():
            print("  A key is still set in your environment, so Elidia will use that.")
        return 0
    print("Nothing to remove — no key was stored in the OS keychain.")
    return 0


def register_cli(parser) -> None:  # noqa: ANN001
    """Attach the `key` subcommands to *parser*."""
    sub = parser.add_subparsers(dest="key_command")

    p_status = sub.add_parser("status", help="Show where the API key is stored")
    p_status.set_defaults(func=cmd_key_status)

    p_store = sub.add_parser(
        "store", help="Move the API key into the OS keychain",
    )
    p_store.add_argument(
        "key", nargs="?",
        help="The key. Omit to be prompted without it entering shell history.",
    )
    p_store.set_defaults(func=cmd_key_store)

    p_remove = sub.add_parser("remove", help="Delete the key from the OS keychain")
    p_remove.set_defaults(func=cmd_key_remove)
