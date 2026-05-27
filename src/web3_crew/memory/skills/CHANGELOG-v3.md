# CHANGELOG — v3 OPENCLAW EDITION

Released 2026-05-25.

---

## Headline changes
- 🆕 **3 new skills**: m10 Web3, m11 Security, m12 Batch
- 🆕 **NFT minter skill**: m13 (universal mint with auto-gas, OpenSea/Manifold/Zora)
- 🆕 **Hermes Crypto Agent absorbed**: full deep-crypto layer at `skills/hermes/` (10 refs + 8 Python templates)
- ⏰ **TIME.md** — 5-layer time-awareness architecture (system inject → tool → cache → infer → disclose). No more time-blind hallucination on deadlines/cron/vesting/claim windows.
- ⚡ **Smarter router**: priority-weighted keywords, multi-skill orchestration, H1-H7 hermes dispatch
- 🛠 **m4 Telegram** now production-grade (anti-duplicate, webhook mode, multi-bot)
- 🤖 **m7 AI** rewritten: streaming, function calling, provider fallback chain, cost tracking
- 🖥 **m2 VPS** expanded: systemd, tmux, nginx security headers, backup automation
- 🔐 **Tighter SOUL**: 2 hard stops only, permissive on grey-area + operational rails for crypto ops
- 🇮🇩 **m3 voice**: airdrop template now matches operator's exact format

---

