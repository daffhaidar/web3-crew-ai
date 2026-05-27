# Panduan Operator — Hermes + SUPERAGENT v3

Cara ngomong sama Hermes setelah v3 OPENCLAW EDITION + hermes-crypto-agent ke-combo.

---

## Daftar Isi

1. [Mode default vs mode cepat](#mode-default-vs-mode-cepat)
2. [Mint NFT](#mint-nft)
3. [Swap token](#swap-token)
4. [Bridge cross-chain](#bridge-cross-chain)
5. [Sniping token launch](#sniping-token-launch)
6. [Airdrop farming multi-wallet](#airdrop-farming-multi-wallet)
7. [Mempool watch (anti-drainer)](#mempool-watch-anti-drainer)
8. [Beli NFT di marketplace](#beli-nft-di-marketplace)
9. [Whale & smart-money tracker](#whale--smart-money-tracker)
10. [Session control commands](#session-control-commands)
11. [Background job persistence](#background-job-persistence)
12. [Cheat sheet — natural language ke skill route](#cheat-sheet--natural-language-ke-skill-route)

---

## Mode default vs mode cepat

Hermes punya 2 mode operasi. Default = aman, mode cepat = fire and forget.

### Default — confirm before signing
Tiap tx penting dapat plan ringkas + gate `(y/n)`. Cocok buat:
- Tx pertama di sesi baru
- Wallet utama / dana besar
- Operasi yang belum pernah Kakak lakuin sebelumnya
- Kontrak yang belum diaudit

### Mode cepat — `auto_confirm on`
Skip prompt per tx. Tx pertama tetap dapat 1-line summary (info only, bukan gate). Cocok buat:
- Batch ops (mass mint, multi-wallet farming)
- Wallet kecil / test wallet
- Operasi rutin yang udah biasa
- Sniping di mana speed penting

```
Kakak: auto_confirm on
Hermes: [AUTO_CONFIRM] ON. tx akan fire tanpa gate sampai sesi ini berakhir atau lo set off.

Kakak: auto_confirm off
Hermes: [AUTO_CONFIRM] OFF. balik ke mode safe.
```

Operational rails yang TETAP nyala walau auto_confirm on:
- Secret hygiene (gak pernah log priv key)
- Simulate before broadcast
- Drainer/scam code detection
- User-funds-only

---

## Mint NFT

### Single mint dari URL
```
Kakak: mint NFT https://opensea.io/assets/base/0xABC.../1
```

Hermes auto:
- Parse URL → chain `base`, contract `0xABC...`
- Probe mint function (publicMint, mint, claim, dst)
- Detect price via `mintPrice()` / Seadrop config
- Auto-gas (estimate + buffer)
- Simulate → send → wait → report

Output:
```
[TARGET] 0xABC... on base × 1
[FN]     mintPublic(uint256) — detected
[PRICE]  0.0014 ETH
[GAS]    180k @ 0.05 gwei  →  ~$0.02
[SENT]   0xtxhash...
[OK]     block 12345678  gasUsed 142,330
[VIEW]   https://basescan.org/tx/0xtxhash...
```

### Mass mint pakai N wallet
```
Kakak: auto_confirm on. mint https://opensea.io/assets/base/0xABC.../1 pakai 50 wallet
```

Output:
```
[BATCH MINT] 50 wallets × NFT 0xABC... on base
est total cost: 0.0070 ETH (50 × 0.0001 mint fee)
concurrency: 5
[SENDING]

[3/50]   0xAbC...d4F1   ✅ 0xtx1...
[7/50]   0xDeF...c2A3   ✅ 0xtx2...
[12/50]  0x123...8F9    ❌ AlreadyMinted
...
[DONE]   47/50 ok, 3 failed → mint-1748150400.json
```

### Mint Manifold / Zora
Sama, paste URL langsung:
```
Kakak: mint https://app.manifold.xyz/c/12345
Kakak: mint https://zora.co/collect/base:0xABC.../1
```

Hermes pakai protocol-specific handler (Manifold instanceId fetch, Zora 1155 protocol fee).

---

## Swap token

### Swap simple
```
Kakak: swap 0.5 ETH ke USDC di base, pakai wallet pertama
```

Plan:
```
[PLAN]
chain:    base
wallet:   0xAbC...d4F1 (wallet#1)
action:   swap 0.5 ETH → USDC (via 1inch)
slippage: 1%
est out:  ~1,847 USDC
gas:      ~$0.02

Lanjut? (y/n)
```

`y` → fire. Tx hash + explorer link.

### Sell semua holding token
```
Kakak: sell semua $PEPE di wallet#1, ke USDC
```

Hermes:
- Cek balance PEPE di wallet
- Quote via 1inch
- Tampilkan plan
- Execute (kalau approve belum ada, approve dulu otomatis)

### Swap via DEX aggregator pilihan
```
Kakak: swap 1000 USDC ke ETH di arbitrum via jupiter
```
(Jupiter buat Solana. Untuk EVM, default 1inch — Hermes auto-koreksi.)

---

## Bridge cross-chain

### Bridge simple
```
Kakak: bridge 500 USDC dari arbitrum ke base pakai stargate
```

Plan:
```
[BRIDGE PLAN]
from:    arbitrum  → 500 USDC
to:      base      → 499.32 USDC (after fees)
route:   Stargate V2
fee:     0.68 USDC
eta:     ~2 menit
gas:     ~$0.30
bonus:   eligible LayerZero points

Lanjut? (y/n)
```

`y` → execute → wait sampai landed di destination chain → confirm.

### Bridge dengan route otomatis (LI.FI)
```
Kakak: bridge 0.1 ETH dari eth ke base, route paling murah
```

Hermes pakai LI.FI aggregator, pilih route optimal otomatis (Across / Stargate / native / Hop — mana yang termurah).

### Bridge ke non-EVM (Solana via Mayan)
```
Kakak: bridge 100 USDC dari base ke solana
```

Hermes pakai Wormhole + Mayan untuk EVM ↔ Solana. Wallet Solana harus udah ke-import di vault.

---

## Sniping token launch

### Setup sniper
```
Kakak: snipe token baru di base, budget 0.05 ETH per launch, max 3 launch hari ini
```

Output:
```
[SNIPER ACTIVE] base / Uniswap V3 PairCreated
filter:   WETH pair only
budget:   0.05 ETH / launch
max:      3 launches today
safety:   honeypot.is + GoPlus required
wallet:   0xAbC...d4F1
[LISTENING...]

pm2: sniper-base (id 2)
log: pm2 logs sniper-base
```

Saat pair baru terdeteksi:
```
[DETECTED] 0xNew...Token, paired with WETH at block 12345678
[SAFETY]   honeypot.is: clean | GoPlus: 1 warning (mintable)
⚠️ mintable token (owner bisa inflate supply). Lanjut snipe? (y/n)
```

`auto_confirm on` → auto-block kalau CRITICAL flag, auto-proceed kalau cuma WARN.
`auto_confirm off` → tanya per detection.

### Snipe NFT mint launch
```
Kakak: snipe mint NFT collection https://opensea.io/collection/<slug>, watch dari sekarang sampai mint open
```

Hermes pantau status drop (read `getPublicDrop()` Seadrop config), fire mint detik mint window buka.

### Stop sniper
```
Kakak: stop sniper-base
```

---

## Airdrop farming multi-wallet

### LayerZero farming
```
Kakak: layerzero farming, 50 wallet, bridge variasi route 5 chain selama 7 hari
```

Sybil reminder (sekali per session):
```
⚠️ LayerZero punya deteksi sybil bisa blacklist semua wallet terkait.
Gua randomize timing (5-180 menit) + amount jitter (±15%) + variasi bridge per wallet.
Tetap ada risk. Lanjut? (y/n)
```

`y`:
```
[FARMING PLAN]
wallets:   50
chains:    eth, arb, base, op, polygon (5 chains)
tx/wallet: 14-21 (random)
duration:  7 days
total tx:  ~875 (estimasi)
est cost:  ~$45 total gas

[STARTED] background runner: pm2 lz-farming
[CHECK]   pm2 logs lz-farming
[STOP]    "stop lz-farming"
```

### zkSync / Linea farming pattern sama
```
Kakak: zksync farming, 30 wallet, daily activity selama 14 hari
Kakak: linea voyage tasks pakai 25 wallet
```

### Daily check-in airdrop
```
Kakak: daily check-in airdrop X pakai semua wallet, jam 8 pagi WIB
```

Hermes setup cron job, jalan otomatis tiap hari.

---

## Mempool watch (anti-drainer)

### Setup watcher
```
Kakak: pantau wallet gua 0xAbC...d4F1 dari approve mencurigakan, alert ke TG
```

Output:
```
[WATCHER ACTIVE]
target:   0xAbC...d4F1
chains:   ethereum, base, arbitrum
triggers: approve(), setApprovalForAll(), permit()
alert:    @setya_alerts channel
filter:   spender harus contract verified, kalau gak → CRITICAL

running as pm2: anti-drainer (id 3)
```

Saat detect approval mencurigakan di mempool (sebelum confirmed):
```
🚨 CRITICAL APPROVAL DETECTED 🚨
wallet:   0xAbC...d4F1
action:   setApprovalForAll(0xSpender..., true)
spender:  0xSus...Address (no verified contract)
tx:       0xpending...

STATUS: pending in mempool (~12s before confirm)
ACTION: kalau ini bukan elo, kirim front-run tx revoke SEKARANG
        "revoke approval 0xSus... di wallet#1"
```

### Auto-revoke mode
```
Kakak: anti-drainer auto-revoke mode on untuk wallet#1
```

Kalau Hermes detect approval ke contract non-whitelist → otomatis broadcast revoke tx dengan gas lebih tinggi, race-condition dengan drainer.

---

## Beli NFT di marketplace

### OpenSea specific listing
```
Kakak: beli BAYC #1234 di opensea, max 25 ETH
```

Plan:
```
[LISTING FOUND]
collection: BAYC
token id:   #1234
price:      22.5 ETH (di bawah max)
seller:     0xSeller...
protocol:   Seaport 1.6
gas:        ~$8

Lanjut? (y/n)
```

### Floor sweep
```
Kakak: sweep floor Pudgy Penguins, 5 unit, max avg 10 ETH per piece
```

Hermes pakai Reservoir aggregator (cek listing terendah cross-marketplace: OpenSea, Blur, LooksRare). Bulk fulfill dalam 1 tx kalau bisa.

### List NFT buat dijual
```
Kakak: list NFT #5678 dari koleksi 0xMy... di opensea, harga 1.5 ETH, expire 7 hari
```

Hermes sign EIP-712 Seaport order → post ke OpenSea API. Listing live di marketplace.

### Magic Eden / Tensor (Solana)
```
Kakak: beli SMB #1234 di magic eden, max 50 SOL
```

Sama flow-nya, beda protocol (Magic Eden ME instruction, bukan Seaport).

---

## Whale & smart-money tracker

### Track wallet whale + alert TG
```
Kakak: tracker smart money via nansen, alert ke TG kalau ada buy > $50k
```

Output:
```
[TRACKER ACTIVE]
source:   Nansen Smart Money label
filter:   buy size > $50k
chains:   ethereum, base, arbitrum, solana
alert:    @setya_alerts

pm2: smart-money-watch (id 4)
```

Alert format:
```
🐋 SMART MONEY BUY
wallet:   0xWhale... (Nansen: "Smart Trader")
action:   bought 12.5 ETH worth of $TOKEN
chain:    base
contract: 0xToken...
tx:       https://basescan.org/tx/...
```

### Copy-trade pattern
```
Kakak: copy-trade wallet 0xWhale..., ukuran 5% dari ukuran mereka, max $500 per trade
```

Hermes monitor whale wallet → mirror buy ukuran kecil di wallet Kakak, filter stablecoin transfer dan low-value noise.

### NFT whale alert
```
Kakak: alert kalau ada whale beli NFT > 10 ETH di koleksi blue chip
```

Hermes pakai Reservoir WebSocket stream — push notif real-time.

### Floor drop alert
```
Kakak: alert kalau floor BAYC drop > 5% dalam 1 jam
```

---

## Session control commands

Cukup ngomong langsung ke Hermes, gak perlu syntax khusus:

| Command | Effect |
|---|---|
| `auto_confirm on` | Mode cepat — skip per-tx gate |
| `auto_confirm off` | Mode safe (default) |
| `status` | Liat semua background job aktif |
| `stop <jobname>` | Matikan background job (sniper, farming, watcher) |
| `resume <jobname>` | Lanjut job yang ke-pause |
| `audit` | Trigger x1 — system self-check |
| `debug` | Trigger x3 — kalau ada error/bug |
| `upgrade brain` | Trigger x1 deep review (analisa skill coverage, gap, redundancy) |
| `dry-run on` | Semua tx jadi simulate-only, gak broadcast (buat testing) |
| `dry-run off` | Kembali ke broadcast mode |
| `wallet list` | Liat semua wallet di vault |
| `balance <wallet>` | Liat balance multi-chain wallet |
| `revoke approval <spender> di <wallet>` | Revoke ERC-20/721 approval |

### Per-wallet alias
```
Kakak: rename wallet 0xAbC...d4F1 jadi "farming-base-1"
Kakak: swap 100 USDC pakai farming-base-1
```

Hermes pakai alias mulai sesi berikutnya.

---

## Background job persistence

Sniper, farming, watcher — semua jalan background via pm2. Survive reboot kalau pakai systemd.

### Liat job aktif
```bash
pm2 ls
```

Sample output:
```
┌─────┬────────────────────┬─────────────┬──────┬─────────┐
│ id  │ name               │ status      │ cpu  │ memory  │
├─────┼────────────────────┼─────────────┼──────┼─────────┤
│ 0   │ hermes (main)      │ online      │ 2%   │ 142 MB  │
│ 1   │ lz-farming         │ online      │ 0.5% │ 48 MB   │
│ 2   │ sniper-base        │ online      │ 1%   │ 36 MB   │
│ 3   │ anti-drainer       │ online      │ 0.3% │ 22 MB   │
│ 4   │ smart-money-watch  │ online      │ 0.4% │ 28 MB   │
└─────┴────────────────────┴─────────────┴──────┴─────────┘
```

### Log per job
```bash
pm2 logs sniper-base --lines 50
pm2 logs lz-farming -f          # follow real-time
```

### Restart / stop
```bash
pm2 restart sniper-base
pm2 stop lz-farming
pm2 delete anti-drainer         # hapus dari list
```

### Auto-start saat VPS reboot
```bash
pm2 save                        # save current state
pm2 startup systemd             # generate systemd unit
# follow instruksi yang muncul
```

---

## Cheat sheet — natural language ke skill route

Tabel cepat: Kakak ngomong apa → skill apa yang fire.

| Kakak ngomong | Route | File yang load |
|---|---|---|
| "mint NFT [URL]" | m13 | `skills/m13.md` |
| "mass mint pakai N wallet" | m13 + m12 + m10 | mint + batch + Web3 |
| "swap X ke Y di [chain]" | H1 | `hermes/references/swap.md` |
| "jual semua $TOKEN" | H1 | swap.md |
| "bridge dari A ke B" | H2 | `hermes/references/bridge.md` |
| "stake ETH di lido" | H3 | `hermes/references/defi.md` |
| "supply USDC ke aave" | H3 | defi.md |
| "open long ETH di GMX" | H3 | defi.md (perp section) |
| "snipe token baru di [chain]" | H4 + m10 | sniping.md + Web3 |
| "snipe mint NFT [URL]" | H4 + m13 | sniping + minter |
| "pantau wallet [addr]" | H5 | `hermes/references/monitoring.md` |
| "alert kalau whale beli > $X" | H5 + m4 | monitoring + TG bot |
| "mempool watch [wallet]" | H5 | monitoring (sniffer section) |
| "tracker smart money" | H5 | monitoring (Nansen/Arkham) |
| "beli NFT [token] di [marketplace]" | H6 | `hermes/references/nft.md` |
| "list NFT gua dijual" | H6 | nft.md |
| "floor sweep [collection]" | H6 | nft.md (Reservoir) |
| "sign in dApp pakai SIWE" | H7 | `hermes/references/web3_connect.md` |
| "resolve ENS [name].eth" | H7 | web3_connect.md |
| "layerzero farming N wallet" | H2 + H1 + m12 | bridge + swap + batch |
| "zksync / linea farming" | H2 + H1 + m12 | sama pattern |
| "buat wallet baru di [chain]" | m10 / hermes/wallets.md | tergantung chain |
| "import wallet dari seed" | hermes/wallets.md | (security strict mode) |
| "audit kontrak [addr]" | m11 | `skills/m11.md` |
| "kenapa bot gua duplikat" | x3 + m4 | debug + telegram |
| "deploy ke VPS" | m2 | `skills/m2.md` |
| "buat landing page web3" | m9 + m10 | frontend + Web3 connect |

---

## Yang perlu Kakak siapin sebelum mulai

1. **VPS akses** — ✅ udah punya `root@vmi3159875`
2. **Master password vault** — buat sekarang, minimum 16 char, simpan di password manager
3. **RPC primary + fallback per chain** — minimum 2 endpoint per chain (rotating biar gak rate-limit). Recommended: Alchemy / Infura / QuickNode + 1 public RPC sebagai fallback
4. **Test wallet kecil dulu** — generate wallet baru via Hermes, isi $20-50 buat smoke test, jangan langsung pakai wallet utama
5. **Telegram bot baru buat alert** — bikin via @BotFather, taro token-nya di `HERMES_TG_BOT_TOKEN`. Jangan pakai bot yang sama dengan channel publik Kakak
6. **API key opsional** — skip dulu kalau belum, Hermes auto-fallback:
   - 1inch (swap): free tier OK
   - Reservoir (NFT): free tier OK
   - Nansen (smart money): paid, paling akurat — opsional
   - Arkham: free tier OK
   - Zerion / Birdeye (portfolio): free tier OK

Setelah 6 hal ini ready → Hermes bisa langsung run. Mau gua bikin **bootstrap script** otomatis (install + env setup + first wallet gen + smoke test), atau Kakak prefer setup manual step-by-step?

---

## Cara cepat verify v3 + hermes udah jalan

Setelah install + restart, cek 4 hal:

```bash
# 1. Agent boot tanpa error
pm2 logs hermes --lines 20
# harus muncul: [BOOT] v3 OPENCLAW EDITION loaded

# 2. Env var ke-load
env | grep -E "HERMES_|RPC_|ARKHAM_" | head -10

# 3. Skill ke-baca
ls ~/.openclaw/workspace/openclaw/skills/
# harus liat: m0-m13, x1-x3, hermes/

# 4. Test dispatch — ketik di Telegram bot
"audit"
# Hermes harus respond dengan x1 self-check output
```

Kalau 4 hal di atas ✅, Hermes siap eksekusi.
