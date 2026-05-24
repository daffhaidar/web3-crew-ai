---
name: safe-transaction-defensive-stack
description: Reference for the SafeTransactionTool defensive execution stack — the Blind Execution / Generic ABI fallback, the 4 honest status codes (success/reverted/pending/rejected), ETH budget cap, opt-in RBF, and RPC-error-during-receipt-poll handling. Use this when debugging a /mint result, when the user asks "why did the bot say X", or when extending the tool with a new on-chain action.
---

# SafeTransactionTool — Defensive Execution Stack

Single source of truth: `src/web3_crew/tools/safe_transaction.py` plus the
hardcoded fallbacks in `src/web3_crew/tools/abi_constants.py`. Tests live
at `tests/test_abi_constants.py` and `tests/test_safe_transaction_blind_exec.py`.

## ABI handling — Blind Execution (the LLM never sees raw ABI)

The tool **does not accept an `abi` field in its input**. Passing one is
silently dropped with a warning log. ABI resolution stays inside Python
and picks one of three modes:

| Mode | Trigger | Source | Returned `abi_source` |
|---|---|---|---|
| Etherscan smart parse | `function_name` set + contract verified + function on-chain | Etherscan V2 `getabi`, then `find_function_entry` keeps only the one entry needed | `etherscan_parsed` |
| Generic ERC-721/ERC-20 | Unverified contract OR Etherscan miss, BUT `function_name` matches a hardcoded fallback (`mint`/`publicMint`/`safeMint` or `transfer`/`approve`/`transferFrom`) | `GENERIC_ERC721_ABI` / `GENERIC_ERC20_ABI` in `abi_constants.py` | `generic_erc721` / `generic_erc20` |
| Blind calldata | Caller sets `action='raw'` AND supplies `raw_calldata` (0x-prefixed hex with ≥ 4 byte selector) | No ABI lookup at all — bytes go on the wire as-is | `raw_calldata` |

If none of the three apply (unknown function, no `raw_calldata`), the
response is `{"status": "rejected", "reason": "...", "abi_source": "no_match"}`.

The tool's response **always** carries `abi_source` and `function_signature`
(a one-line Solidity-style string) so the agent can verify what actually
ran, but **never** the raw ABI JSON. This is the bug-fix that closes the
8 K context OOM on `cerebras/gpt-oss-120b`.

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

## Adding a new generic ABI fallback (recipe)

Do this when a new EVM standard (e.g. ERC-1155 batchMint) becomes common
enough that we want bullet-proof blind execution for it.

1. Append the minimal entry — name, inputs, outputs, stateMutability — to
   `GENERIC_ERC1155_ABI` (or whichever constant) in
   `src/web3_crew/tools/abi_constants.py`. Keep entries **small**: only
   the functions the executor will actually call.
2. Add the names to a new frozenset (`ERC1155_MINT_FUNCTIONS`) and update
   `_pick_generic_abi_for` in `safe_transaction.py` to route the new
   function names to it.
3. Add a test in `tests/test_abi_constants.py` asserting the new entry
   exists and the frozenset matches the ABI surface.
4. Add a test in `tests/test_safe_transaction_blind_exec.py::TestPickGenericAbi`
   covering the new routing.
5. **Never** put rug-pull-shaped functions in a generic ABI (e.g. mint on
   ERC-20, `setFee`, `blacklist`, unlimited approve). Those entries
   would short-circuit the auditor's static analysis.
4. Update `.env.example` and `Settings` if a new tunable is introduced.

## What this skill is NOT

- A general intro to EIP-1559 (read the spec)
- A guide to manual tx replacement via Metamask (out of scope, but the
  `pending`/`reverted` response includes the explorer link the user needs)
- A Flashbots Protect deep dive (see Phase 5 changes in `crew.py` /
  settings; this skill focuses on the post-broadcast defensive layer)
