"""Telegram bridge for the Web3 Crew AI system.

Exposes the multi-agent pipeline as three strict commands:

* ``/start``                       — greeting + status check
* ``/check  <contract_address>``   — Data Gatherer → Auditor, returns the
                                     auditor's JSON risk report (NEVER touches
                                     the Transaction Executor)
* ``/mint   <contract_address>``   — full pipeline; if audit passes, the
                                     Executor mints and the TxHash is returned

OPSEC
-----
The bot enforces a single authorized Telegram user ID via
:func:`_gatekeeper`, a :class:`TypeHandler` registered at group ``-1``. Every
update whose ``effective_user.id`` does not exactly match
``settings.authorized_user_id`` triggers
:class:`telegram.ext.ApplicationHandlerStop`, which terminates dispatch before
any command handler is reached. This means:

* No reply, no acknowledgement — the unauthorized sender gets silence.
* No command parsing, no LLM/RPC/wallet code paths.
* The only side effect is one ``WARNING`` log line containing the attacker's
  numeric ID (never their message payload).

Run with::

    uv run python -m web3_crew.telegram_bot
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from typing import Final

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    TypeHandler,
)

from web3_crew.config import settings
from web3_crew.crew import build_crew

logger = logging.getLogger(__name__)

# EIP-55 / generic EVM address regex. Length is enforced; case is permissive
# (we don't validate checksum because the auditor handles non-checksummed input).
_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(r"^0x[a-fA-F0-9]{40}$")

# 32-byte transaction hash, used to surface the TxHash to the user verbatim.
_TX_HASH_RE: Final[re.Pattern[str]] = re.compile(r"0x[a-fA-F0-9]{64}")

# Telegram caps message bodies at 4096 characters. We reserve ~100 for the
# surrounding ``<pre>`` tags and headers.
_TELEGRAM_MAX_BODY: Final[int] = 3900


# ---------------------------------------------------------------------------
# Gatekeeper
# ---------------------------------------------------------------------------


async def _gatekeeper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Drop every update from a non-authorized Telegram user.

    Registered as a :class:`TypeHandler` at group ``-1`` so it runs before any
    command handler. When the sender's ID does not match
    :pyattr:`Settings.authorized_user_id`, we raise
    :class:`ApplicationHandlerStop`, which makes ``python-telegram-bot`` skip
    the rest of the handler chain for this update entirely.
    """
    user = update.effective_user
    if user is None or user.id != settings.authorized_user_id:
        sender_id = user.id if user else "anonymous"
        logger.warning("Dropping update from unauthorized sender id=%s", sender_id)
        raise ApplicationHandlerStop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_address(args: list[str]) -> str | None:
    """Return the address argument if present and well-formed, else ``None``."""
    if not args:
        return None
    candidate = args[0].strip()
    return candidate if _ADDRESS_RE.match(candidate) else None


