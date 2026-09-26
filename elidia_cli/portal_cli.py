"""``elidia portal`` — the human-readable entry point for Elidia Portal.

Running ``elidia portal`` with no subcommand performs the one-shot Portal
onboarding: store an AiUtils Developer API key (``ak-dev-…``, kept in the OS
keychain — same as ``elidia key store``), pick a model, and switch the inference
provider to the AiUtils Developer API. It is identical to
``elidia setup --portal`` and runs the same flow as the first-time quick setup.
The Portal's former OAuth device-code login no longer exists (AIUT-3434).

Subcommands:
  (none)   Log in to Elidia Portal + set it up (one-shot onboarding).
  login    Explicit alias for the default one-shot onboarding.
  info     Show Portal auth state + which Tool Gateway tools are routed.
  open     Open the Portal API-keys page in the user's default browser.
  tools    List Tool Gateway tools and which are active in the current config.

This command is intentionally minimal — it does not duplicate functionality
already in ``elidia auth`` or ``elidia tools``. It's the onboarding + discovery
surface for the Portal itself.
"""
from __future__ import annotations

import logging
import sys
import webbrowser

from elidia_cli.colors import Colors, color
from elidia_cli.config import load_config

logger = logging.getLogger(__name__)

DEFAULT_PORTAL_URL = "https://developer.aiutils.io"
API_KEYS_URL = "https://developer.aiutils.io/api-keys"
DOCS_URL = "https://aiutils.io/elidia/user-guide/features/tool-gateway"


def _cmd_status(args) -> int:
    """Show Portal auth (AiUtils Developer API key) + Tool Gateway routing summary."""
    logger.debug("Entered into _cmd_status")
    from elidia_cli.auth import PROVIDER_REGISTRY, _resolve_api_key_provider_secret
    from elidia_cli.elidia_subscription import get_elidia_subscription_features

    config = load_config() or {}

    pconfig = PROVIDER_REGISTRY["aiutils"]
    try:
        key, key_source = _resolve_api_key_provider_secret("aiutils", pconfig)
    except Exception:
        key, key_source = "", ""

    logged_in = bool(key)

    print()
    print(color("  Elidia Portal", Colors.MAGENTA))
    print(color("  ───────────", Colors.MAGENTA))
    if logged_in:
        print(
            f"  Auth:    {color('✓ AiUtils Developer API key', Colors.GREEN)}"
            f" {key[:8]}… ({key_source})"
        )
        print(f"  Portal:  {DEFAULT_PORTAL_URL}")
        print(f"  API:     {pconfig.inference_base_url}")
    else:
        print(f"  Auth:    {color('no AiUtils Developer API key', Colors.YELLOW)}")
        print(f"  Get key: {API_KEYS_URL}")
        print(f"  Login:   elidia portal")

    # Provider selection (independent of auth)
    model_cfg = config.get("model") if isinstance(config.get("model"), dict) else {}
    provider = str(model_cfg.get("provider") or "").strip().lower()
    if provider in ("aiutils", "elidia"):
        print(f"  Model:   {color('✓ using Elidia as inference provider', Colors.GREEN)}")
    elif provider:
        print(f"  Model:   currently {provider} (switch with `elidia model`)")

    # Tool Gateway routing
    print()
    print(color("  Tool Gateway", Colors.MAGENTA))
    print(color("  ────────────", Colors.MAGENTA))
    try:
        features = get_elidia_subscription_features(config)
    except Exception:
        features = None

    if features is None:
        print("  (could not resolve subscription state)")
        return 0

    rows = []
    for feat in features.items():
        if feat.managed_by_elidia:
            state = color("via Elidia Portal", Colors.GREEN)
        elif feat.active and feat.current_provider:
            state = feat.current_provider
        elif feat.active:
            state = "active"
        else:
            state = color("not configured", Colors.DIM)
        rows.append((feat.label, state))

    width = max((len(r[0]) for r in rows), default=0)
    for label, state in rows:
        print(f"  {label:<{width}}   {state}")

    if not logged_in:
        print()
        print(color(f"  Docs: {DOCS_URL}", Colors.DIM))
    return 0


def _cmd_open(args) -> int:
    """Open the Portal API-keys page in the default browser."""
    target = API_KEYS_URL
    print(f"Opening {target}")
    try:
        opened = webbrowser.open(target)
    except Exception:
        opened = False
    if not opened:
        print()
        print("Could not launch a browser. Visit the URL above manually.")
        return 1
    return 0


