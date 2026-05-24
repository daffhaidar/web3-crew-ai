"""Telegram bridge for the Web3 Crew AI system.

Exposes the multi-agent pipeline via a natural language interface:

* /start — greeting + status check (tetap dipertahankan untuk inisialisasi)
* [Natural Text] — Secara otomatis merouting input user ke fungsi yang tepat:
  - Jika ada kata "mint"/"hajar" + contract address -> Eksekusi MINT pipeline.
  - Jika ada kata "cek"/"check"/"audit" + contract address -> Eksekusi AUDIT pipeline.
  - Jika tidak ada address -> Masuk ke mode SUPERAGENT (Chat biasa).

OPSEC
-----
The bot enforces a single authorized Telegram user ID via _gatekeeper.
Unauthorized senders are ignored completely with no reply.

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
    MessageHandler,
    TypeHandler,
    filters,
)

from web3_crew.config import settings
from web3_crew.context_manager import ContextManager
from web3_crew.crew import build_chat_crew, build_crew

logger = logging.getLogger(__name__)

# Regex untuk mendeteksi EVM address di dalam kalimat natural.
_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE: Final[re.Pattern[str]] = re.compile(r"0x[a-fA-F0-9]{64}")

_TELEGRAM_MAX_BODY: Final[int] = 3900
_TELEGRAM_PLAIN_MAX: Final[int] = 4000


# ---------------------------------------------------------------------------
# Gatekeeper
# ---------------------------------------------------------------------------

async def _gatekeeper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Drop every update from a non-authorized Telegram user."""
    user = update.effective_user
    if user is None or user.id != settings.authorized_user_id:
        sender_id = user.id if user else "anonymous"
        logger.warning("Dropping update from unauthorized sender id=%s", sender_id)
        raise ApplicationHandlerStop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_address_from_text(text: str) -> str | None:
    """Scan the entire text for an EVM address and return it if found."""
    match = _ADDRESS_RE.search(text)
    return match.group(0) if match else None

def _format_report(payload: str) -> str:
    """Format audit report dari JSON mentah menjadi tampilan Telegram yang estetik."""
    text = payload.strip()
    try:
        parsed = json.loads(text)

        # Mint success path: surface the post-tx metadata block.
        # metadata_summary is already Telegram-safe HTML produced by
        # post_tx_metadata.fetch_post_tx_metadata; we just stitch it
        # on top of the standard tx-status header.
        if (
            isinstance(parsed, dict)
            and parsed.get("status") == "success"
            and parsed.get("tx_hash")
        ):
            tx_hash = str(parsed.get("tx_hash"))
            explorer = parsed.get("explorer_url") or ""
            action = str(parsed.get("action") or "tx")
            meta = parsed.get("metadata_summary") or ""
            msg = "\U0001f7e2 <b>TX SUCCESS</b>\n"
            msg += "\u2501" * 20 + "\n"
            msg += f"<b>Action:</b> <code>{html.escape(action)}</code>\n"
            msg += f"<b>TxHash:</b> <code>{html.escape(tx_hash)}</code>\n"
            if explorer:
                msg += f'<a href="{html.escape(explorer)}">View on explorer</a>\n'
            if meta:
                # ``metadata_summary`` is intentionally pre-formatted HTML
                # (links + bold + code) from post_tx_metadata. Inserting
                # raw would defeat the purpose of building it there.
                msg += "\n" + meta + "\n"
            return msg

        # Ekstrak data menyesuaikan struktur JSON asli dari CrewAI lu
        if isinstance(parsed, dict) and ("risk_score" in parsed or "risk_label" in parsed):
            score = parsed.get("risk_score", "N/A")
            # Ambil "risk_label", kalau kaga ada baru cari "status", kalau kaga ada juga baru "UNKNOWN"
            status = str(parsed.get("risk_label", parsed.get("status", "UNKNOWN"))).upper()
            findings = parsed.get("detailed_findings", parsed.get("findings", []))
            recommendation = parsed.get("recommendation", "")

            # Tentukan emoji
            icon = "🟢" if status == "SAFE" or (isinstance(score, int) and score < 50) else "🔴"

            msg = f"{icon} <b>WEB3 CREW AUDIT REPORT</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"<b>Status:</b> <code>{html.escape(status)}</code>\n"
            msg += f"<b>Risk Score:</b> <code>{html.escape(str(score))}</code>\n\n"

            if findings:
                msg += "<b>🚨 Findings:</b>\n"
                if isinstance(findings, list):
                    for finding in findings:
                        msg += f"• <i>{html.escape(str(finding))}</i>\n"
                else:
                    msg += f"• <i>{html.escape(str(findings))}</i>\n"

            if recommendation:
                msg += f"\n<b>💡 Rekomendasi:</b>\n<i>{html.escape(str(recommendation))}</i>\n"

            return msg

        # Fallback kalau format JSON-nya aneh
        text = json.dumps(parsed, indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        pass  # Kalau bukan JSON, biarin jadi raw text

    # Clamp limit Telegram
    if len(text) > _TELEGRAM_MAX_BODY:
        text = text[:_TELEGRAM_MAX_BODY] + "\n…(truncated)"

    return f"<pre>{html.escape(text)}</pre>"

def _format_chat_reply(payload: str) -> str:
    """Format plain text balasan chat dengan menerjemahkan Markdown ke HTML Telegram."""
    text = (payload or "").strip()

    # 1. POTONG DULUAN di awal (sebelum ada tag HTML yang terbentuk)
    # Dikurangi 20 karakter buat ngasih ruang buat tulisan "\n…(truncated)"
    limit = _TELEGRAM_PLAIN_MAX - 20
    if len(text) > limit:
        text = text[:limit] + "\n…(truncated)"

    # 2. Pre-processing: Ubah <br> jadi Enter betulan
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'^\|?[\s\-:]+\|[\s\-:\|]+\|?$', '', text, flags=re.MULTILINE)

    # 3. Escape karakter berbahaya (<, >)
    text = html.escape(text)

    # 4. Terjemahkan sintaks Markdown ke tag HTML Telegram
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'(?<!\*)\*([^\*]+)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    return text