def _format_report(payload: str) -> str:
    """Return an HTML-safe ``<pre>`` block containing the audit report.

    If ``payload`` parses as JSON we pretty-print it (2-space indent); otherwise
    we send it verbatim. Either way the content is HTML-escaped and clamped to
    Telegram's per-message limit.
    """
    text = payload.strip()
    try:
        parsed = json.loads(text)
        text = json.dumps(parsed, indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        pass  # Send as raw text — formatting it was best-effort.

    if len(text) > _TELEGRAM_MAX_BODY:
        text = text[:_TELEGRAM_MAX_BODY] + "\n…(truncated)"

    return f"<pre>{html.escape(text)}</pre>"


async def _run_crew_with_heartbeat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    token_address: str,
    audit_only: bool,
    action: str = "mint",
) -> str:
    """Run a CrewAI pipeline in a worker thread while keeping the chat alive.

    CrewAI's ``kickoff()`` is synchronous and can take 30-120 seconds. We run
    it on a thread (``asyncio.to_thread``) so the bot's event loop stays free,
    and we fire a recurring ``ChatAction.TYPING`` so Telegram shows the
    'typing…' indicator and doesn't time the conversation out.
    """
    chat_id = update.effective_chat.id  # type: ignore[union-attr]
    crew = build_crew(token_address=token_address, action=action, audit_only=audit_only)

    async def _heartbeat() -> None:
        try:
            while True:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            return

    heartbeat = asyncio.create_task(_heartbeat())
    try:
        result = await asyncio.to_thread(crew.kickoff)
    finally:
        heartbeat.cancel()
        # Suppress the cancellation so it doesn't leak into the caller.
        try:
            await heartbeat
        except (asyncio.CancelledError, Exception):
            pass

    return str(result)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet the authorized user and report bot status."""
    user = update.effective_user
    name = html.escape(user.first_name) if user and user.first_name else "boss"
    msg = (
        f"Halo <b>{name}</b>. Web3 Crew AI bot online.\n\n"
        f"<b>Status</b>\n"
        f"• LLM: <code>{html.escape(settings.llm_model)}</code>\n"
        f"• Chain ID: <code>{settings.chain_id}</code>\n"
        f"• Max risk score: <code>{settings.max_risk_score}</code>\n"
        f"• Authorized user: <code>{settings.authorized_user_id}</code>\n\n"
        "<b>Commands</b>\n"
        "• <code>/check &lt;address&gt;</code> — audit only (no transaction)\n"
        "• <code>/mint &lt;address&gt;</code> — audit + mint if safe"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)  # type: ignore[union-attr]


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run the audit-only pipeline and return the JSON risk report."""
    address = _extract_address(context.args or [])
    if address is None:
        await update.message.reply_text(  # type: ignore[union-attr]
            "Usage: <code>/check 0x...</code> (40 hex chars after 0x)",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(  # type: ignore[union-attr]
        f"Auditing <code>{html.escape(address)}</code>… this can take 30-90s.",
        parse_mode=ParseMode.HTML,
    )

    try:
        result = await _run_crew_with_heartbeat(
            update, context, token_address=address, audit_only=True
        )
    except Exception:
        logger.exception("Audit pipeline failed for %s", address)
        await update.message.reply_text(  # type: ignore[union-attr]
            "Audit pipeline failed. Check the bot logs for details.",
        )
        return

    await update.message.reply_text(  # type: ignore[union-attr]
        _format_report(result), parse_mode=ParseMode.HTML
    )


async def mint_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run the full pipeline and (if audit passes) execute a mint."""
    address = _extract_address(context.args or [])
    if address is None:
        await update.message.reply_text(  # type: ignore[union-attr]
            "Usage: <code>/mint 0x...</code> (40 hex chars after 0x)",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(  # type: ignore[union-attr]
        f"Running full pipeline on <code>{html.escape(address)}</code>… "
        "the executor will refuse if the audit fails.",
        parse_mode=ParseMode.HTML,
    )

    try:
        result = await _run_crew_with_heartbeat(
            update,
            context,
            token_address=address,
            audit_only=False,
            action="mint",
        )
    except Exception:
        logger.exception("Mint pipeline failed for %s", address)
        await update.message.reply_text(  # type: ignore[union-attr]
            "Mint pipeline failed. Check the bot logs for details.",
        )
        return

    tx_hash_match = _TX_HASH_RE.search(result)
    if tx_hash_match:
        tx_hash = tx_hash_match.group(0)
        await update.message.reply_text(  # type: ignore[union-attr]
            f"<b>TxHash</b>: <code>{tx_hash}</code>\n\n{_format_report(result)}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(  # type: ignore[union-attr]
            _format_report(result), parse_mode=ParseMode.HTML
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_application() -> Application:
    """Construct the configured :class:`telegram.ext.Application`.

    Refuses to build the application when either ``TELEGRAM_BOT_TOKEN`` or
    ``AUTHORIZED_USER_ID`` is missing — better to fail loudly at startup than
    boot a bot with no auth wall.
    """
    if not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Get one from @BotFather and add it to .env."
        )
    if settings.authorized_user_id == 0:
        raise SystemExit(
            "AUTHORIZED_USER_ID is not set (or is 0). Message @userinfobot on "
            "Telegram to find yours and add it to .env. Refusing to start an "
            "unauthenticated bot."
        )

    app = Application.builder().token(settings.telegram_bot_token).build()

    # Gatekeeper runs FIRST. ApplicationHandlerStop from group -1 short-circuits
    # the entire handler chain, so unauthorized updates never reach group 0.
    app.add_handler(TypeHandler(Update, _gatekeeper), group=-1)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("mint", mint_command))

    return app


def main() -> None:  # pragma: no cover — exercised only by the actual bot run.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = build_application()
    logger.info(
        "Starting Telegram bot — authorized user id=%s, model=%s",
        settings.authorized_user_id,
        settings.llm_model,
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
