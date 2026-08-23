"""
Where the AiUtils Developer API key lives (B13 — key-holder).

Today the key is read from ``~/.elidia/.env``, and ``load_elidia_dotenv()``
copies that file into ``os.environ`` at import time from several hot modules.
For most CLIs that is unremarkable. For this one it is not: Elidia runs terminal
commands, ``execute_code`` sandboxes and MCP servers **by design**, and every
one of those inherits the parent environment. A spendable production credential
is therefore handed to every subprocess the agent launches, including ones whose
code the user has never read.

So the key gets somewhere the OS can protect: the macOS Keychain, Windows
Credential Manager, or the Secret Service on Linux, via ``keyring``. Read back
on demand, into a variable, not into the environment.

Three deliberate limits:

**The keyring is optional.** It is not a declared dependency, and a headless
Linux box often has no Secret Service at all. Everything here degrades to the
existing env-var path rather than refusing to run — a CLI that stops working
because a keyring daemon is missing is worse than one that keeps a key in a
file.

**Reads are cached for the process.** ``api_key()`` sits on the hot path of
``check_aiutils_requirements``, which runs on every tool availability check. A
Keychain round trip there would be felt, and on macOS could prompt.

**Storing does not remove the .env copy.** Deleting a user's credential because
we think we have a better place for it is not ours to do; :func:`migration_hint`
tells them, and they decide.
"""

from __future__ import annotations

import contextvars
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Developer API keys are issued with this prefix. The gateway rejects anything
# else with "Keys start with 'ak-dev-'", so checking here turns a round trip and
# a 401 into an immediate, specific message at the moment of configuration.
KEY_PREFIX = "ak-dev-"

# What the credential is filed under in the OS store.
SERVICE_NAME = "elidia-agent"
ACCOUNT_NAME = "aiutils-developer-api"

# Same names, and same precedence, as tools/aiutils_client.API_KEY_ENV_VARS.
ENV_VAR_NAMES = ("ELIDIA_KEY", "ELIDIA_API_KEY", "AIUTILS_API_KEY")

# Set by the gateway for the duration of one inbound message, so a call made
# while handling it bills the key that platform user linked rather than the
# operator's. A ContextVar because the gateway handles messages concurrently:
# a module global would let one user's key leak into another's turn.
_session_key_resolver: "contextvars.ContextVar[Optional[Callable[[], Optional[str]]]]" = (
    contextvars.ContextVar("elidia_session_key_resolver", default=None)
)


def set_session_key_resolver(resolver):
    """Install a per-message key lookup; returns the reset token.

    ``resolver`` is called with no arguments and returns a key or None. It is
    called lazily — only when a key is actually needed — so a message that
    never touches a billed tool costs no store read.
    """
    return _session_key_resolver.set(resolver)


def reset_session_key_resolver(token) -> None:
    """Undo :func:`set_session_key_resolver`."""
    try:
        _session_key_resolver.reset(token)
    except (ValueError, LookupError):
        # Reset from a different context than the set — nothing to undo there.
        pass


def load_from_session() -> Optional[str]:
    """The key linked to the platform user whose message is being handled."""
    resolver = _session_key_resolver.get()
    if resolver is None:
        return None
    try:
        return resolver() or None
    except Exception as exc:
        # A broken lookup must fall through to the operator key, not drop the
        # user's message.
        logger.debug("Session key resolver failed: %s", exc)
        return None


_SENTINEL = object()
# ONLY the keyring lookup is cached. Caching the resolved key would freeze the
# environment for the process lifetime, so a test that sets ELIDIA_KEY, a
# gateway reloading its config, or a shell export mid-session would all be
# ignored until restart. The expensive call is the OS round trip; the env read
# is a dict lookup and stays live.
_cached_keyring_key: object = _SENTINEL


def _keyring():
    """The keyring module, or None when it is unavailable or has no backend.

    A missing backend is the normal case on a headless server, not an error —
    ``keyring`` still imports there and raises only when used, so the backend is
    checked up front rather than at the first read.
    """
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
    except Exception as exc:
        logger.debug("keyring unavailable: %s", exc)
        return None
    try:
        if isinstance(keyring.get_keyring(), FailKeyring):
            logger.debug("keyring has no usable backend on this system")
            return None
    except Exception as exc:
        logger.debug("Could not resolve a keyring backend: %s", exc)
        return None
    return keyring


def backend_available() -> bool:
    """True when the OS has somewhere to keep a secret for us."""
    return _keyring() is not None


def backend_name() -> Optional[str]:
    """Human-readable name of the active backend, for `elidia status`."""
    kr = _keyring()
    if kr is None:
        return None
    try:
        return type(kr.get_keyring()).__module__.rsplit(".", 1)[-1]
    except Exception:
        return "unknown"


def looks_like_developer_key(key: Optional[str]) -> bool:
    """True when *key* has the shape the Developer API issues."""
    return bool(key) and key.strip().startswith(KEY_PREFIX)


