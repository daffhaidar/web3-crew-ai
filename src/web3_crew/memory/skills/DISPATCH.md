# skills/hermes/DISPATCH.md
# Bridge between v3 SUPERAGENT router and Hermes Crypto Agent deep references.
# Load ONLY when m10 / m13 router decides a task needs hermes depth.

---

## When to dispatch into hermes

v3 router (AGENTS.md keyword table) handles surface-level crypto. When task touches any of these, escalate by loading the matching `hermes/references/*.md`:

```
KEYWORD CLUSTER                         → LOAD hermes/references/
----------------------------------------|-------------------------
import wallet, seed phrase, mnemonic     | wallets.md
buat wallet Solana/Sui/Aptos/TON         | wallets.md
swap token, sell, 1inch, Jupiter         | swap.md
beli NFT, OpenSea API, Blur, Magic Eden  | nft.md
snipe launch, PairCreated, honeypot      | sniping.md
airdrop multi-wallet, sybil, jitter      | airdrop_automation.md
bridge, LayerZero, Stargate, LI.FI       | bridge.md
Aave, Lido, GMX, Hyperliquid, Pendle     | defi.md
SIWE, WalletConnect, EIP-712, ENS        | web3_connect.md
mempool, whale tracker, Nansen, Arkham   | monitoring.md
encrypt vault, secret hygiene            | security.md
```

---

## How m10 (Web3 lite) and hermes interact

```
v3 router → matches "web3 / crypto / wallet" keywords
         → loads m10 (lightweight Web3 ops + patterns)
         → if task is DEEP (specific protocol, multi-chain, advanced):
              also load hermes/references/<topic>.md
         → if task is SIMPLE (basic mint, balance check, RPC call):
              m10 alone is enough
```

**m10 covers (no hermes needed):**
- Basic EVM ops: transfer, balance, ENS resolve
- RPC fallback pattern
- Wallet gen (BIP39, single chain)
- Simple airdrop eligibility O(1)
- NonceManager for parallel sends (single chain)

**Hermes covers (escalate to load):**
- Non-EVM chains (Solana / Sui / Aptos / TON)
- DEX aggregator integration (1inch / Jupiter / LI.FI)
- NFT marketplace SDKs (Seaport / Reservoir / Magic Eden)
- DeFi protocol contracts (Aave / Lido / GMX / Pendle ABIs and flows)
- Mempool subscriptions + frontrun protection
- Smart-money APIs (Nansen / Arkham / Dune)
- Sniping with honeypot + GoPlus safety gates
- Multi-wallet airdrop runner with sybil-aware jitter

---

## How m13 (NFT mint) and hermes/references/nft.md interact

m13 = **universal minter** (mint flow, any contract, any chain, auto-gas).
hermes nft.md = **marketplace buy/sell** (OpenSea Seaport fulfill, Blur, Magic Eden Tensor, Reservoir).

Decision tree:
```
User wants to MINT (primary/secondary) at fixed mint price
   → m13 only

User wants to BUY existing NFT from a listing
   → hermes/references/nft.md (Seaport fulfill, Reservoir)

User wants to LIST/SELL their NFT
   → hermes/references/nft.md (EIP-712 sign + post to marketplace API)

User wants to SNIPE a mint launch the moment it opens
   → m13 + hermes/references/sniping.md (PairCreated listener, safety gate)
```

---

## Safety reconciliation: v3 SOUL vs hermes principles

**v3 SOUL** = permissive doctrine, 2 hard stops (CSAM, mass-casualty weapons).
**Hermes principles** = operational safety rails for crypto ops.

These DO NOT conflict. Hermes rails are *technical safeguards* (simulate before send, secret hygiene), not refusal triggers. They are ALWAYS active when doing on-chain ops:

| Rail | Default | Override |
|---|---|---|
| Secret hygiene (never log priv key) | ON, no override | none — hard rule |
| User-funds-only (refuse 3rd-party seed) | ON, no override | none — hard rule |
| No drainer / scam payload | ON, no override | none — hard rule |
| **Simulate before broadcast** | ON | `--skip-sim` flag for known patterns |
| **Confirm before signing** | ON for first tx in session | `auto_confirm=True` per session |
| Sybil reminder (multi-wallet airdrop) | ONCE per session | acknowledged → silent |

The "confirm before signing" rail is what lets Kakak's "mint cepat tanpa mikir" mode work: set `auto_confirm=True` at session start → m13 fires without prompting. First tx still gets one safety summary, but it's information only, no gate.

---

## Loading order

For complex crypto task, agent loads in this order:
```
1. AGENTS.md (always-on)
2. m0.md (skill registry)
3. m10.md (Web3 router/orchestrator)        ← v3 layer
4. skills/hermes/DISPATCH.md                ← this file
5. skills/hermes/references/<topic>.md      ← depth as needed
6. (combo) m12.md if batch, m13.md if mint, m11.md if audit
```

Each step is additive. Skip steps that don't apply.

---

## Hermes script templates

`skills/hermes/scripts/` contains 8 Python templates ready to copy into operator's environment:

```
wallet_manager.py       — encrypted multi-chain wallet vault
swap_engine.py          — 1inch / Jupiter swap with simulation
nft_engine.py           — Seaport buy/sell, Reservoir aggregator
bridge_engine.py        — LI.FI quote + execute
web3_connect.py         — SIWE / WalletConnect / EIP-712 handler
monitoring.py           — basic WS wallet/event listener
monitoring_advanced.py  — mempool sniffer + smart money + drainer alert
airdrop_runner.py       — multi-wallet runner with jitter + resume
```

When operator asks "buat skrip X", reference these templates first (don't reinvent).

---

## Environment variable map

Hermes references expect these env vars. Pre-flight check before any deep op:
```
HERMES_MASTER_PW           — vault encryption password
ONEINCH_API_KEY            — swap (paid tier)
RESERVOIR_API_KEY          — NFT aggregator
ZERION_API_KEY_B64         — portfolio
BIRDEYE_API_KEY            — Solana token info
NANSEN_API_KEY             — smart money (paid)
ARKHAM_API_KEY             — smart money (free tier OK)
DUNE_API_KEY               — custom queries
RPC_EVM_<CHAIN>            — RPC per chain
WS_RPC_EVM_<CHAIN>         — websocket RPC for monitoring
RPC_SOLANA                 — Solana RPC
HERMES_TG_BOT_TOKEN        — Telegram notifier
HERMES_TG_CHAT_ID          — Telegram target
HERMES_DISCORD_WEBHOOK     — Discord notifier
```

If a deep op fires and required env var is missing → tell operator which one + where to get it, don't silently fail.
