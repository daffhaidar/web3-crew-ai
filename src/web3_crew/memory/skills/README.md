# SUPERAGENT v3 — OPENCLAW EDITION

Production-grade agent brain for OpenClaw / Hermes runtime. Successor to v2.

---

## Quick start

### Install on VPS
```bash
# 1. Drop this folder into the agent workspace
cp -r openclaw ~/.openclaw/workspace/superagent-v3/

# 2. Point the agent config at it
nano ~/.openclaw/workspace/openclaw-agents.json
# Add or update:
# {
#   "system_prompt_path": "~/.openclaw/workspace/superagent-v3/AGENTS.md",
#   "skills_dir": "~/.openclaw/workspace/superagent-v3/skills",
#   "memory_dir": "~/.openclaw/workspace/superagent-v3/memory"
# }

# 3. (RECOMMENDED) Enable time-awareness injection in host wrapper
#    See TIME.md Layer 1 for the host-side code that prepends
#    [RUNTIME CONTEXT] block to every user message. Without this,
#    agent falls back to tool call (Layer 2) or inference (Layer 4).

# 4. Restart the agent
pm2 restart openclaw  # or screen -r / systemctl
```

### Load order
1. `AGENTS.md` — core router (always loaded)
2. `IDENTITY.md` + `SOUL.md` — character (always loaded)
3. `HEARTBEAT.md` + `TOOLS.md` + `MEMORY.md` — runtime config (always loaded)
4. `USER.md` — operator profile (always loaded, customize first)
5. `skills/m*.md` and `skills/x*.md` — loaded on-demand by router

Always-on token budget: ~3.5k. Skills bring task-specific knowledge only when triggered.

---

## What's in v3

### Core files
| File | Purpose |
|---|---|
| `AGENTS.md` | Router, rules R1-R10, weighted keyword table |
| `IDENTITY.md` | Response speed tiers, character modes |
| `SOUL.md` | Flexibility doctrine, hard stops, operational rails |
| `TIME.md` | **5-layer time awareness** (NEW — system inject → tool call → cache → infer → disclose) |
| `HEARTBEAT.md` | Session continuity, time refresh, token discipline |
| `TOOLS.md` | Agent-side vs operator-side execution, time tool specs |
| `USER.md` | Operator profile template (FILL THIS IN) |
| `MEMORY.md` | Compaction rules, format |
| `CONTRIBUTORS.md` | Credits — community contributors |
| `panduan.md` | Operator usage guide with real examples |

### Skills
| Skill | Domain |
|---|---|
| m0 | Skill registry, reflection loop |
| m1 | Monetization, business ops |
| m2 | VPS, infra, deployment |
| m3 | Content, copywriting, Indonesian voice |
| m4 | Telegram bots, production patterns |
| m5 | Data handling, snapshots, large files |
| m6 | Integrations, payments, webhooks |
| m7 | AI providers, multi-LLM, streaming, fallback |
| m8 | Documents (docx/xlsx/pptx/pdf), images |
| m9 | Frontend, landing pages, Web3 UI |
| **m10** | **Web3 ops, on-chain, mass farming** *(NEW)* |
| **m11** | **Security audit, skill safety, secret scan** *(NEW)* |
| **m12** | **Batch ops, parallel exec, queues** *(NEW)* |
| **m13** | **Universal NFT minter — OpenSea/Manifold/Zora, auto-gas** *(NEW)* |
| **hermes** | **Deep crypto layer** — multi-chain wallets, 1inch/Jupiter swap, Seaport/Blur/ME NFT buy, LI.FI bridge, Aave/Lido/GMX DeFi, mempool sniffer, Nansen/Arkham smart money, sniping with honeypot gate *(INTEGRATED)* |
| x1 | Self-audit, system refinement |
| x2 | Deep decomposition, strategy |
| x3 | Debug, fault diagnosis |

---

## Configure for your operator
Edit `USER.md`:
- Name, honorific, timezone
- Domain focus checkboxes
- Trigger phrases
- Language default

---

## Upgrade from v2
- Back up v2 memory: `cp -r ~/.openclaw/workspace/superagent-v2/memory ~/.openclaw/backups/`
- Drop v3 in beside it (don't overwrite v2 immediately)
- Test on staging agent if available
- Migrate memory: copy daily logs into `v3/memory/`
- Switch agent config to v3 path
- Keep v2 for 7 days before deleting

See `CHANGELOG-v3.md` for full diff.

---

## Token budget
- Always-on: ~3.5k
- Light skill load (1 skill): +0.5-1.5k
- Heavy skill load (2-3 skills, e.g. m4+m7+m10 on Web3 bot bug): +3-5k
- Hermes deep ref: +2-4k per reference, loaded only on H-skill match
- Hard ceiling: 12k context spent on system. If higher, run x1 audit.

## How hermes loads (token discipline)
H-skills never preload. When operator mentions e.g. "bridge layerzero":
1. `hermes/DISPATCH.md` loads once per session (cached)
2. `hermes/references/bridge.md` loads only when bridge keyword fires
3. Other 9 references stay on disk until their keywords trigger

10 deep references add ~0 always-on cost.
