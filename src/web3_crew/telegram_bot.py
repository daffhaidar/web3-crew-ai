"""Telegram bridge for the Web3 Crew AI system.

Exposes the multi-agent pipeline via a natural language interface:

* /start - greeting + status check (tetap dipertahankan untuk inisialisasi)
* [Natural Text] - Secara otomatis merouting input user ke fungsi yang tepat:
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
import sqlite3
import tempfile
from pathlib import Path
from typing import Final

from telegram import Update
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
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
from web3 import Web3

from web3_crew.config import settings
from web3_crew.context_manager import ContextManager
from web3_crew.crew import build_chat_crew, build_crew
from web3_crew.memory.skill_ingestor import SkillManager
from web3_crew.tools.eligibility import check_eligibility
from web3_crew.tools.mint_phase import probe_mint_phase
from web3_crew.tools.scheduled_executor import poll_loop
from web3_crew.tools.scheduled_mint import (
    ScheduledJob,
    ScheduledMintQueue,
    parse_schedule_time,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLite User Logging
# ---------------------------------------------------------------------------
_DB_PATH: Final[Path] = Path(__file__).resolve().parent.parent.parent / "bot_users.db"


def _init_user_db() -> None:
    """Create the user-log table if it does not already exist."""
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_users (
                chat_id    INTEGER PRIMARY KEY,
                username   TEXT,
                first_seen TEXT DEFAULT (datetime('now')),
                last_seen  TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _log_user_chat_id(chat_id: int, username: str | None = None) -> None:
    """Upsert a user's chat ID so we track first and last interaction."""
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO bot_users (chat_id, username, first_seen, last_seen)
            VALUES (?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(chat_id) DO UPDATE SET
                username  = COALESCE(excluded.username, bot_users.username),
                last_seen = datetime('now')
            """,
            (chat_id, username),
        )
        conn.commit()
    except sqlite3.Error:
        logger.exception("Failed to log chat_id=%s to SQLite", chat_id)
    finally:
        conn.close()


# Run once at import time so the table is ready before any handler fires.
_init_user_db()

# Inisialisasi Skill Manager (Dynamic Ingestion)
_skill_manager = SkillManager()

# Singleton queue for scheduled mints; created lazily so tests can override
# the queue path via ScheduledMintQueue(queue_path=...) before this is
# accessed.
_scheduled_queue: ScheduledMintQueue | None = None


def _get_scheduled_queue() -> ScheduledMintQueue:
    global _scheduled_queue
    if _scheduled_queue is None:
        _scheduled_queue = ScheduledMintQueue()
    return _scheduled_queue


# Regex untuk mendeteksi EVM address di dalam kalimat natural.
_ADDRESS_RE: Final[re.Pattern[str]] = re.compile(r"0x[a-fA-F0-9]{40}")
_TX_HASH_RE: Final[re.Pattern[str]] = re.compile(r"0x[a-fA-F0-9]{64}")

# Schedule directive in a natural-language mint message. Matches:
#   ' @06:00 UTC'  ' @06:00'  ' @1715000000'  ' @+30m'  ' @+90s'  ' @+2h'
_SCHEDULE_RE: Final[re.Pattern[str]] = re.compile(
    r"@\s*(\+?\d+[smh]?|\d{1,2}:\d{2}(?:\s*UTC)?)",
    flags=re.IGNORECASE,
)

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

    # Log authorized user interaction to SQLite
    _log_user_chat_id(
        chat_id=user.id,
        username=user.username or user.first_name,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_address_from_text(text: str) -> str | None:
    """Scan the entire text for an EVM address and return it if found."""
    match = _ADDRESS_RE.search(text)
    return match.group(0) if match else None

def _format_report(payload: str) -> str:
    """Format audit report dari JSON mentah menjadi tampilan Telegram."""
    text = payload.strip()
    
    # Trik variabel agar tidak merusak tampilan markdown AI
    simbol_kutip = "`" * 3
    
    # KUPAS BUNGKUS MARKDOWN: Hapus bungkus json di awal dan akhir
    text = re.sub(r'^' + simbol_kutip + r'(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*' + simbol_kutip + r'$', '', text)
    
    try:
        parsed = json.loads(text)

        if (
            isinstance(parsed, dict)
            and parsed.get("status") == "success"
            and parsed.get("tx_hash")
        ):
            tx_hash = str(parsed.get("tx_hash"))
            explorer = parsed.get("explorer_url") or ""
            action = str(parsed.get("action") or "tx")
            meta = parsed.get("metadata_summary") or ""
            msg = "[+] <b>TX SUCCESS</b>\n"
            msg += "=" * 20 + "\n"
            msg += f"<b>Action:</b> <code>{html.escape(action)}</code>\n"
            msg += f"<b>TxHash:</b> <code>{html.escape(tx_hash)}</code>\n"
            if explorer:
                msg += f'<a href="{html.escape(explorer)}">View on explorer</a>\n'
            if meta:
                msg += "\n" + meta + "\n"
            return msg

        if isinstance(parsed, dict) and ("risk_score" in parsed or "risk_label" in parsed):
            score = parsed.get("risk_score", "N/A")
            status = str(parsed.get("risk_label", parsed.get("status", "UNKNOWN"))).upper()
            findings = parsed.get("detailed_findings", parsed.get("findings", []))
            recommendation = parsed.get("recommendation", "")

            icon = "[SAFE]" if status == "SAFE" or (isinstance(score, int) and score < 50) else "[DANGER]"

            msg = f"{icon} <b>WEB3 CREW AUDIT REPORT</b>\n"
            msg += "====================\n"
            msg += f"<b>Status:</b> <code>{html.escape(status)}</code>\n"
            msg += f"<b>Risk Score:</b> <code>{html.escape(str(score))}</code>\n\n"

            if findings:
                msg += "<b>[*] Findings:</b>\n"
                if isinstance(findings, list):
                    for finding in findings:
                        msg += f"- <i>{html.escape(str(finding))}</i>\n"
                else:
                    msg += f"- <i>{html.escape(str(findings))}</i>\n"

            if recommendation:
                msg += f"\n<b>[!] Rekomendasi:</b>\n<i>{html.escape(str(recommendation))}</i>\n"

            return msg

        text = json.dumps(parsed, indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        pass

    if len(text) > _TELEGRAM_MAX_BODY:
        text = text[:_TELEGRAM_MAX_BODY] + "\n...(truncated)"

    return f"<pre>{html.escape(text)}</pre>"

def _format_chat_reply(payload: str) -> str:
    """Format plain text balasan chat dengan menerjemahkan Markdown ke HTML Telegram."""
    text = (payload or "").strip()

    limit = _TELEGRAM_PLAIN_MAX - 20
    if len(text) > limit:
        text = text[:limit] + "\n...(truncated)"

    # 1. Escape karakter HTML bawaan biar kaga bentrok dengan Telegram parser
    text = html.escape(text)

    # 2. Parse Code Blocks (Triple Backticks) DULUAN
    # Menangkap ```javascript\nkode\n``` atau ```kode``` dan mengubahnya jadi <pre>
    text = re.sub(r'```[a-zA-Z0-9]*\n?(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)

    # 3. Parse Inline Code (Single Backtick)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # 4. Parse Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)

    return text

async def _run_with_heartbeat(update: Update, context: ContextTypes.DEFAULT_TYPE, *, crew) -> str:
    chat_id = update.effective_chat.id

    async def _heartbeat() -> None:
        try:
            while True:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            return

    heartbeat = asyncio.create_task(_heartbeat())
    
    try:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Coba eksekusi Crew
                result = await asyncio.to_thread(crew.kickoff)
                break  # Kalau sukses, keluar dari loop
            except Exception as e:
                error_msg = str(e)
                # Deteksi error 503 atau Service Unavailable
                if "503" in error_msg or "ServiceUnavailable" in error_msg:
                    if attempt < max_retries - 1:
                        await update.message.reply_text(
                            f"[!] Otak AI sibuk (Error 503). Retrying otomatis {attempt + 1}/{max_retries} dalam 5 detik..."
                        )
                        await asyncio.sleep(5)
                        continue
                # Kalau bukan 503 atau jatah retry abis, lempar errornya
                raise e
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
        f"- LLM: <code>{html.escape(settings.llm_model)}</code>\n"
        f"- Chain ID: <code>{settings.chain_id}</code>\n"
        f"- Max risk: <code>{settings.max_risk_score}</code>\n\n"
        "<b>Cara Pakai</b>\n"
        "Tinggal ngobrol biasa aja. Contoh:\n"
        "- <i>'Tolong cek ini 0x...'</i> (Otomatis Audit)\n"
        "- <i>'Hajar mint contract ini 0x...'</i> (Otomatis Mint)\n"
        "- <i>'Coy, jelasin cara bypass gas war'</i> (Otomatis Chat)\n"
        "- <i>Kirim file ZIP berisi file .md untuk ingest skill baru.</i>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def handle_skill_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    msg = await update.message.reply_text("[*] Mengunduh dan memvalidasi file ZIP...", parse_mode=ParseMode.HTML)
    
    try:
        file = await context.bot.get_file(document.file_id)
        # Jangan gunakan context manager 'with' agar file tidak otomatis terhapus saat error
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        tmp_path = Path(tmp.name)
        tmp.close()
        
        await file.download_to_drive(custom_path=tmp_path)
        
        try:
            count = _skill_manager.process_zip(tmp_path)
            await msg.edit_text(f"[+] Skill di-install. Total {count} file diserap.")
            tmp_path.unlink(missing_ok=True)
            
        except ValueError:
            # File berbahaya terdeteksi. Munculkan tombol Bypass.
            context.user_data['pending_zip'] = str(tmp_path)
            
            keyboard = [
                [
                    InlineKeyboardButton("Gas, Bypass!", callback_data="bypass_zip_yes"),
                    InlineKeyboardButton("Batal", callback_data="bypass_zip_no")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await msg.edit_text(
                "?? <b>PERINGATAN SISTEM</b>\n"
                "File berbahaya (.py, .sh, dll) terdeteksi di dalam ZIP. Ini berbahaya? Mau lanjutin?",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            
        except Exception as e:
            await msg.edit_text(f"[!] File ZIP rusak atau gagal diekstrak: {e}")
            tmp_path.unlink(missing_ok=True)
            
    except Exception as e:
        logger.exception("Failed to download ZIP")
        await msg.edit_text("[-] Gagal mengunduh file.")
        
        
async def handle_zip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    tmp_path_str = context.user_data.get('pending_zip')
    if not tmp_path_str:
        await query.edit_message_text("[-] Sesi upload kadaluarsa.")
        return
        
    tmp_path = Path(tmp_path_str)
    
    if query.data == "bypass_zip_yes":
        await query.edit_message_text("[*] Memaksa eksekusi file...")
        try:
            # Panggil dengan force=True
            count = _skill_manager.process_zip(tmp_path, force=True)
            await query.edit_message_text(f"Yaudah oke gue eksekusi yaa.. DYOR oke. Total {count} file diserap.")
        except Exception as e:
            await query.edit_message_text(f"[!] Bypass gagal: {e}")
    else:
        await query.edit_message_text("[-] Eksekusi dibatalkan demi keamanan.")
        
    # Cleanup
    tmp_path.unlink(missing_ok=True)
    context.user_data.pop('pending_zip', None)
    
async def handle_mint_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani klik tombol konfirmasi MINT."""
    query = update.callback_query
    await query.answer()
    
    address = context.user_data.get('pending_mint_address')
    skill_context = context.user_data.get('pending_mint_skill', "")
    
    if not address:
        await query.edit_message_text("[-] Sesi konfirmasi kadaluarsa atau tidak valid.")
        return
        
    if query.data == "confirm_mint_yes":
        await query.edit_message_text(
            f"?? <b>Mengeksekusi transaksi on-chain untuk</b> <code>{html.escape(address)}</code>...", 
            parse_mode=ParseMode.HTML
        )
        try:
            # Eksekusi Penuh (Bypass Audit karena udah diaudit sebelumnya)
            crew = build_crew(
                token_address=address, 
                action="mint", 
                audit_only=False, 
                force_execution=True, 
                skill_context=skill_context
            )
            result = await _run_with_heartbeat(update, context, crew=crew)
            
            tx_hash_match = _TX_HASH_RE.search(result)
            if tx_hash_match:
                tx_hash = tx_hash_match.group(0)
                bot_reply = f"<b>TxHash</b>: <code>{tx_hash}</code>\n\n{_format_report(result)}"
            else:
                bot_reply = _format_report(result)
                
            await query.edit_message_text(bot_reply, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.exception("Mint execution failed")
            await query.edit_message_text(f"[-] Eksekusi gagal: {e}")
    else:
        await query.edit_message_text(f"[!] Eksekusi <b>dibatalkan</b> oleh operator. Dana aman.", parse_mode=ParseMode.HTML)
        
    # Bersihkan memori sesi
    context.user_data.pop('pending_mint_address', None)
    context.user_data.pop('pending_mint_skill', None)


async def _handle_phase_probe(
    update: Update, address: str, user_input: str
) -> None:
    """Read-only mint phase + eligibility probe. No tx, no wallet use."""
    try:
        w3 = Web3(Web3.HTTPProvider(settings.web3_rpc_url))
        user_addr_match = re.search(
            r"(?<!0x[a-fA-F0-9])0x[a-fA-F0-9]{40}",
            user_input.replace(address, "", 1),
        )
        user_addr = user_addr_match.group(0) if user_addr_match else None

        if user_addr:
            verdict = await asyncio.to_thread(
                check_eligibility, w3, address, user_addr, requested_qty=1
            )
            summary = verdict.summary()
            if verdict.phase_result is not None:
                summary += "\n\n" + verdict.phase_result.summary()
        else:
            phase = await asyncio.to_thread(probe_mint_phase, w3, address)
            summary = phase.summary()
        await update.message.reply_text(
            f"<pre>{html.escape(summary)}</pre>", parse_mode=ParseMode.HTML
        )
    except Exception:
        logger.exception("Phase probe failed for %s", address)
        await update.message.reply_text("Phase probe gagal. Cek log server.")


async def _handle_schedule_mint(
    update: Update,
    address: str,
    user_input: str,
    schedule_spec: str,
) -> None:
    """Parse 'mint N di 0x... @06:00 UTC' and enqueue."""
    target_ts = parse_schedule_time(schedule_spec)
    if target_ts is None:
        await update.message.reply_text(
            f"Format jadwal '{html.escape(schedule_spec)}' gak dikenal. "
            "Contoh valid: @06:00 UTC, @+30m, @+90s, @1715000000."
        )
        return

    # qty: look for "N kali", "N nft", "N qty" or first standalone integer 1-50
    qty = 1
    m = re.search(r"\b(\d{1,2})\s*(?:x|qty|kali|nft|piece|pcs)?\b", user_input.lower())
    if m:
        candidate = int(m.group(1))
        if 1 <= candidate <= 50:
            qty = candidate

    # function_name: default publicMint. Allow override via "via mint(uint256)" etc.
    fn_name = "publicMint"
    fn_match = re.search(r"\bvia\s+(\w+)\b", user_input.lower())
    if fn_match:
        fn_name = fn_match.group(1)

    # value_eth: look for "@0.0003 ETH" pattern (NOT the schedule @) or "value 0.001"
    value_wei = 0
    val_match = re.search(
        r"(?:value|harga|price)[\s:=]*(\d*\.?\d+)\s*eth",
        user_input.lower(),
    )
    if val_match:
        value_wei = int(float(val_match.group(1)) * 1e18) * qty

    queue = _get_scheduled_queue()
    job = await queue.enqueue(
        contract_address=address,
        qty=qty,
        scheduled_at=target_ts,
        value_wei=value_wei,
        function_name=fn_name,
        user_id=update.effective_user.id,
        chain_id=settings.chain_id,
    )
    delta = target_ts - int(__import__("time").time())
    delta_str = f"T-{delta}s" if delta < 60 else f"T-{delta // 60}m{delta % 60:02d}s"
    await update.message.reply_text(
        f"<b>Scheduled mint job</b> <code>{job.id[:8]}</code>\n"
        f"- contract: <code>{html.escape(address)}</code>\n"
        f"- qty: <code>{qty}</code>\n"
        f"- function: <code>{fn_name}</code>\n"
        f"- value: <code>{value_wei / 1e18:.6f} ETH</code> total\n"
        f"- fires at: <code>unix {target_ts}</code> ({delta_str})\n\n"
        f"<i>Cancel: /cancel {job.id[:8]}. List: /scheduled.</i>",
        parse_mode=ParseMode.HTML,
    )


async def scheduled_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all scheduled mint jobs."""
    queue = _get_scheduled_queue()
    jobs = await queue.list_all()
    if not jobs:
        await update.message.reply_text("No scheduled mint jobs.")
        return
    active = [j for j in jobs if not j.is_terminal]
    terminal = [j for j in jobs if j.is_terminal][-5:]  # last 5
    lines: list[str] = []
    if active:
        lines.append("<b>Active</b>")
        lines.extend(html.escape(j.summary_line()) for j in active)
    if terminal:
        lines.append("\n<b>Recent (last 5)</b>")
        lines.extend(html.escape(j.summary_line()) for j in terminal)
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel a scheduled job by id prefix: /cancel <id8>"""
    if not context.args:
        await update.message.reply_text("Usage: /cancel <job_id_prefix>")
        return
    queue = _get_scheduled_queue()
    target = await queue.cancel(context.args[0])
    if target is None:
        await update.message.reply_text(f"Job '{context.args[0]}' tidak ditemukan.")
        return
    if target.status == "cancelled":
        await update.message.reply_text(
            f"Cancelled job <code>{target.id[:8]}</code>.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"Job <code>{target.id[:8]}</code> sudah {target.status}, tidak bisa cancel.",
            parse_mode=ParseMode.HTML,
        )


async def _scheduled_notifier(job: ScheduledJob, emoji: str, msg: str) -> None:
    """Send DM to the authorized user when a scheduled job completes."""
    try:
        from telegram import Bot

        if not settings.telegram_bot_token or settings.authorized_user_id == 0:
            return
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(
            chat_id=settings.authorized_user_id,
            text=(
                f"<b>{emoji} Scheduled job {html.escape(job.id[:8])}</b>\n"
                f"contract: <code>{html.escape(job.contract_address)}</code>\n"
                f"qty: {job.qty}, fn: {html.escape(job.function_name)}\n"
                f"{html.escape(msg)}"
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("Failed to notify scheduled job %s", job.id[:8])


async def natural_language_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Intelligent router yang menggantikan slash commands.
    Membaca input natural dari user dan memicu pipeline yang tepat.
    """
    user_input = update.message.text.strip()
    user_id = update.effective_user.id

    augmented_input = ContextManager.get_augmented_input(
        context.user_data,
        user_input,
        user_id
    )

    # -------------------------------------------------------------
    # CONTEXT INJECTION
    # Per-command skill routing: identity files always load, and only the
    # m-skills relevant to the chosen pipeline get pulled in. See
    # SkillManager.COMMAND_SKILL_MAP for the prefix-to-command mapping.
    # -------------------------------------------------------------
    augmented_input_lower = user_input.lower()
    address = _extract_address_from_text(user_input)

    # 0. ROUTING: PHASE PROBE (read-only, no tx)
    _PHASE_KEYWORDS = (
        "phase", "fase", "eligible", "eligibility",
        "kapan buka", "kapan mulai", "info mint",
    )
    if address and any(kw in augmented_input_lower for kw in _PHASE_KEYWORDS):
        await _handle_phase_probe(update, address, user_input)
        return

    # 1a. ROUTING: SCHEDULED MINT (mint + address + @<time>)
    schedule_match = _SCHEDULE_RE.search(user_input)
    if (
        address
        and schedule_match
        and any(keyword in augmented_input_lower for keyword in ["mint", "hajar", "buy"])
    ):
        await _handle_schedule_mint(update, address, user_input, schedule_match.group(1))
        return

    # 1. ROUTING: MINT PIPELINE
    if address and any(keyword in augmented_input_lower for keyword in ["mint", "hajar", "gas", "buy"]):
        skill_context = _skill_manager.get_skill_context(command="mint")
        msg = await update.message.reply_text(
            f"[*] Mempersiapkan MINT pipeline untuk <code>{html.escape(address)}</code>...\nMelakukan audit pra-eksekusi...",
            parse_mode=ParseMode.HTML,
        )
        try:
            # Jalankan Audit Dulu
            crew = build_crew(token_address=address, audit_only=True, skill_context=skill_context)
            audit_result = await _run_with_heartbeat(update, context, crew=crew)
            audit_report = _format_report(audit_result)
            
            # Simpan state untuk eksekusi
            context.user_data['pending_mint_address'] = address
            context.user_data['pending_mint_skill'] = skill_context
            
            # Buat Tombol Rem Darurat
            keyboard = [
                [
                    InlineKeyboardButton("[!] TANDA TANGANI & GAS", callback_data="confirm_mint_yes"),
                    InlineKeyboardButton("[X] BATALKAN", callback_data="confirm_mint_no")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await msg.edit_text(
                f"{audit_report}\n\n[!] <b>OTORISASI EKSEKUSI</b>\nApakah lu yakin mau mengeksekusi transaksi untuk kontrak ini?",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            
            # Simpan log interaksi
            ContextManager.store_exchange(context.user_data, user_input, audit_report, user_id)
        except Exception:
            logger.exception("Mint pipeline audit failed for %s", address)
            await msg.edit_text("[-] Audit pra-eksekusi gagal. Cek log server.")
        return

    # 2. ROUTING: AUDIT PIPELINE
    if address and any(keyword in user_input.lower() for keyword in ["cek", "check", "audit", "liat", "aman"]):
        skill_context = _skill_manager.get_skill_context(command="check")
        await update.message.reply_text(
            f"Scanning audit untuk <code>{html.escape(address)}</code>... (30-90s).",
            parse_mode=ParseMode.HTML,
        )
        try:
            crew = build_crew(token_address=address, audit_only=True, skill_context=skill_context)
            result = await _run_with_heartbeat(update, context, crew=crew)
            bot_reply = _format_report(result)
            await update.message.reply_text(bot_reply, parse_mode=ParseMode.HTML)

            ContextManager.store_exchange(context.user_data, user_input, bot_reply, user_id)
        except Exception:
            logger.exception("Audit pipeline failed for %s", address)
            await update.message.reply_text("Audit pipeline gagal. Cek log server.")
        return

    # 3. ROUTING: SUPERAGENT CHAT
    skill_context = _skill_manager.get_skill_context(command="chat")
    await update.message.reply_text("SUPERAGENT processing... (10-30s)")
    try:
        crew = build_chat_crew(augmented_input, skill_context=skill_context)
        result = await _run_with_heartbeat(update, context, crew=crew)
        bot_reply = _format_chat_reply(result)
        await update.message.reply_text(bot_reply, parse_mode=ParseMode.HTML)

        ContextManager.store_exchange(context.user_data, user_input, bot_reply, user_id)
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

    app.add_handler(CommandHandler("start", start_command))

    # Handler ZIP Upload & Tombolnya (TARUH DI SINI)
    app.add_handler(MessageHandler(filters.Document.ZIP, handle_skill_upload))
    app.add_handler(CallbackQueryHandler(handle_zip_callback, pattern="^bypass_zip_"))
    app.add_handler(CallbackQueryHandler(handle_mint_callback, pattern="^confirm_mint_"))

    # Router NLP harus di bawah supaya kaga nabrak command lain
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, natural_language_router))

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = build_application()
    logger.info(
        "Starting Telegram bot - authorized user id=%s, model=%s",
        settings.authorized_user_id,
        settings.llm_model,
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
