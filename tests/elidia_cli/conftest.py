"""Fixtures shared across elidia_cli kanban tests."""

from __future__ import annotations

import contextlib
import importlib

import pytest


@pytest.fixture
def all_assignees_spawnable(monkeypatch):
    """Pretend every assignee maps to a real Elidia profile.

    Most dispatcher tests use synthetic assignees ("alice", "bob") that
    don't correspond to actual profile directories on disk. Without this
    patch, the dispatcher's profile-exists guard (PR #20105) routes
    those tasks into ``skipped_nonspawnable`` instead of spawning, which
    would break tests that assert spawn behavior.
    """
    from elidia_cli import profiles
    monkeypatch.setattr(profiles, "profile_exists", lambda name: True)


@pytest.fixture(autouse=True)
def _suppress_concurrent_elidia_gate(request, monkeypatch):
    """Default ``_detect_concurrent_elidia_instances`` to ``[]`` for every test.

    The Windows update path now refuses to proceed when another
    ``elidia.exe`` is detected (issue #26670). On a developer's Windows
    machine running the test suite via ``elidia`` itself, this would
    flag the running agent as a concurrent instance and abort every
    ``cmd_update`` test. Tests that want to exercise the gate explicitly
    re-patch ``_detect_concurrent_elidia_instances`` with their own
    return value — autouse here gives a clean default without touching
    the rest of the suite.

    Tests that need to call the REAL function (e.g. unit tests for the
    helper itself) opt out with ``@pytest.mark.real_concurrent_gate``.
    """
    if request.node.get_closest_marker("real_concurrent_gate"):
        return
    try:
        from elidia_cli import main as _cli_main
    except Exception:
        return
    monkeypatch.setattr(
        _cli_main, "_detect_concurrent_elidia_instances", lambda *_a, **_k: []
    )


# ---------------------------------------------------------------------------
# Module-purge isolation
# ---------------------------------------------------------------------------

def purge_elidia_modules():
    """Drop cached elidia modules so the next import re-reads ELIDIA_HOME.

    Returns the removed modules, which the caller MUST put back — see
    :func:`restore_elidia_modules`.

    Several kanban fixtures purged ``sys.modules`` to force a re-import under a
    fresh ELIDIA_HOME and never restored it. That looks local but is not: test
    modules already collected hold references to the OLD module objects and the
    functions inside them. After a purge, ``elidia_cli.service_manager`` (say)
    is re-imported as a *brand new* module object, so a later

        monkeypatch.setattr("elidia_cli.service_manager.detect_service_manager", ...)

    patches the new object while the test's own imported ``get_service_manager``
    still lives in the old one. The patch silently does nothing, the real
    function runs, and the test fails somewhere that looks unrelated to kanban.

    That single unrestored purge was responsible for a large block of
    order-dependent failures across service_manager, gateway_service, setup,
    tools_config, models and plugins — every one of which passes in isolation,
    which is what made it look like many separate bugs.
    """
    import sys

    removed = {}
    for name in list(sys.modules):
        if name.startswith(("elidia_cli", "elidia_state")) or name == "elidia_constants":
            removed[name] = sys.modules.pop(name)
    return removed


def restore_elidia_modules(removed):
    """Undo :func:`purge_elidia_modules`.

    Also drops modules imported *during* the test, so the fresh-ELIDIA_HOME
    copies do not outlive it — otherwise the restore would simply swap which
    generation leaks.
    """
    import sys

    for name in list(sys.modules):
        if name.startswith(("elidia_cli", "elidia_state")) or name == "elidia_constants":
            del sys.modules[name]
    sys.modules.update(removed)


@pytest.fixture
def elidia_module_purge():
    """Purge cached elidia modules for one test, restoring them afterwards."""
    removed = purge_elidia_modules()
    try:
        yield
    finally:
        restore_elidia_modules(removed)


@contextlib.contextmanager
def temporarily_reloaded(*modules):
    """Reload *modules* for the duration of the block, then put them back.

    ``importlib.reload`` re-executes the module body, which builds NEW class and
    function objects and rebinds them in the module's namespace. Anything that
    captured the old objects — every test module already collected — keeps
    pointing at them, so afterwards::

        isinstance(elidia_cli.main.something(), _UpdateOutputStream)  # False

    with both names printing identically. The curator fixtures reloaded
    elidia_constants, agent.curator and elidia_cli.main to pick up a fresh
    ELIDIA_HOME and left them that way, which broke test_update_hangup_protection,
    test_setup, test_setup_model_provider, test_whatsapp_setup_ordering,
    test_portal_cli, test_gmi_provider and test_regression_16767 — all of which
    pass on their own.

    Reloading a second time on teardown would NOT fix it: a reload always
    produces new objects. Restoring identity means restoring the namespace, so
    this snapshots ``__dict__`` and puts the original objects back — including
    any module-level caches, which the reload had also reset.
    """
    saved = [(module, dict(module.__dict__)) for module in modules]
    try:
        for module in modules:
            importlib.reload(module)
        yield
    finally:
        for module, snapshot in reversed(saved):
            module.__dict__.clear()
            module.__dict__.update(snapshot)


@contextlib.contextmanager
def reimported(name: str):
    """Re-import *name* inside the block, then restore it completely.

    Restoring ``sys.modules`` alone is NOT enough, and the gap is invisible: a
    submodule is also an ATTRIBUTE of its parent package, and re-importing
    rebinds that attribute to the new module object. Put back only the
    sys.modules entry and you get::

        sys.modules["elidia_cli.main"] is original   -> True
        elidia_cli.main               is original   -> False

    ``monkeypatch.setattr("elidia_cli.main.x", ...)`` resolves through the
    PACKAGE ATTRIBUTE, so it then patches the new module while the test holds
    symbols imported from the old one. The patch silently does nothing and the
    real function runs — which is how test_env_loader was breaking
    test_whatsapp_setup_ordering, test_setup, test_setup_model_provider,
    test_gmi_provider, test_portal_cli and test_regression_16767, all of which
    pass on their own.
    """
    import importlib
    import sys

    previous = sys.modules.get(name)
    parent_name, _, child = name.rpartition(".")
    parent = sys.modules.get(parent_name) if parent_name else None
    had_attr = parent is not None and hasattr(parent, child)
    previous_attr = getattr(parent, child, None) if had_attr else None

    sys.modules.pop(name, None)
    try:
        yield importlib.import_module(name)
    finally:
        if previous is not None:
            sys.modules[name] = previous
        else:
            sys.modules.pop(name, None)
        if parent is not None:
            if had_attr:
                setattr(parent, child, previous_attr)
            else:
                try:
                    delattr(parent, child)
                except AttributeError:
                    pass