def validate(key: Optional[str]) -> tuple[bool, Optional[str]]:
    """Check a key's shape. Returns ``(ok, problem)``.

    Only the shape — whether it is live, unrevoked and funded is the server's
    business, and the only honest way to know is to use it. What this catches is
    the paste error: a Portal session token, an OpenAI key, or a key with the
    surrounding quotes still attached. Those otherwise surface as a 401 at the
    first billed call, which reads like a broken tool rather than a wrong key.
    """
    if not key or not key.strip():
        return False, "No API key was provided."
    key = key.strip()

    if key.startswith(("sk-", "sk_")):
        return False, (
            "That looks like an OpenAI-style key. The AiUtils Developer API "
            f"issues keys beginning with '{KEY_PREFIX}' — get one from the "
            "Developer Console."
        )
    if key.startswith(("eyJ", "Bearer ")):
        return False, (
            "That looks like a session token, not an API key. Developer API "
            f"keys begin with '{KEY_PREFIX}'."
        )
    if not key.startswith(KEY_PREFIX):
        prefix = key[:7] + "…" if len(key) > 7 else key
        return False, (
            f"Developer API keys begin with '{KEY_PREFIX}'; this one begins "
            f"with '{prefix}'. Check you copied the whole key from the "
            "Developer Console."
        )
    if len(key) <= len(KEY_PREFIX):
        return False, "The key is only the prefix — the rest is missing."
    return True, None


def store(key: str) -> tuple[bool, Optional[str]]:
    """Put *key* in the OS credential store. Returns ``(stored, problem)``.

    Refuses to store a key that fails :func:`validate`: writing a bad
    credential into the keychain just relocates the confusion, and the user
    then has to find and clear it.
    """
    logger.debug("Entered into store: len=%s", len(key or ""))
    ok, problem = validate(key)
    if not ok:
        return False, problem

    kr = _keyring()
    if kr is None:
        return False, (
            "No OS credential store is available on this system. The key stays "
            "in ~/.elidia/.env, which works but is readable by any process that "
            "inherits this environment."
        )
    try:
        kr.set_password(SERVICE_NAME, ACCOUNT_NAME, key.strip())
    except Exception as exc:
        logger.warning("Could not write the API key to the keyring: %s", exc)
        return False, f"The OS credential store rejected the write: {exc}"

    global _cached_keyring_key
    _cached_keyring_key = key.strip()
    return True, None


def load_from_keyring() -> Optional[str]:
    """The stored key, or None. Never raises.

    Cached for the process: ``api_key()`` sits on the hot path of
    ``check_aiutils_requirements``, which runs on every tool availability check,
    and a Keychain round trip there would be felt — and on macOS could prompt.
    """
    global _cached_keyring_key
    if _cached_keyring_key is not _SENTINEL:
        return _cached_keyring_key  # type: ignore[return-value]

    kr = _keyring()
    if kr is None:
        _cached_keyring_key = None
        return None
    try:
        value = kr.get_password(SERVICE_NAME, ACCOUNT_NAME) or None
    except Exception as exc:
        # A locked keychain, a denied prompt, a dead D-Bus. Falling back to the
        # env var is better than failing the whole CLI over it. NOT cached — a
        # keychain the user unlocks mid-session should start working.
        logger.debug("Could not read the API key from the keyring: %s", exc)
        return None
    _cached_keyring_key = value
    return value


def load_from_env() -> Optional[str]:
    """The key from the environment, in the documented precedence order."""
    for name in ENV_VAR_NAMES:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def load() -> Optional[str]:
    """The API key from wherever it lives, keyring first.

    Order: the key linked to the platform user being served, then the OS
    keyring, then the environment.

    The session key comes first because it is the only one that identifies a
    *person*: on a gateway serving many users through one bot, falling back to
    the operator's key would bill their wallet for someone else's work.

    The keyring beats the environment because it is where a user deliberately
    put the key, while an env var may be a leftover from a shell open for a
    week. An explicit ``ELIDIA_KEY=... elidia ...`` still works — see
    :func:`load_preferring_env`.
    """
    return load_from_session() or load_from_keyring() or load_from_env()


def load_preferring_env() -> Optional[str]:
    """Env first, keyring second — for a one-off override on the command line."""
    return load_from_env() or load_from_keyring()


def delete() -> bool:
    """Remove the stored key. True when something was removed."""
    logger.debug("Entered into delete")
    kr = _keyring()
    if kr is None:
        return False
    try:
        if kr.get_password(SERVICE_NAME, ACCOUNT_NAME) is None:
            return False
        kr.delete_password(SERVICE_NAME, ACCOUNT_NAME)
    except Exception as exc:
        logger.warning("Could not delete the API key from the keyring: %s", exc)
        return False
    invalidate_cache()
    return True


def invalidate_cache() -> None:
    """Forget the cached keyring lookup so the next read goes back to the OS."""
    global _cached_keyring_key
    _cached_keyring_key = _SENTINEL


def source() -> str:
    """Where the key currently in use came from, for `elidia status`."""
    if load_from_keyring():
        return "os-keychain"
    if load_from_env():
        return "environment"
    return "not-configured"


def migration_hint() -> Optional[str]:
    """Advice when the key is in the environment and could be better protected.

    Deliberately a hint rather than an automatic move. The .env file may be
    deployment-managed, shared with the gateway, or version-controlled by the
    user's own tooling; silently relocating someone's credential and leaving
    them to discover it is not a fix.
    """
    if load_from_keyring():
        return None
    if not load_from_env():
        return None
    if not backend_available():
        return None
    return (
        "Your AiUtils key is in the environment, so every command and MCP "
        "server Elidia starts inherits it. Run 'elidia key store' to move it "
        f"into the {backend_name()} keychain instead."
    )
