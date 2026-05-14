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

### Run

```bash
uv run python -m web3_crew.main 0xYourTokenAddress --action mint
```

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
│   ├── crew.py           # Crew orchestration
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
| `LLM_MODEL` | No | LiteLLM model identifier (default: `gemini/gemini-1.5-pro`) |
| `LLM_TEMPERATURE` | No | Sampling temperature for the LLM (default: `0.2`) |
| `WEB3_RPC_URL` | Yes | EVM JSON-RPC endpoint |
| `ETHERSCAN_API_KEY` | Yes | Etherscan API key |
| `WALLET_PRIVATE_KEY` | For execution | Hex-encoded private key |
| `CHAIN_ID` | No | EVM chain ID (default: 1) |

### LLM Provider

Agents use **Google Gemini (`gemini-1.5-pro`)** by default, wired through
[CrewAI](https://github.com/crewaiinc/crewai) → [LiteLLM](https://github.com/BerriAI/litellm).
Get an API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
and set `GEMINI_API_KEY` in your `.env`. To use a different Gemini model
(or any other LiteLLM-supported provider), override `LLM_MODEL` — e.g.
`gemini/gemini-1.5-flash` or `gemini/gemini-2.0-flash`.

## License

MIT
