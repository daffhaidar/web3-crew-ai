"""File-backed scheduled-mint queue.

Defers a mint until a target unix timestamp. Persists across bot restarts
by writing the queue to a JSON file. Designed for a single-user bot (no
multi-tenant locking).

Lifecycle
---------
1. :func:`enqueue` writes a new job to the queue file in status
   ``scheduled``. The function returns a job ID immediately so the
   Telegram handler can echo it back to the user.
2. A long-running asyncio task -- spawned by ``telegram_bot.build_application``
   -- calls :func:`poll_and_execute` every ``poll_interval_seconds`` to
   find due jobs (``scheduled_at <= now`` and status ``scheduled``).
3. For each due job we transition status to ``executing``, persist, then
   invoke :class:`web3_crew.tools.safe_transaction.SafeTransactionTool`
   directly (NOT through the LLM -- the agent is not involved at
   execution time). The job is marked ``done`` or ``failed`` based on
   the tool's response.
4. Completed jobs stay in the file (for audit / status command) but
   are skipped on future polls.

Failure modes covered
---------------------
* Bot restart between ``enqueue`` and execution -- job persists; next
  startup spawns the poller and the job fires at its scheduled time.
* Bot down at scheduled_at -- job stays in ``scheduled`` and fires
  on next bot startup if its time has already passed (caller decides
  whether late firing is acceptable via :attr:`max_lateness_seconds`).
* SafeTransactionTool throws / returns ``rejected`` -- job marked
  ``failed`` with the tool's reason in :attr:`ScheduledJob.result`.
* RPC / chain outage -- caught in :func:`_execute_job` and surfaced as
  ``failed`` with the exception message.

Concurrency
-----------
File access is wrapped in ``asyncio.Lock`` to serialize concurrent
enqueue / poll calls within the same process. Cross-process locking
is NOT attempted -- this bot runs as a single process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)


_DEFAULT_QUEUE_PATH: Final[Path] = (
    Path.home() / ".web3-crew-ai" / "scheduled_mints.json"
)

# How late (seconds past ``scheduled_at``) is still acceptable to fire?
# Past this threshold the job is marked ``expired`` to avoid surprise
# mints hours after the user's window has closed.
DEFAULT_MAX_LATENESS_SECONDS: Final[int] = 30 * 60  # 30 minutes


@dataclass
class ScheduledJob:
    """One scheduled mint job."""

    id: str
    contract_address: str
    qty: int
    scheduled_at: int  # unix seconds, UTC
    value_wei: int
    function_name: str  # "publicMint" / "mint" / "safeMint" / ...
    status: str = "scheduled"  # scheduled | executing | done | failed | expired | cancelled
    created_at: int = field(default_factory=lambda: int(time.time()))
    user_id: int | None = None
    chain_id: int | None = None
    result: str | None = None  # tool response JSON or error message
    executed_at: int | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in {"done", "failed", "expired", "cancelled"}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ScheduledJob:
        # Allow forward-compat: ignore unknown fields rather than crash.
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def summary_line(self) -> str:
        """One-line human-readable summary for the /scheduled list view."""
        eta_or_done: str
        if self.is_terminal:
            eta_or_done = self.status
        else:
            delta = self.scheduled_at - int(time.time())
            if delta <= 0:
                eta_or_done = "now / pending poll"
            else:
                eta_or_done = f"T-{_fmt_delta(delta)}"
        return (
            f"[{self.id[:8]}] {self.qty}x mint @ {self.contract_address[:10]}... "
            f"({self.function_name}) -- {eta_or_done}"
        )


class ScheduledMintQueue:
    """File-backed FIFO queue of scheduled mints."""

    def __init__(
        self,
        *,
        queue_path: Path | None = None,
        max_lateness_seconds: int = DEFAULT_MAX_LATENESS_SECONDS,
    ) -> None:
        self.queue_path = queue_path or _DEFAULT_QUEUE_PATH
        self.max_lateness_seconds = max_lateness_seconds
        self._lock = asyncio.Lock()
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_unsafe(self) -> list[ScheduledJob]:
        if not self.queue_path.exists():
            return []
        try:
            raw = json.loads(self.queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.exception("Scheduled queue file is corrupt; starting fresh")
            return []
        return [ScheduledJob.from_dict(d) for d in raw if isinstance(d, dict)]

    def _save_unsafe(self, jobs: list[ScheduledJob]) -> None:
        self.queue_path.write_text(
            json.dumps([j.to_dict() for j in jobs], indent=2),
            encoding="utf-8",
        )

    async def load(self) -> list[ScheduledJob]:
        async with self._lock:
            return self._load_unsafe()

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        *,
        contract_address: str,
        qty: int,
        scheduled_at: int,
        value_wei: int = 0,
        function_name: str = "publicMint",
        user_id: int | None = None,
        chain_id: int | None = None,
    ) -> ScheduledJob:
        """Add a new job. Returns the persisted job (with assigned id)."""
        job = ScheduledJob(
            id=uuid.uuid4().hex,
            contract_address=contract_address,
            qty=qty,
            scheduled_at=scheduled_at,
            value_wei=value_wei,
            function_name=function_name,
            user_id=user_id,
            chain_id=chain_id,
        )
        async with self._lock:
            jobs = self._load_unsafe()
            jobs.append(job)
            self._save_unsafe(jobs)
        return job

    async def cancel(self, job_id: str) -> ScheduledJob | None:
        """Cancel a job by full id or 8-char prefix. None = not found."""
        async with self._lock:
            jobs = self._load_unsafe()
            target = _find_by_id(jobs, job_id)
            if target is None or target.is_terminal:
                return target
            target.status = "cancelled"
            self._save_unsafe(jobs)
            return target

    async def list_active(self) -> list[ScheduledJob]:
        async with self._lock:
            return [j for j in self._load_unsafe() if not j.is_terminal]

    async def list_all(self) -> list[ScheduledJob]:
        async with self._lock:
            return self._load_unsafe()

    async def claim_due(self, now: int | None = None) -> list[ScheduledJob]:
        """Find jobs whose scheduled_at has passed and atomically claim them.

        Status flips from ``scheduled`` -> ``executing`` so a second
        poll cannot re-claim the same job. Returns the claimed jobs.
        Jobs that are too late are flipped to ``expired`` instead.
        """
        now = now if now is not None else int(time.time())
        claimed: list[ScheduledJob] = []
        async with self._lock:
            jobs = self._load_unsafe()
            changed = False
            for job in jobs:
                if job.status != "scheduled":
                    continue
                if job.scheduled_at > now:
                    continue
                lateness = now - job.scheduled_at
                if lateness > self.max_lateness_seconds:
                    job.status = "expired"
                    job.result = (
                        f"missed firing window -- lateness {lateness}s > "
                        f"{self.max_lateness_seconds}s"
                    )
                    changed = True
                    continue
                job.status = "executing"
                changed = True
                claimed.append(job)
            if changed:
                self._save_unsafe(jobs)
        return claimed

    async def complete(self, job_id: str, *, status: str, result: str) -> None:
        if status not in {"done", "failed"}:
            raise ValueError(f"complete() requires done/failed, got {status!r}")
        async with self._lock:
            jobs = self._load_unsafe()
            target = _find_by_id(jobs, job_id)
            if target is None:
                logger.warning("complete() called for unknown job %s", job_id)
                return
            target.status = status
            target.result = result
            target.executed_at = int(time.time())
            self._save_unsafe(jobs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_by_id(jobs: list[ScheduledJob], job_id: str) -> ScheduledJob | None:
    """Match by full id or 8-char prefix."""
    if len(job_id) == len("0" * 32):
        for j in jobs:
            if j.id == job_id:
                return j
        return None
    # Prefix lookup
    matches = [j for j in jobs if j.id.startswith(job_id)]
    if len(matches) == 1:
        return matches[0]
    return None


def _fmt_delta(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"{seconds // 86400}d{(seconds % 86400) // 3600:02d}h"


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------


def parse_schedule_time(spec: str, *, now: int | None = None) -> int | None:
    """Parse a human schedule spec into a unix timestamp.

    Accepted formats (all UTC):

    * ``@HH:MM`` or ``HH:MM UTC`` -- today (or tomorrow if already past).
    * ``@<unix>`` -- absolute unix timestamp.
    * ``+<N>m`` / ``+<N>s`` / ``+<N>h`` -- relative offset from now.

    Returns ``None`` on parse failure (callers should reply with an
    error rather than guess).
    """
    import re

    now = now if now is not None else int(time.time())
    spec = spec.strip().lstrip("@").strip()

    # +<N><unit>
    m = re.fullmatch(r"\+(\d+)([smh])", spec)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        seconds = {"s": 1, "m": 60, "h": 3600}[unit]
        return now + n * seconds

    # Absolute unix
    m = re.fullmatch(r"(\d{10,})", spec)
    if m:
        return int(m.group(1))

    # HH:MM (optionally followed by UTC)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\s*UTC)?", spec, flags=re.IGNORECASE)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        # Construct today's HH:MM UTC
        import datetime as _dt

        today_utc = _dt.datetime.fromtimestamp(now, _dt.UTC).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        target = int(today_utc.timestamp())
        # If already past, schedule for tomorrow.
        if target <= now:
            target += 86400
        return target

    return None
