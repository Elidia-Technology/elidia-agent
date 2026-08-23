"""
Per-user AiUtils API keys for gateway platforms (B14).

The gateway serves many people through one bot. Until now it resolved a single
``ELIDIA_KEY`` from the operator's environment, so every Telegram, WhatsApp or
Slack user's DT spend was billed to the **operator's** wallet. Fifty users, one
bill, and no way for any of them to use the balance they paid for.

``/link`` attaches a person's own Developer API key to their platform identity,
so their calls draw on their own DT.

Three things this refuses to do, all of them load-bearing:

**It will not accept a key in a group.** A key pasted into a group chat is
visible to everyone in it and to the platform's history forever. The link
command works in a direct message only, and says why.

**It never echoes the key.** Confirmations show a masked prefix — enough to tell
which key was stored, useless to anyone reading over a shoulder.

**It does not pretend the store is private from the operator.** The gateway must
hold usable credentials to spend on a user's behalf, so encryption at rest would
only be theatre against whoever runs the process. The file is 0600 and the keys
are never logged; the honest summary is that linking a key trusts the gateway
operator, and :func:`trust_notice` says so to the user before they do it.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STORE_FILENAME = "gateway-linked-keys.json"

# Owner-only. The gateway may run as a service account on a shared host.
_FILE_MODE = 0o600
_DIR_MODE = 0o700


def _store_path() -> Path:
    home = os.getenv("ELIDIA_HOME") or str(Path.home() / ".elidia")
    directory = Path(home)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(_DIR_MODE)
    except OSError:
        # A shared or mounted home may refuse; the file mode below still applies.
        logger.debug("Could not tighten permissions on %s", directory)
    return directory / STORE_FILENAME


def identity(platform: str, user_id: str) -> Optional[str]:
    """Storage key for a platform identity, or None when either half is missing.

    Both halves are required: user ids are only unique *within* a platform, so
    keying on the id alone would let a Telegram user id collide with a Slack one
    and hand someone else's key to the wrong person.
    """
    platform = (platform or "").strip().lower()
    user_id = str(user_id or "").strip()
    if not platform or not user_id:
        return None
    return f"{platform}:{user_id}"


def _load_all() -> dict:
    try:
        path = _store_path()
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        # Never log the contents. A corrupt store means "nobody is linked",
        # which falls back to the operator key rather than breaking the bot.
        logger.warning("Could not read the linked-key store: %s", type(exc).__name__)
        return {}


def _save_all(data: dict) -> bool:
    """Write the store atomically with owner-only permissions."""
    path = _store_path()
    try:
        # mkstemp creates with 0600 already, so the secret is never briefly
        # world-readable between write and chmod.
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".keys-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            os.chmod(tmp_name, _FILE_MODE)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return True
    except Exception as exc:
        logger.warning("Could not write the linked-key store: %s", type(exc).__name__)
        return False


def masked(key: str) -> str:
    """Enough of a key to recognise it, not enough to use it."""
    key = (key or "").strip()
    if len(key) <= 12:
        return (key[:4] + "…") if key else ""
    return f"{key[:11]}…{key[-4:]}"


def link(platform: str, user_id: str, key: str) -> tuple[bool, str]:
    """Attach *key* to a platform identity. Returns ``(ok, message)``.

    The message is safe to send back to the user — it never contains the key.
    """
    logger.debug("Entered into link: platform=%s", platform)
    ident = identity(platform, user_id)
    if ident is None:
        return False, "I could not tell who you are on this platform, so I cannot link a key."

    from elidia_cli import key_store

    ok, problem = key_store.validate(key)
    if not ok:
        return False, f"Not linked: {problem}"

    data = _load_all()
    replacing = ident in data
    data[ident] = {"api_key": key.strip()}
    if not _save_all(data):
        return False, "Could not save the key. Nothing was stored."

    verb = "Replaced" if replacing else "Linked"
    return True, (
        f"{verb} your AiUtils key ({masked(key)}). Your usage now bills your own "
        "DT wallet.\n\nDelete the message you pasted it in — it is still in this "
        "chat's history."
    )


def unlink(platform: str, user_id: str) -> tuple[bool, str]:
    """Detach the key from a platform identity."""
    logger.debug("Entered into unlink: platform=%s", platform)
    ident = identity(platform, user_id)
    if ident is None:
        return False, "I could not tell who you are on this platform."

    data = _load_all()
    if ident not in data:
        return False, "You do not have a key linked."
    del data[ident]
    if not _save_all(data):
        return False, "Could not update the store. The key is still linked."
    return True, "Unlinked. Your usage now bills the operator's wallet again."


def linked_key(platform: str, user_id: str) -> Optional[str]:
    """The key linked to a platform identity, or None."""
    ident = identity(platform, user_id)
    if ident is None:
        return None
    entry = _load_all().get(ident)
    if not isinstance(entry, dict):
        return None
    key = entry.get("api_key")
    return key.strip() if isinstance(key, str) and key.strip() else None


def status(platform: str, user_id: str) -> str:
    """A line the user can read about their own linkage."""
    key = linked_key(platform, user_id)
    if key:
        return (
            f"Your AiUtils key is linked ({masked(key)}). Usage bills your own "
            "DT wallet. Use /link off to remove it."
        )
    return (
        "You have no AiUtils key linked, so your usage bills the operator's "
        "wallet. Send /link ak-dev-… in a direct message to use your own."
    )


def trust_notice() -> str:
    """What a user should know before pasting a key into someone's bot."""
    return (
        "Linking a key means this gateway can spend your DT. It stores the key "
        "on the machine it runs on, so whoever operates that machine can read "
        "it. Only link a key to a gateway you trust, and revoke it in the "
        "Developer Console if that changes."
    )