def _cmd_tools(args) -> int:
    """List the Tool Gateway catalog + current routing."""
    from elidia_cli.elidia_subscription import get_elidia_subscription_features

    config = load_config() or {}
    try:
        features = get_elidia_subscription_features(config)
    except Exception:
        print("Could not resolve Tool Gateway state.", file=sys.stderr)
        return 1

    # Static catalog — the partners Tool Gateway routes to today.
    catalog = [
        ("web",       "Web search & extract",  "Firecrawl"),
        ("image_gen", "Image generation",      "FAL"),
        ("tts",       "Text-to-speech",        "OpenAI TTS"),
        ("browser",   "Browser automation",    "Browser Use"),
        ("modal",     "Cloud terminal",        "Modal"),
    ]

    print()
    print(color("  Tool Gateway catalog", Colors.MAGENTA))
    print(color("  ────────────────────", Colors.MAGENTA))

    if not features.elidia_auth_present:
        print(color("  Not logged into Elidia Portal — sign in with `elidia portal`.", Colors.YELLOW))
        print()

    label_width = max(len(label) for _, label, _ in catalog)
    for key, label, partner in catalog:
        feat = features.features.get(key)
        if feat is None:
            state = color("unknown", Colors.DIM)
        elif feat.managed_by_elidia:
            state = color("✓ via Elidia Portal", Colors.GREEN)
        elif feat.active and feat.current_provider:
            state = feat.current_provider
        elif feat.active:
            state = "active"
        else:
            state = color("not configured", Colors.DIM)
        print(f"  {label:<{label_width}}  partner: {partner:<14} {state}")

    print()
    print(color(f"  Manage your API keys: {API_KEYS_URL}", Colors.DIM))
    print(color(f"  Docs: {DOCS_URL}", Colors.DIM))
    return 0


def _cmd_login(args) -> int:
    """Run the one-shot Elidia Portal onboarding (API key + model + provider).

    It reuses the exact wiring behind `elidia setup --portal` (which in
    turn runs the same Elidia flow as the first-time quick setup), so the
    commands stay in lockstep: store the AiUtils Developer API key, pick a
    model, and switch the inference provider to the AiUtils Developer API.

    Login means storing an AiUtils Developer API key, the same key
    `elidia auth add elidia` and `elidia key store` save.
    """
    from elidia_cli.setup import _run_portal_one_shot

    config = load_config() or {}
    try:
        _run_portal_one_shot(config)
    except (KeyboardInterrupt, EOFError):
        print()
        print("Portal setup cancelled.")
        return 1
    return 0


def portal_command(args) -> int:
    """Top-level dispatch for `elidia portal <subcommand>`."""
    sub = getattr(args, "portal_command", None)
    if sub in {None, "", "login"}:
        # Default to the one-shot onboarding — equivalent to
        # `elidia setup --portal`; authenticates with an AiUtils Developer API
        # key (see elidia_cli.key_cli), never OAuth.
        return _cmd_login(args)
    if sub in {"info", "status"}:
        # `status` kept as a back-compat alias for the prior default.
        return _cmd_status(args)
    if sub == "open":
        return _cmd_open(args)
    if sub == "tools":
        return _cmd_tools(args)
    print(f"Unknown portal subcommand: {sub}", file=sys.stderr)
    print("Run `elidia portal -h` for usage.", file=sys.stderr)
    return 1


def add_parser(subparsers) -> None:
    """Register `elidia portal` on the given argparse subparsers object."""
    portal_parser = subparsers.add_parser(
        "portal",
        help="Set up Elidia Portal (login, model pick, Tool Gateway); see also `portal info`",
        description=(
            "Run `elidia portal` with no subcommand to log in to Elidia Portal "
            "and set it up — pick a model, set Elidia as your provider, and offer "
            "the Tool Gateway (identical to `elidia setup --portal`; signs in "
            "with an AiUtils Developer API key). "
            "Subcommands: login (default), info, open, tools."
        ),
    )
    portal_sub = portal_parser.add_subparsers(dest="portal_command")

    portal_sub.add_parser(
        "login",
        help="Log in to Elidia Portal + set it up (default; one-shot onboarding)",
    )
    portal_sub.add_parser(
        "info",
        help="Show Portal auth + Tool Gateway routing summary",
    )
    # `status` retained as a hidden back-compat alias for `info`.
    portal_sub.add_parser("status")
    portal_sub.add_parser(
        "open",
        help="Open the Portal subscription page in your default browser",
    )
    portal_sub.add_parser(
        "tools",
        help="List Tool Gateway tools and which are routed via Elidia",
    )

    portal_parser.set_defaults(func=portal_command)