## New files
| File | Why |
|---|---|
| `skills/m10.md` | Web3 ops kept getting stuffed into m6. Now dedicated: RPC fallback, BIP39 wallet gen, NonceManager, simulate→send→wait pattern, eligibility O(1) checker, mass farming with p-limit, multicall, Solana basics. |
| `skills/m11.md` | Security audits (tradingview-mcp, Daydreams skill) were ad-hoc. Now: skill-file injection checklist, Solidity red flags, suspicious package signals, secret leak detection, OpenClaw-specific safety. |
| `skills/m12.md` | Batch patterns scattered. Now: p-limit, asyncio.gather, token bucket, progress tracking, resume-from-failure checkpoint pattern. |
| `skills/m13.md` | **Universal NFT minter**. One command → mint anywhere. Parses OpenSea/Manifold/Zora URLs or raw contract address. Auto-detects mint function via signature probing + ABI fallback. Auto-detects mint price. Auto-gas (estimate + 20% buffer, EIP-1559 priority tuned per chain). Simulate → send → wait → report. Combo with m12 for mass mint with N wallets. Supports Seadrop (OpenSea), Manifold Claims, Zora 1155 protocol-specific paths. |
| `skills/hermes/*` | **Hermes Crypto Agent integration** — entire deep-crypto skill (SKILL.md + 10 references + 8 Python templates) absorbed into v3 as a sub-skill layer. Loaded via H1-H7 dispatch routes (swap, bridge, defi, sniping, mempool/smart-money, NFT marketplace buy/sell, SIWE/WC). Multi-chain coverage: EVM + Solana + Sui + Aptos + TON. Marketplace flows: Seaport / Blur / Reservoir / Magic Eden / Tensor. DeFi: Aave V3 / Lido / EigenLayer / GMX V2 / Hyperliquid / Pendle. Mempool sniffer with frontrun + drainer detection. Smart-money tracker via Nansen / Arkham / Dune. |
| `TIME.md` | **5-layer time-awareness architecture**. Solves LLM time-blindness. Layer 1 system inject (host wrapper prepends `[RUNTIME CONTEXT]`), Layer 2 tool call (`get_current_time`, `get_block_timestamp`), Layer 3 session cache (30min refresh), Layer 4 user-message inference (tagged as assumption), Layer 5 explicit disclosure (never fabricate). Strict mode for crypto cron/deadline/vesting/claim. Block timestamp sanity check (system_time vs on_chain_ts desync detection). Contributor: 👁⃤Fiⱥnͥ.ⱥsͣsͫⱥn 𓂀 ([@fianassan25](https://t.me/fianassan25)). |
| `CONTRIBUTORS.md` | Credits — CVC Owner + Member contributions. |
| `panduan.md` | Operator usage guide (12 sections + cheat sheet) with real Hermes examples. |
| `CHANGELOG-v3.md` | This file. |
| `INDEX.md` | One-line index of all files. |

---

## Upgraded files

### `AGENTS.md`
- Rules expanded from R1-R6 to R1-R10
- R7: **provider cascade** (Anthropic → Kimi → OpenRouter → DeepSeek → Groq)
- R8: **multi-skill orchestration** (load 2-3 skills when task spans domains)
- R9: **token economy** (refuse to load >3 skills without explicit need)
- R10: **escape hatch** (when stuck, drop to m0 reflection loop)
- New keyword weight table — EN + ID, weighted 1-5 per term
- Added crypto/Web3 trigger cluster

### `IDENTITY.md`
- Added 3 response speed tiers: fast (one-liner) / standard / deep
- New character mode: **Web3 operator** voice (CT-style, no fluff)
- Tightened against motivational filler

### `SOUL.md`
- Hard stops reduced to **2**: CSAM, mass-casualty weapons
- Single risk gate replaces multi-layer (was over-refusing on grey-area)
- Explicit permissive doctrine on: crypto ops, on-chain automation, growth hacking, content stunting, security research on own systems

### `HEARTBEAT.md`
- Smart continuity triggers (resume detection without explicit ask)
- Token discipline rules: warn at 60%, compact at 80%
- Session resume protocol

### `TOOLS.md`
- Split agent-side vs operator-side tool execution surface
- OpenClaw streaming config bug documented (`streaming: false` boolean, not string)
- Hermes-specific tool registration notes

### `USER.md`
- Now a **template** with fill-in slots
- New "trigger phrases" section (operator-specific keywords)
- Domain focus checkboxes (crypto / dev / content / ops)

### `MEMORY.md`
- Compact format spec (1 line per entry)
- 30-day rolling window
- Monthly compaction rules
- Anti-bloat enforcement

### `skills/m0.md`
- Registry now 12 skills + 3 expansion (was 9 + 3)
- Reflection loop tightened: ask "what did this teach me" only on failure, not every call
- Escape hatch protocol when no skill matches

### `skills/m1.md`
- Added crypto monetization: paid alpha, premium TG channels, affiliate referral codes
- Indonesia-specific channels (Saweria, Trakteer alongside global tools)

### `skills/m2.md`
- Full VPS bootstrap script
- pm2 + systemd + screen + tmux comparison table
- nginx production template with security headers
- Backup automation cron pattern
- OpenClaw-specific VPS patterns (workspace dir, agent restart)
- Security hardening checklist

### `skills/m3.md`
- **Airdrop template** now matches Kakak's exact format:
  ```
  New Airdrops : (Name Project)
  🏷 Reward : ...
  🪂 Register :
  ➖ Join Telegram
  ➖ Follow Twitter & Retweet
  ➖ Submit BSC Address
  ➖ Complete Another Task
  ➖ Done
  
  📖 Details : ...
  ```
- CT-style crypto hooks library
- Indonesian voice patterns (casual lo/gue, sarkasme)
- Sarcastic commentary patterns for crypto culture posts

### `skills/m4.md` — biggest rewrite
- Anti-duplicate dedupe with Map+TTL (the OpenClaw streaming bug pattern)
- Retry + rate limit baked in
- Webhook mode (production) + polling mode (dev)
- Telegraf alternative shown
- cron + APScheduler for jobs
- Idempotent job pattern
- In-memory queue
- Multi-bot orchestration (Kakak's @ClaudebySetya_bot + others)
- `polling_error` recovery handler (was missing in v2 → caused silent bot deaths)

### `skills/m5.md`
- O(1) lookup pattern for snapshot files (Kakak's Pharos 208K bot pattern)
- SQLite for medium datasets
- Crypto-specific: holders parsing, spam wallet detection, wallet bundling heuristics

### `skills/m6.md`
- Circuit breaker pattern added
- Token bucket rate limiter
- HMAC verification (webhook security)
- Midtrans + Xendit + WhatsApp Cloud API templates

### `skills/m7.md` — full rewrite
- Anthropic with proper headers (`x-api-key`, `anthropic-version`)
- Streaming SSE handler
- OpenAI-compat wrapper for Kimi/OpenRouter/DeepSeek/Groq
- **Provider fallback chain** with try/catch cascade
- Function calling / tool use loop
- Cost tracking with PRICING table per provider
- Caching layer (request-level dedupe)
- Universal Python wrapper

### `skills/m8.md`
- DOCX/XLSX/PPTX/PDF templates
- **PDF with clickable hyperlinks** via ReportLab (the Kakak 40-account PDF pattern)
- Image processing: rembg, cartoonize, upscale

### `skills/m9.md`
- HTML+Tailwind production template
- React + wagmi Web3 connect button (real implementation)
- Pricing section pattern
- Form with validation
- AOS + Framer Motion integration
- Performance protocol (Lighthouse-target)

### `skills/x1.md`
- Added skill coverage matrix audit
- Token usage profiling
- Soul drift check
- Signals from user feedback shape ("panjang amat" → compress, etc)

### `skills/x2.md`
- **Pre-mortem step** (NEW): assume failed, why?
- **Reversibility framework**: two-way vs one-way door decisions
- Tradeoff matrix tightened

### `skills/x3.md`
- **Common error pattern library**: Node/JS, Python, Telegram, Web3, VPS, OpenClaw/Hermes specific
- OpenClaw `streaming` config bug catalogued
- Decision tree for diagnosis class

---

## Migration notes from v2
1. Back up v2 memory: `cp -r v2/memory v2/memory.bak`
2. Drop v3 in alongside v2 (don't overwrite immediately)
3. Migrate daily logs: `cp v2/memory/*.md v3/memory/`
4. Update agent config to point at v3 path
5. Restart agent
6. Run x1 audit after 48h to catch any routing issues
7. Keep v2 for 7 days as rollback

---

## Known good combos (multi-skill load)
- "bikin bot Telegram + bayar TON" → m4 + m6 + m10
- "audit skill file ini" → m11 (alone)
- "mass mint 300 wallet" → m13 + m12 + m10
- "mint NFT dari URL ini" → m13 (alone)
- "mint NFT pakai 50 wallet di Base" → m13 + m12
- "swap 1000 USDC ke ETH di base" → H1 (hermes/swap.md) + m10
- "bridge dari arb ke base via stargate" → H2 (hermes/bridge.md)
- "stake ETH di lido" → H3 (hermes/defi.md)
- "snipe token baru di uniswap" → H4 (hermes/sniping.md) + m10
- "pantau wallet whale 0xABC..." → H5 (hermes/monitoring.md)
- "beli NFT bored ape #1234 di opensea" → H6 (hermes/nft.md)
- "farming airdrop layerzero 50 wallet" → H2 + H1 + m12 (multi-wallet jitter pattern)
- "tracker smart money via nansen + alert telegram" → H5 + m4
- "kenapa bot gua duplikat" → x3 + m4
- "deploy ke VPS" → m2 (alone, m4 may join if Telegram involved)
- "buat landing page web3" → m9 + m10

---

## Roadmap (NOT in v3, candidates for v4)
- m13: Solana-deep (anchor, SPL token, Phantom signing)
- m14: Twitter/X automation (agent-twitter-client patterns, follow tracker)
- m15: SEO + organic content distribution
- x4: Tone calibration (per-channel voice tuning)
