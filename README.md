# Web3 Crew AI

**Autonomous Multi-Agent System** for Web3 token analysis, smart contract auditing, and safe transaction execution — powered by [CrewAI](https://github.com/crewaiinc/crewai).

## Architecture

Three specialized agents work in a **sequential pipeline**:

```
Data Gatherer  →  Smart Contract Auditor  →  Transaction Executor
```

| Agent | Role | Tools |
|-------|------|-------|
| **Data Gatherer** | Collects token metadata, source code, and DEX liquidity data | `TokenDataFetcherTool`, `DexScreenerTool` |
| **Smart Contract Auditor** | Static analysis for rug-pull patterns, risk scoring | `ContractAnalyzerTool`, `RugPullDetectorTool` |
| **Transaction Executor** | Executes on-chain transactions **only** if audit passes | `SafeTransactionTool` |

## Security

- **No hardcoded keys** — all secrets loaded from `.env` via `pydantic-settings`
- **Transaction gating** — executor refuses to transact if `risk_score >= 50`
- **Gas cap** — hard limit on gas to prevent runaway transactions
- `.env` is in `.gitignore` — only `.env.example` is committed

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Setup

```bash
# Clone the repo
git clone <repo-url>
cd web3-crew-ai

# Install dependencies
uv sync

# Copy and fill in your environment variables
cp .env.example .env
# Edit .env with your real API keys and wallet
```

### Run (CLI)

```bash
uv run python -m web3_crew.main 0xYourTokenAddress --action mint
```

### Run (Telegram bot)

```bash
uv run python -m web3_crew.telegram_bot
```

See the [Telegram Bridge](#telegram-bridge) section below for setup details.

### Lint

```bash
uv run ruff check src/ tests/
```

### Test

```bash
uv run pytest
```

## Project Structure

```
web3-crew-ai/
├── .env.example          # Template (committed)
├── .gitignore
├── pyproject.toml
├── README.md
├── src/web3_crew/
│   ├── main.py           # CLI entry point
│   ├── telegram_bot.py   # Telegram bridge entry point
│   ├── crew.py           # Crew orchestration
│   ├── llm.py            # Shared LLM factory (Gemini via LiteLLM)
│   ├── agents/           # Agent definitions
│   ├── tasks/            # Task definitions
│   ├── tools/            # Custom CrewAI tools
│   └── config/           # Settings (.env loader)
└── tests/
```

## Configuration

All configuration is in `.env`. See `.env.example` for available variables.

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google Gemini API key for the LLM (used via LiteLLM) |
| `LLM_MODEL` | No | LiteLLM model identifier (default: `gemini/gemini-2.5-flash`) |
| `LLM_TEMPERATURE` | No | Sampling temperature for the LLM (default: `0.2`) |
| `WEB3_RPC_URL` | Yes | EVM JSON-RPC endpoint |
| `ETHERSCAN_API_KEY` | Yes | Etherscan API key |
| `WALLET_PRIVATE_KEY` | For execution | Hex-encoded private key |
| `CHAIN_ID` | No | EVM chain ID (default: 1) |
| `TELEGRAM_BOT_TOKEN` | For bot | BotFather token (only required to run the Telegram bridge) |
| `AUTHORIZED_USER_ID` | For bot | Telegram numeric user ID allowed to send commands (only required to run the Telegram bridge) |

### LLM Provider

Agents use **Google Gemini (`gemini-2.5-flash`)** by default, wired through
[CrewAI](https://github.com/crewaiinc/crewai) → [LiteLLM](https://github.com/BerriAI/litellm).
Get an API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
and set `GEMINI_API_KEY` in your `.env`.

**Why `gemini-2.5-flash` is the default:** as of late-2025 Google's free Gemini
API tier no longer grants quota to any `*-pro` model (`gemini-2.5-pro`,
`gemini-pro-latest`, etc.) — calls return `429 RESOURCE_EXHAUSTED` with
`limit: 0`. `gemini-2.5-flash` is the strongest model currently available on
the free tier and is enough for these agents' reasoning load.

To upgrade to a pro model, enable billing on your AI Studio project and
override `LLM_MODEL` in `.env`:

```dotenv
LLM_MODEL=gemini/gemini-2.5-pro
```

## Telegram Bridge

Control the crew remotely via a Telegram bot:

| Command | Pipeline | Side effect |
|---------|----------|-------------|
| `/start` | none | greeting + status |
| `/check <address>` | Data Gatherer → Auditor | sends JSON risk report; **never** runs the Transaction Executor |
| `/mint  <address>` | full pipeline | mints if audit passes, returns TxHash; rejects if risk score is too high |

### OPSEC

The bot enforces a single authorized Telegram user ID via a `TypeHandler`
registered at group `-1`. Every update whose `effective_user.id` does not
exactly match `AUTHORIZED_USER_ID` raises `ApplicationHandlerStop`, which
terminates dispatch before any command handler is reached. Unauthorized
senders receive **no reply** and the only side effect is a `WARNING` log
line containing their numeric ID (never the message payload).

The bot also refuses to boot when either `TELEGRAM_BOT_TOKEN` or
`AUTHORIZED_USER_ID` is missing — fail loud, not silent.

### Setup

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram and run
   `/newbot`. Copy the token into `TELEGRAM_BOT_TOKEN` in your `.env`.
2. Talk to [@userinfobot](https://t.me/userinfobot) to find your numeric
   Telegram user ID. Put it in `AUTHORIZED_USER_ID`.
3. Run the bot:

   ```bash
   uv run python -m web3_crew.telegram_bot
   ```

4. Message your bot `/start` to confirm it's online.

## License

MIT