async def _run_with_heartbeat(update: Update, context: ContextTypes.DEFAULT_TYPE, *, crew) -> str:
    chat_id = update.effective_chat.id  # type: ignore[union-attr]

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
        try:
            await heartbeat
        except (asyncio.CancelledError, Exception):
            pass

    return str(result)


# ---------------------------------------------------------------------------
# Command & Message Handlers
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
        f"• Max risk: <code>{settings.max_risk_score}</code>\n\n"
        "<b>Cara Pakai</b>\n"
        "Tinggal ngobrol biasa aja. Contoh:\n"
        "• <i>'Tolong cek ini 0x...'</i> (Otomatis Audit)\n"
        "• <i>'Hajar mint contract ini 0x...'</i> (Otomatis Mint)\n"
        "• <i>'Coy, jelasin cara bypass gas war'</i> (Otomatis Chat)"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)  # type: ignore[union-attr]


async def natural_language_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Intelligent router yang menggantikan slash commands.
    Membaca input natural dari user dan memicu pipeline yang tepat.
    """
    user_input = update.message.text.strip()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]

    # Get augmented input with conversational history
    augmented_input = ContextManager.get_augmented_input(
        context.user_data,
        user_input,
        user_id
    )

    augmented_input_lower = augmented_input.lower()

    # Deteksi address di dalam pesan (using augmented input)
    address = _extract_address_from_text(augmented_input)

    # 1. ROUTING: MINT PIPELINE
    if address and any(keyword in augmented_input_lower for keyword in ["mint", "hajar", "gas", "buy"]):
        await update.message.reply_text(
            f"Eksekusi MINT pipeline untuk <code>{html.escape(address)}</code>…\nExecutor standby menunggu hasil audit.",
            parse_mode=ParseMode.HTML,
        )
        try:
            crew = build_crew(token_address=address, action="mint", audit_only=False)
            result = await _run_with_heartbeat(update, context, crew=crew)
            tx_hash_match = _TX_HASH_RE.search(result)
            if tx_hash_match:
                tx_hash = tx_hash_match.group(0)
                bot_reply = f"<b>TxHash</b>: <code>{tx_hash}</code>\n\n{_format_report(result)}"
                await update.message.reply_text(bot_reply, parse_mode=ParseMode.HTML)
            else:
                bot_reply = _format_report(result)
                await update.message.reply_text(bot_reply, parse_mode=ParseMode.HTML)

            # Store exchange with original user_input (not augmented)
            ContextManager.store_exchange(
                context.user_data,
                user_input,
                bot_reply,
                user_id
            )
        except Exception:
            logger.exception("Mint pipeline failed for %s", address)
            await update.message.reply_text("Mint pipeline gagal. Cek log server.")
        return

    # 2. ROUTING: AUDIT PIPELINE
    if address and any(keyword in augmented_input_lower for keyword in ["cek", "check", "audit", "liat", "aman"]):
        await update.message.reply_text(
            f"Scanning audit untuk <code>{html.escape(address)}</code>… (30-90s).",
            parse_mode=ParseMode.HTML,
        )
        try:
            crew = build_crew(token_address=address, audit_only=True)
            result = await _run_with_heartbeat(update, context, crew=crew)
            bot_reply = _format_report(result)
            await update.message.reply_text(bot_reply, parse_mode=ParseMode.HTML)

            # Store exchange with original user_input (not augmented)
            ContextManager.store_exchange(
                context.user_data,
                user_input,
                bot_reply,
                user_id
            )
        except Exception:
            logger.exception("Audit pipeline failed for %s", address)
            await update.message.reply_text("Audit pipeline gagal. Cek log server.")
        return

    # 3. ROUTING: SUPERAGENT CHAT (Fallback jika tidak ada instruksi teknis di atas)
    await update.message.reply_text("SUPERAGENT processing… (10-30s)")
    try:
        crew = build_chat_crew(augmented_input)
        result = await _run_with_heartbeat(update, context, crew=crew)
        bot_reply = _format_chat_reply(result)
        await update.message.reply_text(bot_reply, parse_mode=ParseMode.HTML)

        # Store exchange with original user_input (not augmented)
        ContextManager.store_exchange(
            context.user_data,
            user_input,
            bot_reply,
            user_id
        )
    except Exception:
        logger.exception("Chat pipeline failed")
        await update.message.reply_text("Chat pipeline gagal. Cek log server.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_application() -> Application:
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set.")
    if settings.authorized_user_id == 0:
        raise SystemExit("AUTHORIZED_USER_ID is not set.")

    app = Application.builder().token(settings.telegram_bot_token).build()

    # OPSEC Gatekeeper
    app.add_handler(TypeHandler(Update, _gatekeeper), group=-1)

    # Command Handler murni cuma buat /start
    app.add_handler(CommandHandler("start", start_command))

    # Message Handler menangkap semua teks biasa dan memasukkannya ke router kepintaran buatan lu
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, natural_language_router))

    return app


def main() -> None:
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
