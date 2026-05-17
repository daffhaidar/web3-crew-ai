---
name: safe-transaction-defensive-stack
description: Reference for the SafeTransactionTool defensive execution stack — the 4 honest status codes (success/reverted/pending/rejected), ETH budget cap, opt-in RBF, and RPC-error-during-receipt-poll handling. Use this when debugging a /mint result, when the user asks "why did the bot say X", or when extending the tool with a new on-chain action.
---

# SafeTransactionTool — Defensive Execution Stack

Single source of truth: `src/web3_crew/tools/safe_transaction.py`. Tests at
`tests/test_tools.py` (search for `test_status_*`, `test_rbf_*`, `test_budget_*`,
`test_receipt_*`).

## The four honest status codes

The tool **never** returns "success" for an on-chain revert or a stuck tx.
Every response has exactly one of these shapes:

| `status` | Meaning | ETH consumed? | Action surfaced |
|---|---|---|---|
| `success` | Mined AND `receipt.status == 1` (execution OK) | Yes, normal gas | `tx_hash`, `block_number`, `gas_used` |
| `reverted` | Mined BUT `receipt.status == 0` (execution failed on-chain) | **Yes, gas was burnt** | `tx_hash`, `explorer_url`, `reason` explaining the revert |
| `pending` | Broadcast OK, no receipt within `TX_WAIT_SECONDS`, or RPC errored mid-wait | Not yet, but nonce is consumed | `tx_hash`, `nonce`, `explorer_url`, instructions to manually replace/cancel |
| `rejected` | Never broadcast (audit gate, budget cap, validation failure) | **0 ETH** | `reason` only — no `tx_hash` because nothing was signed |

The fifth shape, `{"status": "error", ...}`, is reserved for pre-submit
exceptions where no tx ever hit the wire (e.g., RPC down before
`estimate_gas`). Those responses have NO `tx_hash` by definition.

## Pre-flight gates (in order)

1. **Audit gate** — caller (Tx Executor agent) only invokes the tool if
   `risk_score < MAX_RISK_SCORE`. If the gate is bypassed by tests/manual
   callers, the tool itself still runs the remaining checks.
2. **Address validity** — `Web3.is_address(to)` must be true.
3. **Contract has code** — `eth_getCode` must be non-empty; refuses to
   send to an EOA when calling a contract method.
4. **Gas estimation** — `estimate_gas` simulates the tx. A revert here
   means the tx WOULD fail on-chain → returns `rejected`, never broadcasts.
5. **Budget cap** — computes `gas_limit × max_fee_per_gas` in ETH and
   refuses if it exceeds `MAX_TX_COST_ETH` (default 0.05 ETH). The response
   includes the exact ETH ceiling and current projection so the caller can
   decide to raise the cap or wait for cheaper gas.

## Gas pricing (EIP-1559)

- Reads `eth_maxPriorityFeePerGas` and the latest block's `base_fee_per_gas`.
- Applies the `GAS_STRATEGY` multiplier (`slow=1.0x`, `standard=1.5x`,
  `fast=2.0x` default, `aggressive=3.0x`).
- Caps priority fee at `MAX_PRIORITY_FEE_GWEI` (default 5).
- Computes `max_fee_per_gas = 2 × base_fee + priority_fee` (industry-standard
  headroom for one ~12.5% base-fee bump per block).

## Receipt polling

```
wait_for_transaction_receipt(timeout=TX_WAIT_SECONDS, poll_interval=2)
```

The wait is wrapped in a `try/except` that catches **all** exceptions, not
just `TimeExhausted`. If anything goes wrong WHILE `tx_hash` already
exists (RPC 429, connection reset, DNS hiccup, JSON-RPC error), the tool
returns `pending` with `tx_hash` + `nonce` + `explorer_url` instead of
losing the hash. This was added in Phase 6 to close the
"rate-limited mid-poll → tx_hash dropped" gap.

## Opt-in Replace-By-Fee (RBF)

Disabled by default. Set `ENABLE_AUTO_RBF=true` to enable.

When enabled, a `pending` outcome triggers up to `MAX_RBF_ATTEMPTS` retries
under the **same nonce** with:

- `max_fee_per_gas = max(recomputed_cap, current_max_fee × 1.5)` —
  guarantees ≥ 50% bump, which is well above geth/nethermind's 10%
  replacement threshold.
- `max_priority_fee_per_gas = current_priority × 1.5`.
- Re-checks the budget cap on every retry. The total spend across all
  RBF attempts can never silently exceed `MAX_TX_COST_ETH`.

If the RBF `send_raw_transaction` itself throws (e.g.,
`replacement transaction underpriced`, network down), the prior `tx_hash`
is preserved in the response so the caller can still manually
replace/cancel. This is enforced by
`test_rbf_retry_send_error_preserves_prior_tx_hash`.

## Explorer URL helper

`_explorer_url(chain_id, tx_hash)` returns the canonical tx URL per chain:

| Chain ID | Explorer |
|---|---|
| 1 | etherscan.io |
| 137 | polygonscan.com |
| 8453 | basescan.org |
| 42161 | arbiscan.io |
| 10 | optimistic.etherscan.io |
| 56 | bscscan.com |

Unknown chains return `None`, which is fine — the response will simply omit
the `explorer_url` field.

## Adding a new defensive check (recipe)

1. Add the check in `_run()` **before** `send_raw_transaction`.
2. On failure, `return {"status": "rejected", "reason": "..."}` (don't raise).
3. Add a unit test asserting both the status string AND the absence of a
   `tx_hash` field in the response.
4. Update `.env.example` and `Settings` if a new tunable is introduced.

## What this skill is NOT

- A general intro to EIP-1559 (read the spec)
- A guide to manual tx replacement via Metamask (out of scope, but the
  `pending`/`reverted` response includes the explorer link the user needs)
- A Flashbots Protect deep dive (see Phase 5 changes in `crew.py` /
  settings; this skill focuses on the post-broadcast defensive layer)
