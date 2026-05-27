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
| `GAS_STRATEGY` | No | EIP-1559 priority-fee strategy: `slow`/`standard`/`fast`/`aggressive` (default: `fast`) |
| `MAX_PRIORITY_FEE_GWEI` | No | Hard cap on `maxPriorityFeePerGas` in gwei (default: `5`) |
| `FLASHBOTS_RPC_URL` | No | Optional MEV-protected submission endpoint (e.g. `https://rpc.flashbots.net`) |
| `MAX_TX_COST_ETH` | No | Per-tx worst-case cost cap in ETH (default: `0.05`) |
| `TX_WAIT_SECONDS` | No | Receipt wait timeout per attempt in seconds (default: `120`) |
| `ENABLE_AUTO_RBF` | No | Opt-in Replace-By-Fee retry on stuck tx (default: `false`) |
| `MAX_RBF_ATTEMPTS` | No | RBF retries when enabled (default: `1`) |

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
| `/chat <text>` | ChatAgent + SkillRouter | SUPERAGENT-style general assistant; dynamically loads `.agents/skills/*/SKILL.md` to answer free-form requests (server, monetize, content, automation, data, API, AI, files, frontend, audit, strategy, debug) |

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

## Gas War (EIP-1559) and Anti-MEV

The Transaction Executor builds **EIP-1559** transactions and computes
fees dynamically from chain state instead of using legacy `gas_price`.

```
maxPriorityFeePerGas = min(suggested_priority * strategy_multiplier,
                           MAX_PRIORITY_FEE_GWEI)
maxFeePerGas         = 2 * base_fee + maxPriorityFeePerGas
```

Priority fee (the tip validators see) is what wins a race for the next
block. `MAX_PRIORITY_FEE_GWEI` is a hard cap so a volatile network can
never drain the wallet through a runaway bid.

| `GAS_STRATEGY` | Priority multiplier | When to use |
|----------------|---------------------|-------------|
| `slow` | 1.0x | Background approvals, non-urgent transfers |
| `standard` | 1.5x | Regular trades on a calm network |
| `fast` (default) | 2.0x | Default for `/mint` — aims for inclusion in the next block |
| `aggressive` | 3.0x | Contested mints, NFT drops, time-sensitive arbitrage |

If the chain doesn't expose `baseFeePerGas` (pre-London or some L2s),
the executor falls back to a legacy `gasPrice` transaction automatically.

### Anti-MEV via Flashbots Protect

Set `FLASHBOTS_RPC_URL=https://rpc.flashbots.net` to broadcast signed
transactions through Flashbots' private mempool. MEV bots scanning the
public mempool never see the tx, so they cannot sandwich or frontrun it.
Reads (nonce, gas estimate, balance, receipt polling) still use your
primary `WEB3_RPC_URL`. Flashbots Protect is free, requires no auth, and
is Ethereum mainnet only — leave the variable blank on other chains.

## Defensive Execution

The Transaction Executor reports **four** honest outcome statuses
instead of conflating mining with success:

| `status` | Meaning | ETH spent? |
|----------|---------|-----------:|
| `success`  | Mined, `receipt.status == 1` | Yes — normal gas |
| `reverted` | Mined, `receipt.status == 0` (execution failed on-chain) | Yes — gas was burned up to the revert point |
| `pending`  | Not mined within `TX_WAIT_SECONDS`, or the RPC errored (rate limit / network blip) while polling for the receipt. Tx still alive in the mempool. | No yet — but the nonce is reserved |
| `rejected` | Never submitted — audit risk too high, or worst-case cost over budget | No |

`reverted` and `pending` responses include both `tx_hash` and
`explorer_url`, so the Telegram user can investigate or replace a stuck
or failed tx in one click instead of copy-pasting hashes.

### Worst-case cost budget

Before signing, the executor refuses to submit any transaction whose
`gas_limit * max_fee_per_gas` exceeds `MAX_TX_COST_ETH` (default
`0.05` ETH). The rejection response includes `gas_limit`,
`max_fee_per_gas`, the computed `worst_case_cost_eth`, and the active
`budget_eth` so the user can decide whether to raise the cap or wait
for fees to fall.

### Replace-By-Fee (opt-in)

When `ENABLE_AUTO_RBF=true`, a tx that is `pending` after
`TX_WAIT_SECONDS` is resubmitted under the **same nonce** with a 1.5x
bumped priority fee, up to `MAX_RBF_ATTEMPTS` times. Every retry is
re-checked against `MAX_TX_COST_ETH`, so RBF can never silently push
the wallet past the budget. If the bumped fee would blow the budget,
the executor returns `pending` for the last-submitted tx instead of
attempting another replacement. RBF is **off** by default to preserve
the original conservative one-shot behaviour.

## License

MIT
