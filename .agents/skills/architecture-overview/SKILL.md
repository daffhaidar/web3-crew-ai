---
name: architecture-overview
description: High-level map of the CrewAI multi-agent pipeline — agents, tasks, tools, and the data flow. Use this when orienting on the codebase, deciding where to add a feature, or when the user asks "how does this work end-to-end".
---

# Architecture Overview

Two independent pipelines share one LLM factory but have no other coupling:

```
  Specialist pipeline (/check, /mint)
  Data Gatherer  ─►  Smart Contract Auditor  ─►  Transaction Executor
      │                       │                        │
      ▼                       ▼                        ▼
  Token + DEX data       Risk score + flags        Signed tx + hash
                                                   (only if score < cap)

  General pipeline (/chat)
  ChatAgent (SUPERAGENT persona)
      │
      ▼
  SkillRouterTool ─► match keywords ─► load .agents/skills/*/SKILL.md
      │
      ▼
  Synthesized natural-language reply
```

## Pipeline data flow

1. **Data Gatherer** (`src/web3_crew/agents/data_gatherer.py`)
   - Tools: `TokenDataFetcherTool`, `DexScreenerTool`
   - Output: token metadata (name, deployer, total supply), `abi_summary`
     (short string — NOT the raw ABI), `source_findings` (pre-computed
     static-analysis hits, NOT the raw Solidity source), DEX liquidity
     snapshot.
   - **LLM-context discipline**: raw ABI and raw source code are
     parsed/scanned inside `TokenDataFetcherTool` and discarded before
     the response is built. Neither field ever enters the agent context.
     See `src/web3_crew/tools/source_analyzer.py` for the regex registry.

2. **Smart Contract Auditor** (`src/web3_crew/agents/contract_auditor.py`)
   - Tools: `RugPullDetectorTool` only. `ContractAnalyzerTool` was
     removed from the agent's tool list because invoking it forced the
     raw source to round-trip through the LLM context. The analyzer's
     logic now lives in `source_analyzer.analyze_source_code` and is
     called inline by the gatherer.
   - Output: JSON `{risk_score: int (0-100), risk_label: str, findings,
     recommendation: str}`. Patterns checked include hidden mint,
     blacklist, owner-only fee setters, pausable transfers, proxy
     backdoor, selfdestruct, unlimited approve.

3. **Transaction Executor** (`src/web3_crew/agents/tx_executor.py`)
   - Tools: `SafeTransactionTool` (the only tool that touches a wallet)
   - **Gate**: refuses to act if `risk_score >= MAX_RISK_SCORE` (default 50).
     Returns `{status: "rejected", reason: "..."}` without ever signing.
   - On audit pass: builds EIP-1559 tx, optionally routes through Flashbots
     Protect, broadcasts, waits for receipt, returns honest status.

4. **ChatAgent** (`src/web3_crew/agents/chat_agent.py`) — separate pipeline
   - Tools: `SkillRouterTool` (single tool, no Web3 access)
   - Persona: loaded from `.agents/persona/SOUL.md` + `IDENTITY.md` into
     `backstory`. SUPERAGENT tone: direct, tactical, execute first.
   - Used by `/chat <text>` only. Never inherits / leaks into the specialist
     pipeline — their agents keep their original backstories untouched.

## File map

```
src/web3_crew/
├── main.py             # CLI entry point: `python -m web3_crew.main <addr>`
├── telegram_bot.py     # Long-running Telegram bridge entry point
├── crew.py             # `build_crew` (audit/mint) + `build_chat_crew` (chat)
├── llm.py              # Gemini-via-LiteLLM factory; shared by all agents
├── config/settings.py  # pydantic-settings; loads .env, validates types
├── agents/             # data_gatherer + contract_auditor + tx_executor + chat_agent
├── tasks/              # gather/audit/execute tasks + chat_task
└── tools/              # CrewAI BaseTool subclasses; pure functions over Web3 RPC
                       # plus skill_router (filesystem-only, no Web3 calls)

.agents/
├── skills/             # 17 SKILL.md files loaded on demand by SkillRouterTool
└── persona/            # SOUL.md + IDENTITY.md, injected into ChatAgent only
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
| New tone / language for replies | For specialist agents: edit their `backstory` directly. For the ChatAgent: edit `.agents/persona/SOUL.md` / `IDENTITY.md`. |
| New free-form chat skill | Drop a `SKILL.md` with YAML frontmatter into `.agents/skills/<name>/` and add a row to `SKILL_REGISTRY` in `tools/skill_router.py`. |
| New chain support (e.g., Base, Polygon) | `CHAIN_ID` already plumbed through settings + explorer URL builder; verify ABI is chain-agnostic |

## What this skill is NOT

- API reference for individual tools (read the docstrings in `tools/`)
- Step-by-step tutorial (see `setup-and-run` skill)
- Deployment / hosting strategy
