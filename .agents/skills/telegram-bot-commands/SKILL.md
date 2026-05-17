---
name: telegram-bot-commands
description: Reference for the Telegram bot surface — the three commands (/start, /check, /mint), the single-user auth wall, and the response shapes. Use this when adding a new command, debugging "bot doesn't reply", or explaining what each command does and does not do.
---

# Telegram Bot Commands

Entry point: `src/web3_crew/telegram_bot.py`.
Run with: `uv run python -m web3_crew.telegram_bot`.

## Auth model — strict single-user gatekeeper

A `TypeHandler` registered at group `-1` runs **before any command handler**.
It checks:

```python
update.effective_user.id == settings.authorized_user_id
```

If false → `raise ApplicationHandlerStop` and dispatch ends. The
unauthorized sender gets **zero acknowledgement** — no error, no
"unauthorized" reply, no read receipt beyond what Telegram itself shows.
The bot logs one `WARNING` line containing the attacker's numeric ID and
**never** their message content.

Implication for testing: to reproduce auth rejection in a test, mock
`update.effective_user.id` to a value other than the configured one and
assert no command handler is called.

## Commands

### `/start`

- Returns a greeting + a one-line health check: confirms LLM key is set, RPC
  is reachable, and Etherscan key is set.
- No on-chain side effects.

### `/check <contract_address>`

- Runs **Data Gatherer → Auditor** only. The Transaction Executor agent is
  not part of the pipeline for this command.
- Returns the auditor's JSON report:
  ```json
  {
    "risk_score": 42,
    "flags": ["hidden_mint", "pausable_transfers"],
    "summary": "...",
    "token": {"name": "...", "symbol": "...", "decimals": 18, ...},
    "liquidity": {"pairs": [...], "total_usd": 12345}
  }
  ```
- Cost: zero ETH (read-only).

### `/mint <contract_address>`

- Runs the **full pipeline** (Gatherer → Auditor → Executor).
- If `risk_score >= MAX_RISK_SCORE` (default 50), executor returns
  `{status: "rejected", reason: ...}` and the bot replies with the reason
  + the auditor's flags. **No tx is signed.**
- If audit passes, executor builds + broadcasts the mint tx and returns
  one of `success | reverted | pending`. See the
  `safe-transaction-defensive-stack` skill for the exact response shapes.
- Reply always includes the auditor's risk score so the user can see why
  the mint was allowed (or refused).

## Response formatting

All bot replies are HTML-formatted (via `html.escape` on user-controlled
strings) and use ``<pre>`` blocks for JSON. Long contract source code or
DEX dumps are never echoed back — only the auditor's distilled JSON is
shown.

If a reply would exceed Telegram's 4096-char limit, the bot splits at JSON
boundaries and sends multiple messages. This is in `_send_long_reply()`.

## Adding a new command

1. Implement an async handler `async def _cmd_foo(update, context): ...` in
   `telegram_bot.py`.
2. Register it with `app.add_handler(CommandHandler("foo", _cmd_foo))`.
3. If the command runs the pipeline, route it through `crew.kickoff(...)`
   so the agent gating logic is reused.
4. Add a unit test in `tests/test_telegram_bot.py` that:
   - Mocks `Update` with the authorized user ID → asserts handler runs.
   - Mocks `Update` with a random user ID → asserts handler does NOT run
     and no reply is sent.

## Common failure patterns

- **Bot starts but silent for you too** → `AUTHORIZED_USER_ID` is wrong.
  DM `@userinfobot` to verify your ID.
- **`telegram.error.NetworkError: httpx.ConnectTimeout`** → outbound to
  `api.telegram.org` is blocked or the VM lost network. Retry once; if
  persistent, check VPN / firewall.
- **`/mint` replies with `{"status": "error"}` and no tx_hash** → a
  pre-submit failure. Check bot logs for the underlying exception
  message (sanitized — no PK will be there). Usually RPC down or wallet
  has 0 ETH.

## What this skill is NOT

- A general tutorial on python-telegram-bot v20+ API
- Multi-user / role-based access (the bot is intentionally single-user;
  changing that requires a settings migration AND a new auth model)
- Inline-button UX (the bot is command-only by design)
