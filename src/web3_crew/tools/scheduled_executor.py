"""Executor side of the scheduled mint queue.

Lives separately from the queue file (:mod:`scheduled_mint`) so the
queue stays a pure-data module that's easy to unit-test. This module
owns the side-effecting "actually broadcast a mint tx" path.

Hot wallet caveat
-----------------
The bot mints from the single hot wallet configured in
``settings.wallet_private_key``. It is **NOT** the user's browser
extension wallet -- this is the same hot wallet that backs the regular
/mint command. Operator-funded mints only. See HERMES.md for the
user-funds-only operating policy.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from web3_crew.tools.safe_transaction import SafeTransactionTool
from web3_crew.tools.scheduled_mint import ScheduledJob, ScheduledMintQueue

logger = logging.getLogger(__name__)

# Notifier signature: (job, status_emoji, message) -> awaitable
# When the bot starts, telegram_bot wires this to send a Telegram DM to
# the authorized user. Tests inject a no-op or list-collector.
Notifier = Callable[[ScheduledJob, str, str], Awaitable[None]]


async def _noop_notifier(job: ScheduledJob, emoji: str, msg: str) -> None:  # pragma: no cover
    return None


def build_mint_tx_request(job: ScheduledJob) -> str:
    """Build the JSON payload SafeTransactionTool expects."""
    payload: dict[str, Any] = {
        "action": "mint",
        "contract_address": job.contract_address,
        "function_name": job.function_name,
        # SafeTransactionTool's function_args is positional. publicMint() takes
        # zero args; mint(uint256) takes [qty]; safeMint(address, uint256)
        # takes [recipient, qty] (recipient is filled in by the tool from
        # wallet_private_key, so we still just pass [qty] here -- the tool's
        # generic-ABI path handles this).
        "function_args": [job.qty] if job.function_name != "publicMint" else [],
        "value_wei": job.value_wei,
        # Scheduled jobs are pre-decided by the user; skip the audit gate.
        "risk_score": 0,
    }
    return json.dumps(payload)


async def execute_job(
    job: ScheduledJob,
    queue: ScheduledMintQueue,
    *,
    tool: SafeTransactionTool | None = None,
    notifier: Notifier = _noop_notifier,
) -> ScheduledJob:
    """Run a single scheduled mint job.

    Updates the queue (done/failed) and notifies the user via ``notifier``.
    """
    tool = tool or SafeTransactionTool()
    tx_request = build_mint_tx_request(job)
    logger.info("Executing scheduled job %s (%s)", job.id[:8], job.contract_address)

    try:
        # SafeTransactionTool is synchronous (sends an HTTP RPC call). Push
        # it to a worker thread so we don't block the bot's event loop
        # during the receipt poll.
        result_str = await asyncio.to_thread(tool._run, tx_request)
    except Exception as exc:
        logger.exception("Scheduled job %s raised", job.id[:8])
        await queue.complete(job.id, status="failed", result=f"executor crash: {exc}")
        await notifier(job, "[FAIL]", f"crashed -- {exc}")
        return job

    # Parse the response. SafeTransactionTool returns JSON with a "status"
    # field: success | reverted | pending | rejected | error.
    try:
        parsed = json.loads(result_str)
        tx_status = parsed.get("status", "unknown")
    except json.JSONDecodeError:
        tx_status = "unknown"
        parsed = {"raw": result_str}

    if tx_status == "success":
        await queue.complete(job.id, status="done", result=result_str)
        await notifier(
            job,
            "[OK]",
            f"minted -- tx {parsed.get('tx_hash', '?')[:14]}...",
        )
    else:
        await queue.complete(job.id, status="failed", result=result_str)
        await notifier(
            job,
            "[FAIL]",
            f"{tx_status} -- {parsed.get('reason', 'see logs')}",
        )
    return job


async def poll_and_execute(
    queue: ScheduledMintQueue,
    *,
    tool: SafeTransactionTool | None = None,
    notifier: Notifier = _noop_notifier,
) -> list[ScheduledJob]:
    """One poll cycle: claim due jobs, execute each, return what ran."""
    due_jobs = await queue.claim_due()
    if not due_jobs:
        return []
    results: list[ScheduledJob] = []
    for job in due_jobs:
        result = await execute_job(job, queue, tool=tool, notifier=notifier)
        results.append(result)
    return results


async def poll_loop(
    queue: ScheduledMintQueue,
    *,
    poll_interval_seconds: float = 10.0,
    tool: SafeTransactionTool | None = None,
    notifier: Notifier = _noop_notifier,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Long-running loop. Cancel via ``stop_event`` or task.cancel()."""
    logger.info(
        "Scheduled mint poller starting (interval=%ss, queue=%s)",
        poll_interval_seconds,
        queue.queue_path,
    )
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            try:
                await poll_and_execute(queue, tool=tool, notifier=notifier)
            except Exception:  # pragma: no cover -- never let the loop die
                logger.exception("Scheduled mint poll cycle raised; continuing")
            await asyncio.sleep(poll_interval_seconds)
    except asyncio.CancelledError:
        logger.info("Scheduled mint poller cancelled")
        raise
