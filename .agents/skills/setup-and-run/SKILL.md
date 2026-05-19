---
name: setup-and-run
description: Setup local dev environment, configure secrets via .env, and run the bot in CLI or Telegram bridge mode. Use this when starting fresh on the repo, debugging "command not found" / missing-env errors, or when the user asks how to launch the bot.
---

# Setup & Run

Web3 Crew AI uses **uv** for dependency management and **pydantic-settings** for
config. All secrets live in `.env` (gitignored). `.env.example` is the canonical
template.

## Prerequisites

- Python **3.11+** (`python3 --version` to check)
- [`uv`](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

## First-time setup

```bash
cd /path/to/web3-crew-ai
uv sync                       # installs all deps from uv.lock into .venv
cp .env.example .env          # NEVER commit .env
$EDITOR .env                  # fill in secrets — see "Required env vars" below
```

`uv sync` is idempotent — safe to re-run after pulling new commits.

## Required env vars

| Variable | When required | Notes |
|---|---|---|
| `LLM_PROVIDER` | Optional | `gemini` (default) or `cerebras`. Switching is a pure env-var change. |
| `GEMINI_API_KEY` | When `LLM_PROVIDER=gemini` | Free tier OK — get at https://aistudio.google.com/app/apikey |
| `CEREBRAS_API_KEY` | When `LLM_PROVIDER=cerebras` | Free tier, very fast — get at https://cloud.cerebras.ai |
| `LLM_MODEL` | Optional | Pin a specific model. Empty = factory default per provider (`gemini/gemini-2.5-flash` or `cerebras/llama3.1-8b`). |
| `WEB3_RPC_URL` | Always | Alchemy / Infura HTTPS endpoint. Public RPC works but rate-limited. |
| `ETHERSCAN_API_KEY` | Always (for `/check` and source fetching) | https://etherscan.io/myapikey |
| `WALLET_PRIVATE_KEY` | Only for `/mint` (actual execution) | Hex, with or without `0x` prefix. **Burner wallet recommended.** |
| `CHAIN_ID` | Optional | Defaults to `1` (Ethereum mainnet). Set `137` for Polygon, `8453` for Base, etc. |
| `TELEGRAM_BOT_TOKEN` | Only for Telegram mode | BotFather token. |
| `AUTHORIZED_USER_ID` | Only for Telegram mode | Single numeric Telegram user ID. Everyone else is silently dropped. |

Optional tuning vars (gas, RBF, budget cap): see `.env.example` for full list with
defaults. Sane defaults ship in `src/web3_crew/config/settings.py`.

### Switching LLM provider

Only the *active* provider's API key is required. The other can stay empty.

```bash
# Free, fast Llama 3.1 8B on Cerebras
LLM_PROVIDER=cerebras
CEREBRAS_API_KEY=csk-...

# Or bigger Cerebras model (slower, stronger):
# LLM_MODEL=cerebras/gpt-oss-120b
```

The factory in `src/web3_crew/llm.py` raises a clear `ValueError` at boot if
the matching `*_API_KEY` is missing — no silent 401s at first agent call.

## Run modes

### CLI (one-shot audit + optional mint)

```bash
uv run python -m web3_crew.main 0xYourTokenAddress --action check
uv run python -m web3_crew.main 0xYourTokenAddress --action mint
```

`--action check` runs Data Gatherer + Auditor only (zero on-chain side effects).
`--action mint` runs the full pipeline and broadcasts the mint tx **if and only
if** `risk_score < MAX_RISK_SCORE` (default 50).

### Telegram bridge (long-running, recommended)

```bash
uv run python -m web3_crew.telegram_bot
```

Bot replies only to messages from the Telegram user ID set in
`AUTHORIZED_USER_ID`. All others get **silence** (one WARNING log line, no
acknowledgement). See `telegram-bot-commands` skill for the command surface.

## Common gotchas

- **`pydantic_settings.ValidationError`** on startup → a required env var is
  missing or empty. The error names which one. Fix in `.env` and re-run.
- **`uv: command not found`** → install via the curl one-liner above; do NOT
  `pip install uv` inside the project's venv (it conflicts).
- **`web3.exceptions.ProviderConnectionError`** → `WEB3_RPC_URL` is unreachable
  or rate-limited. Try a different provider or wait 60s.
- **Telegram bot starts but never replies** → confirm `AUTHORIZED_USER_ID`
  matches your numeric Telegram ID exactly (DM `@userinfobot` to get it). The
  bot is designed to be silent for unauthorized senders.

## What this skill is NOT

- Production deployment (no VPS / systemd / Docker instructions here yet)
- Cross-chain config beyond CHAIN_ID swap
- Wallet provisioning (use Metamask / similar externally)
