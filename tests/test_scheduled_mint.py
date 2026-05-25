"""Tests for the scheduled-mint queue + executor."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from web3_crew.tools.scheduled_executor import (
    build_mint_tx_request,
    execute_job,
    poll_and_execute,
)
from web3_crew.tools.scheduled_mint import (
    ScheduledJob,
    ScheduledMintQueue,
    parse_schedule_time,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_queue(tmp_path: Path) -> ScheduledMintQueue:
    return ScheduledMintQueue(
        queue_path=tmp_path / "queue.json",
        max_lateness_seconds=300,
    )


CONTRACT = "0x" + "ab" * 20


# ---------------------------------------------------------------------------
# Queue persistence + lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_persists_job(tmp_queue: ScheduledMintQueue) -> None:
    job = await tmp_queue.enqueue(
        contract_address=CONTRACT,
        qty=2,
        scheduled_at=int(time.time()) + 60,
    )
    assert job.id
    assert job.status == "scheduled"

    # Reload from disk via a new queue instance pointed at the same file.
    queue2 = ScheduledMintQueue(queue_path=tmp_queue.queue_path)
    loaded = await queue2.load()
    assert len(loaded) == 1
    assert loaded[0].id == job.id
    assert loaded[0].qty == 2


@pytest.mark.asyncio
async def test_claim_due_picks_up_only_past_jobs(
    tmp_queue: ScheduledMintQueue,
) -> None:
    past = await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) - 5
    )
    await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) + 600
    )
    claimed = await tmp_queue.claim_due()
    assert len(claimed) == 1
    assert claimed[0].id == past.id
    assert claimed[0].status == "executing"


@pytest.mark.asyncio
async def test_claim_due_skips_terminal_jobs(
    tmp_queue: ScheduledMintQueue,
) -> None:
    job = await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) - 5
    )
    # Claim once -> moves to executing
    claimed = await tmp_queue.claim_due()
    assert len(claimed) == 1
    # Mark done
    await tmp_queue.complete(job.id, status="done", result="{}")
    # Second claim must not re-pick this job
    claimed2 = await tmp_queue.claim_due()
    assert claimed2 == []


@pytest.mark.asyncio
async def test_expired_jobs_marked_when_too_late(
    tmp_queue: ScheduledMintQueue,
) -> None:
    # Job scheduled 1 hour ago, beyond max_lateness_seconds=300
    await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) - 3600
    )
    claimed = await tmp_queue.claim_due()
    assert claimed == []  # not claimed
    jobs = await tmp_queue.list_all()
    assert len(jobs) == 1
    assert jobs[0].status == "expired"
    assert "missed firing window" in (jobs[0].result or "")


@pytest.mark.asyncio
async def test_cancel_pending_job_marks_cancelled(
    tmp_queue: ScheduledMintQueue,
) -> None:
    job = await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) + 600
    )
    cancelled = await tmp_queue.cancel(job.id[:8])
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    # Cancelled jobs are not picked up.
    assert await tmp_queue.claim_due() == []


@pytest.mark.asyncio
async def test_cancel_unknown_job_returns_none(
    tmp_queue: ScheduledMintQueue,
) -> None:
    result = await tmp_queue.cancel("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_cancel_does_not_revert_terminal_job(
    tmp_queue: ScheduledMintQueue,
) -> None:
    job = await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) - 5
    )
    await tmp_queue.claim_due()
    await tmp_queue.complete(job.id, status="done", result="{}")
    # Cancelling a done job should leave its status as-is.
    result = await tmp_queue.cancel(job.id)
    assert result is not None
    assert result.status == "done"


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


def test_parse_schedule_time_relative_offsets() -> None:
    now = 1_700_000_000
    assert parse_schedule_time("+30s", now=now) == now + 30
    assert parse_schedule_time("+5m", now=now) == now + 300
    assert parse_schedule_time("+2h", now=now) == now + 7200


def test_parse_schedule_time_hhmm_today_or_tomorrow() -> None:
    # 2023-11-14 22:13:20 UTC
    now = 1_700_000_000
    # 22:14 UTC -> 1 minute later (today)
    assert parse_schedule_time("22:14", now=now) == 1_700_000_040
    # 22:13 UTC same minute -> tomorrow (schedule cannot be in the past)
    same_minute = parse_schedule_time("22:13", now=now)
    assert same_minute is not None
    assert same_minute - now > 86000  # ~tomorrow


def test_parse_schedule_time_absolute_unix() -> None:
    assert parse_schedule_time("1715000000") == 1_715_000_000


def test_parse_schedule_time_rejects_garbage() -> None:
    assert parse_schedule_time("tomorrow") is None
    assert parse_schedule_time("99:99") is None
    assert parse_schedule_time("") is None


def test_parse_schedule_time_accepts_utc_suffix() -> None:
    now = 1_700_000_000
    assert parse_schedule_time("22:14 UTC", now=now) == 1_700_000_040


# ---------------------------------------------------------------------------
# Executor — does NOT broadcast in tests (tool is mocked)
# ---------------------------------------------------------------------------


def test_build_mint_tx_request_strips_args_for_publicmint() -> None:
    job = ScheduledJob(
        id="x",
        contract_address=CONTRACT,
        qty=2,
        scheduled_at=0,
        value_wei=10,
        function_name="publicMint",
    )
    payload = json.loads(build_mint_tx_request(job))
    assert payload["function_name"] == "publicMint"
    assert payload["function_args"] == []
    assert payload["value_wei"] == 10
    assert payload["risk_score"] == 0


def test_build_mint_tx_request_passes_qty_for_mint() -> None:
    job = ScheduledJob(
        id="x",
        contract_address=CONTRACT,
        qty=3,
        scheduled_at=0,
        value_wei=0,
        function_name="mint",
    )
    payload = json.loads(build_mint_tx_request(job))
    assert payload["function_args"] == [3]


@pytest.mark.asyncio
async def test_execute_job_marks_done_on_success(
    tmp_queue: ScheduledMintQueue,
) -> None:
    job = await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) - 5
    )
    await tmp_queue.claim_due()

    tool = MagicMock()
    tool._run = MagicMock(
        return_value=json.dumps({"status": "success", "tx_hash": "0xabc"})
    )

    notified: list = []

    async def notifier(j, emoji, msg):  # type: ignore[no-untyped-def]
        notified.append((j.id, emoji, msg))

    await execute_job(job, tmp_queue, tool=tool, notifier=notifier)

    reloaded = await tmp_queue.list_all()
    assert reloaded[0].status == "done"
    assert "0xabc" in (reloaded[0].result or "")
    assert notified and notified[0][1] == "[OK]"


@pytest.mark.asyncio
async def test_execute_job_marks_failed_on_revert(
    tmp_queue: ScheduledMintQueue,
) -> None:
    job = await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) - 5
    )
    await tmp_queue.claim_due()

    tool = MagicMock()
    tool._run = MagicMock(
        return_value=json.dumps({"status": "reverted", "reason": "out of gas"})
    )

    notified: list = []

    async def notifier(j, emoji, msg):  # type: ignore[no-untyped-def]
        notified.append((j.id, emoji, msg))

    await execute_job(job, tmp_queue, tool=tool, notifier=notifier)
    reloaded = await tmp_queue.list_all()
    assert reloaded[0].status == "failed"
    assert notified and notified[0][1] == "[FAIL]"


@pytest.mark.asyncio
async def test_execute_job_survives_tool_crash(
    tmp_queue: ScheduledMintQueue,
) -> None:
    job = await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) - 5
    )
    await tmp_queue.claim_due()

    tool = MagicMock()
    tool._run = MagicMock(side_effect=RuntimeError("rpc died"))

    await execute_job(job, tmp_queue, tool=tool)
    reloaded = await tmp_queue.list_all()
    assert reloaded[0].status == "failed"
    assert "rpc died" in (reloaded[0].result or "")


@pytest.mark.asyncio
async def test_poll_and_execute_runs_only_due_jobs(
    tmp_queue: ScheduledMintQueue,
) -> None:
    await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) - 5
    )
    await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) + 600
    )

    tool = MagicMock()
    tool._run = MagicMock(
        return_value=json.dumps({"status": "success", "tx_hash": "0x" + "0" * 64})
    )

    ran = await poll_and_execute(tmp_queue, tool=tool)
    assert len(ran) == 1

    states = [j.status for j in await tmp_queue.list_all()]
    assert "done" in states
    assert "scheduled" in states  # the future job untouched


# ---------------------------------------------------------------------------
# Job lookup edge case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_by_prefix(tmp_queue: ScheduledMintQueue) -> None:
    job = await tmp_queue.enqueue(
        contract_address=CONTRACT, qty=1, scheduled_at=int(time.time()) + 600
    )
    short = job.id[:8]
    cancelled = await tmp_queue.cancel(short)
    assert cancelled is not None and cancelled.status == "cancelled"
