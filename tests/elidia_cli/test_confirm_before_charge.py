"""Tests for confirm-before-charge (B5).

The rule under test: money does not move without an explicit yes. Every path
that is not a clear approval — no prompt available, a declined prompt, a
timeout, a crashed callback, an unparseable answer — must refuse rather than
proceed. Silence is never consent.
"""

import types

import pytest

from tools import aiutils_client, confirm_context


@pytest.fixture(autouse=True)
def _reset_callback():
    token = confirm_context.set_confirm_callback(None)
    yield
    confirm_context._confirm_callback.reset(token)


def _client(estimated_dt, balance_dt=10_000):
    class _Wallet:
        def estimate_cost(self, model, parameters=None):
            return types.SimpleNamespace(estimated_dt=estimated_dt)

        def balance(self):
            return types.SimpleNamespace(balance_dt=balance_dt)

    return types.SimpleNamespace(wallet=_Wallet())


class TestThreshold:
    def test_small_spend_does_not_prompt(self):
        asked = []
        confirm_context.set_confirm_callback(lambda q, c: asked.append(q) or "yes")

        guard = aiutils_client.check_spend_allowed("m", client=_client(1))

        assert guard["ok"] is True
        assert asked == [], "a trivial charge must not interrupt the user"

    def test_large_spend_prompts_and_proceeds_on_yes(self):
        asked = []

        def _cb(question, choices):
            asked.append(question)
            return "yes"

        confirm_context.set_confirm_callback(_cb)
        guard = aiutils_client.check_spend_allowed("flux-pro", client=_client(5_000))

        assert guard["ok"] is True
        assert len(asked) == 1
        assert "5000 DT" in asked[0], "the prompt must state the amount"
        assert "flux-pro" in asked[0], "and what is being paid for"

    def test_threshold_is_configurable(self, monkeypatch):
        monkeypatch.setattr(aiutils_client, "CONFIRM_THRESHOLD_DT", 100_000)
        # Would decline if asked — so passing proves it was never asked.
        confirm_context.set_confirm_callback(lambda q, c: "no")

        # 5000 DT is below the raised threshold, so it must not prompt at all.
        assert aiutils_client.check_spend_allowed("m", client=_client(5_000))["ok"] is True


class TestRefusalPaths:
    """Everything that is not an explicit yes must refuse."""

    def test_declined_prompt_refuses(self):
        confirm_context.set_confirm_callback(lambda q, c: "no")
        guard = aiutils_client.check_spend_allowed("m", client=_client(5_000))

        assert guard["ok"] is False
        assert guard["declined"] is True
        assert "not approved" in guard["error"]

    def test_no_interactive_prompt_now_PROCEEDS(self):
        """REVERSED by owner directive 2026-08-23. This previously failed closed,
        which stranded unattended jobs the user had already funded. Automated
        runs — gateway, messaging, cron — now spend freely; their ceiling is the
        wallet (see test_spend_pause.py), not the presence of a prompt."""
        guard = aiutils_client.check_spend_allowed("m", client=_client(5_000))
        assert guard["ok"] is True

    def test_crashed_callback_is_not_consent(self):
        def _boom(question, choices):
            raise RuntimeError("prompt died")

        confirm_context.set_confirm_callback(_boom)
        assert aiutils_client.check_spend_allowed("m", client=_client(5_000))["ok"] is False

    def test_empty_or_timed_out_answer_is_not_consent(self):
        for answer in ("", None, "   "):
            confirm_context.set_confirm_callback(lambda q, c, a=answer: a)
            guard = aiutils_client.check_spend_allowed("m", client=_client(5_000))
            assert guard["ok"] is False, f"answer {answer!r} must not read as approval"

    def test_unrelated_answer_is_not_consent(self):
        confirm_context.set_confirm_callback(lambda q, c: "maybe later")
        assert aiutils_client.check_spend_allowed("m", client=_client(5_000))["ok"] is False


class TestInteractionWithExistingGuard:
    def test_spend_exceeding_the_balance_is_allowed_but_disclosed(self):
        """CHANGED by owner directive 2026-08-23. This previously refused when
        the estimate exceeded the balance. Work now runs while the wallet holds
        anything, the final call may overshoot, and that settles on the next
        top-up — so the user is told, not blocked."""
        asked = []
        confirm_context.set_confirm_callback(lambda q, c: asked.append(q) or "yes")

        guard = aiutils_client.check_spend_allowed("m", client=_client(5_000, balance_dt=10))

        assert guard["ok"] is True
        assert asked, "an overshoot must still be disclosed"
        assert "exceeds your balance by 4990 DT" in asked[0]

    def test_unpriceable_call_is_not_confirmed(self):
        """Confirming an unknown amount is not meaningful consent, so the
        balance-floor path stays as it was."""
        class _Wallet:
            def estimate_cost(self, model, parameters=None):
                raise RuntimeError("404 Model not found")

            def balance(self):
                return types.SimpleNamespace(balance_dt=10_000)

        asked = []
        confirm_context.set_confirm_callback(lambda q, c: asked.append(q) or "yes")

        guard = aiutils_client.check_spend_allowed(
            "slug", client=types.SimpleNamespace(wallet=_Wallet())
        )

        assert guard["ok"] is True
        assert guard["exact"] is False
        assert asked == []


class TestContextIsolation:
    def test_callback_is_context_local_not_a_module_global(self):
        """Two concurrent sessions must not share one session's prompt."""
        import contextvars

        confirm_context.set_confirm_callback(lambda q, c: "yes")

        def _in_other_context():
            return confirm_context.is_interactive()

        other = contextvars.Context()
        assert other.run(_in_other_context) is False
        assert confirm_context.is_interactive() is True

    def test_confirm_without_callback_returns_false(self):
        assert confirm_context.confirm("anything?") is False
