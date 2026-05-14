"""Tests for the Telegram bridge.

Focus areas (in priority order):

1. The gatekeeper *aggressively* drops updates from any sender whose ID does
   not match ``settings.authorized_user_id``.  This is the CRITICAL OPSEC
   contract.
2. The audit-only crew shape (``/check``) never includes the Transaction
   Executor, so even a buggy handler can't accidentally trigger a transaction.
3. ``build_application`` refuses to boot without the required secrets.
4. Address validation and report formatting handle pathological input.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Update, User
from telegram.ext import ApplicationHandlerStop

from web3_crew.crew import build_crew
from web3_crew.telegram_bot import (
    _ADDRESS_RE,
    _extract_address,
    _format_report,
    _gatekeeper,
    build_application,
)

AUTHORIZED_ID = 4242
SOMEONE_ELSE_ID = 9999


@pytest.fixture(autouse=True)
def _wire_settings(monkeypatch):
    """Pin a known authorized user ID for every test in this module."""
    from web3_crew.config import settings as live_settings

    monkeypatch.setattr(live_settings, "authorized_user_id", AUTHORIZED_ID)
    monkeypatch.setattr(live_settings, "telegram_bot_token", "test-bot-token")
    yield


def _fake_update(user_id: int | None) -> Update:
    """Build a minimal :class:`Update` whose ``effective_user`` has ``user_id``."""
    update = MagicMock(spec=Update)
    if user_id is None:
        update.effective_user = None
    else:
        update.effective_user = User(id=user_id, first_name="x", is_bot=False)
    return update


# ---------------------------------------------------------------------------
# Gatekeeper — the OPSEC contract
# ---------------------------------------------------------------------------


class TestGatekeeper:
    @pytest.mark.asyncio
    async def test_drops_update_from_other_user_id(self):
        update = _fake_update(SOMEONE_ELSE_ID)
        with pytest.raises(ApplicationHandlerStop):
            await _gatekeeper(update, MagicMock())

    @pytest.mark.asyncio
    async def test_drops_update_from_user_id_zero(self):
        # Telegram never assigns id=0, but defense in depth.
        update = _fake_update(0)
        with pytest.raises(ApplicationHandlerStop):
            await _gatekeeper(update, MagicMock())

    @pytest.mark.asyncio
    async def test_drops_update_when_effective_user_is_none(self):
        update = _fake_update(None)
        with pytest.raises(ApplicationHandlerStop):
            await _gatekeeper(update, MagicMock())

    @pytest.mark.asyncio
    async def test_drops_off_by_one_user_id(self):
        # Equality must be exact — no truthy/coercion shenanigans.
        update = _fake_update(AUTHORIZED_ID + 1)
        with pytest.raises(ApplicationHandlerStop):
            await _gatekeeper(update, MagicMock())

    @pytest.mark.asyncio
    async def test_allows_authorized_user(self):
        update = _fake_update(AUTHORIZED_ID)
        # Must NOT raise.
        await _gatekeeper(update, MagicMock())


# ---------------------------------------------------------------------------
# Crew shape — /check must never trigger a transaction
# ---------------------------------------------------------------------------


class TestAuditOnlyCrewShape:
    def test_audit_only_has_no_executor_agent(self):
        crew = build_crew("0x0000000000000000000000000000000000000001", audit_only=True)
        roles = [a.role for a in crew.agents]
        assert "Secure Transaction Executor" not in roles, (
            "/check pipeline accidentally includes the Transaction Executor — "
            "this would let /check trigger on-chain side effects."
        )
        assert len(crew.tasks) == 2

    def test_full_crew_still_has_executor(self):
        # Regression: refactoring crew.py must not accidentally drop the
        # executor from the default pipeline.
        crew = build_crew("0x0000000000000000000000000000000000000001")
        roles = [a.role for a in crew.agents]
        assert "Secure Transaction Executor" in roles
        assert len(crew.tasks) == 3


# ---------------------------------------------------------------------------
# build_application — refuse to boot without secrets
# ---------------------------------------------------------------------------


class TestBuildApplicationRefusesInsecureBoot:
    def test_refuses_without_bot_token(self, monkeypatch):
        from web3_crew.config import settings as live_settings

        monkeypatch.setattr(live_settings, "telegram_bot_token", "")
        with pytest.raises(SystemExit, match="TELEGRAM_BOT_TOKEN"):
            build_application()

    def test_refuses_with_authorized_user_id_zero(self, monkeypatch):
        from web3_crew.config import settings as live_settings

        monkeypatch.setattr(live_settings, "telegram_bot_token", "test-bot-token")
        monkeypatch.setattr(live_settings, "authorized_user_id", 0)
        with pytest.raises(SystemExit, match="AUTHORIZED_USER_ID"):
            build_application()


# ---------------------------------------------------------------------------
# Address validation
# ---------------------------------------------------------------------------


class TestAddressValidation:
    @pytest.mark.parametrize(
        "raw",
        [
            "0x0000000000000000000000000000000000000001",
            "0xAaBbCcDdEeFf0011223344556677889900aaBBcc",
            "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        ],
    )
    def test_accepts_valid_address(self, raw):
        assert _ADDRESS_RE.match(raw)
        assert _extract_address([raw]) == raw

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # empty
            "not-an-address",  # garbage
            "0x123",  # too short
            "0xZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ",  # non-hex
            "0000000000000000000000000000000000000001",  # missing 0x prefix
            "0x0000000000000000000000000000000000000001 extra",  # trailing
        ],
    )
    def test_rejects_invalid_address(self, raw):
        assert _extract_address([raw]) is None

    def test_no_args_rejected(self):
        assert _extract_address([]) is None


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestReportFormatting:
    def test_pretty_prints_json(self):
        payload = json.dumps({"risk_score": 12, "risk_label": "safe"})
        out = _format_report(payload)
        assert out.startswith("<pre>")
        assert out.endswith("</pre>")
        # Pretty-printed JSON has a newline + 2-space indent. The body is
        # HTML-escaped before being sent, so quotes become &quot;.
        assert "\n  &quot;risk_score&quot;: 12" in out

    def test_escapes_html_in_payload(self):
        # A malicious auditor output must not break the Telegram HTML parser.
        out = _format_report("<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_falls_back_to_raw_text_for_non_json(self):
        out = _format_report("plain text report")
        assert "plain text report" in out

    def test_truncates_oversized_payload(self):
        big = "x" * 10_000
        out = _format_report(big)
        # Must fit within Telegram's 4096-char limit (with breathing room).
        assert len(out) < 4096
        assert "(truncated)" in out


# ---------------------------------------------------------------------------
# Wiring: gatekeeper is registered ahead of command handlers
# ---------------------------------------------------------------------------


class TestApplicationWiring:
    def test_gatekeeper_runs_before_command_handlers(self):
        app = build_application()
        # Group -1 must be present and must contain exactly one handler that is
        # the gatekeeper. Command handlers must live in group 0+.
        assert -1 in app.handlers
        assert any(getattr(h, "callback", None) is _gatekeeper for h in app.handlers[-1])
        commands_group = app.handlers.get(0, [])
        # Three commands: /start, /check, /mint.
        command_names = {
            cmd
            for h in commands_group
            for cmd in getattr(h, "commands", []) or []
        }
        assert {"start", "check", "mint"}.issubset(command_names)


# ---------------------------------------------------------------------------
# Sanity: AsyncMock works as expected (used elsewhere in the test file)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_asyncmock_smoke():
    m = AsyncMock()
    await m("ok")
    m.assert_awaited_once_with("ok")
