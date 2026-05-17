---
name: architecture-overview
description: High-level map of the CrewAI multi-agent pipeline — agents, tasks, tools, and the data flow. Use this when orienting on the codebase, deciding where to add a feature, or when the user asks "how does this work end-to-end".
---

# Architecture Overview

Three specialized CrewAI agents run as a **strict sequential pipeline**.
Each agent owns exactly one task and a bounded toolset.

```
   Data Gatherer  ─►  Smart Contract Auditor  ─►  Transaction Executor
       │                       │                        │
       ▼                       ▼                        ▼
  Token + DEX data       Risk score + flags        Signed tx + hash
                                                   (only if score < cap)
```

## Pipeline data flow

1. **Data Gatherer** (`src/web3_crew/agents/data_gatherer.py`)
   - Tools: `TokenDataFetcherTool`, `DexScreenerTool`
   - Output: token metadata (name, symbol, decimals, total supply, source
     code from Etherscan), DEX liquidity snapshot (pairs, USD liquidity, 24h
     volume).

2. **Smart Contract Auditor** (`src/web3_crew/agents/contract_auditor.py`)
   - Tools: `ContractAnalyzerTool`, `RugPullDetectorTool`
   - Output: JSON `{risk_score: int (0-100), flags: [str], summary: str}`.
     Patterns checked include hidden mint, blacklist, owner-only fee setters,
     pausable transfers, fee-on-transfer, mintable supply, ownership
     concentration, proxy backdoor.

3. **Transaction Executor** (`src/web3_crew/agents/tx_executor.py`)
   - Tools: `SafeTransactionTool` (the only tool that touches a wallet)
   - **Gate**: refuses to act if `risk_score >= MAX_RISK_SCORE` (default 50).
     Returns `{status: "rejected", reason: "..."}` without ever signing.
   - On audit pass: builds EIP-1559 tx, optionally routes through Flashbots
     Protect, broadcasts, waits for receipt, returns honest status.

## File map

```
src/web3_crew/
├── main.py             # CLI entry point: `python -m web3_crew.main <addr>`
├── telegram_bot.py     # Long-running Telegram bridge entry point
├── crew.py             # Glues agents + tasks + sequential Process
├── llm.py              # Gemini-via-LiteLLM factory; shared by all agents
├── config/settings.py  # pydantic-settings; loads .env, validates types
├── agents/             # CrewAI Agent definitions (role + goal + backstory)
├── tasks/              # CrewAI Task definitions (description + expected_output)
└── tools/              # CrewAI BaseTool subclasses; pure functions over Web3 RPC
```

## Conventions

- **Pure-function tools**: every tool in `tools/` is a `BaseTool` whose `_run`
  is deterministic given its args + chain state. No global mutation, no
  cross-tool state leakage.
- **Settings are read once** at process start via `get_settings()` (cached).
  Never read env vars directly from tool code — always go through the
  Settings object so tests can override cleanly.
- **Status, not exceptions**: tools return structured `{status, reason, ...}`
  dicts. Exceptions bubble up to the CrewAI process boundary but the tx
  executor specifically catches and translates everything into one of:
  `success | reverted | pending | rejected | error`. See
  `safe-transaction-defensive-stack` skill.
- **No secrets in logs**: every tool that handles `WALLET_PRIVATE_KEY` runs
  through `_scrub_private_key()` before formatting any error message. This is
  enforced by tests in `test_tools.py::test_scrub_private_key_*`.

## Where to add a new feature

| Feature idea | Where to add |
|---|---|
| New on-chain data source (e.g., Tenderly simulation) | `tools/`, then bind to Data Gatherer agent |
| New rug-pull heuristic | Extend `RugPullDetectorTool`, add unit test |
| New on-chain action (e.g., `/sell`, `/approve`) | New task in `tasks/`, wire to Tx Executor, add `/cmd` in `telegram_bot.py` |
| New tone / language for replies | Edit agent `backstory` field; do NOT add a SOUL.md persona layer |
| New chain support (e.g., Base, Polygon) | `CHAIN_ID` already plumbed through settings + explorer URL builder; verify ABI is chain-agnostic |

## What this skill is NOT

- API reference for individual tools (read the docstrings in `tools/`)
- Step-by-step tutorial (see `setup-and-run` skill)
- Deployment / hosting strategy
