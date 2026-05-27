# HEARTBEAT.md — Session Heartbeat Checklist (v3)
# Runs every session start. Keep token cost low.

---

## On Every Heartbeat

```
1. Read memory/[today YYYY-MM-DD].md  → if exists, scan last 5 entries
2. Read MEMORY.md tail                → active projects + locked decisions
3. Re-confirm USER.md preferences     → name, language, tone, level
4. Skill registry already in m0.md    → do not re-read until intent matched
```

---

## Session Continuity Triggers

If memory shows pending task > 24h without update → flag at first opportunity:
> `Catatan: [task X] dari [date] masih open. Lanjutin atau drop?`

If memory shows incomplete deployment → offer resume:
> `Sesi terakhir: deploy [project] di tahap [step]. Lanjut dari sini?`

If operator returns after gap > 7 days → quick context recap (3 lines max):
> `Last session: [project] | Last decision: [X] | Open: [Y]`

---

## Per-Session State Tracking

Track internally (only output if asked):
```
session_start:      timestamp
goal:               stated objective
active_skill:       [m4, m6, ...]  // loaded modules
decisions:          []
blockers:           []
files_touched:      []
tokens_used:        approximate count
time_source:        layer_1 | layer_2 | layer_3 | layer_4 | layer_5
last_time_check:    timestamp
```

### Time refresh during heartbeat
On each heartbeat:
1. Check if `[RUNTIME CONTEXT]` present in current message → update `last_time_check`
2. If absent and last check >30min ago → call `get_current_time` tool
3. If time-sensitive task incoming (cron, deadline, vesting, claim) → force refresh regardless of cache age

---

## Token Discipline

- Skill files: load on demand, never preemptively
- After heavy operation (large code dump, file gen) → suggest:
  `Lanjut di sesi baru biar context fresh?` (only if obviously bloated)
- Memory writes: append only — never re-dump entire memory
