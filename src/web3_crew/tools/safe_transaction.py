"""Tool for building, signing, and broadcasting transactions via web3.py.

Private key is loaded from .env through pydantic-settings — never hardcoded.
Transactions are gated by the audit risk score.

Gas War — EIP-1559 dynamic fees
-------------------------------
Priority fee (the tip validators see) is what wins the race for the next
block. This module:

  * reads the current block's ``baseFeePerGas``;
  * asks the chain for a suggested ``maxPriorityFeePerGas``;
  * multiplies that suggestion by a strategy factor
    (``slow`` / ``standard`` / ``fast`` / ``aggressive``);
  * caps the result with ``max_priority_fee_gwei`` so a volatile network
    cannot drain the wallet;
  * builds an EIP-1559 (``type=2``) transaction.

When ``flashbots_rpc_url`` is configured, the signed transaction is sent
through Flashbots Protect instead of the public mempool. Reads (nonce,
gas, balance, receipt) still go through the user's primary RPC.

Defensive execution
-------------------
This module distinguishes four post-submit outcomes and surfaces them
honestly to the agent (and therefore the Telegram user):

  * ``success``  — mined, ``receipt.status == 1``.
  * ``reverted`` — mined, ``receipt.status == 0``. Gas was spent.
  * ``pending``  — not mined within ``tx_wait_seconds``. Tx still alive in
                   the mempool; ``tx_hash`` + ``nonce`` + explorer link are
                   returned so the user can replace or cancel.
  * ``rejected`` — never submitted. Either the audit gate blocked it, the
                   estimated worst-case cost exceeded ``max_tx_cost_eth``,
                   or some validation failed.

When ``enable_auto_rbf`` is true and a tx becomes ``pending``, the tool
resubmits with a 1.5x-bumped priority fee under the same nonce, up to
``max_rbf_attempts`` times. Every retry is re-checked against the budget
cap so RBF can never blow past ``max_tx_cost_eth``.
"""

import json
from typing import Any

from crewai.tools import BaseTool
from web3 import Web3
from web3.exceptions import TimeExhausted
from web3.middleware import ExtraDataToPOAMiddleware

from web3_crew.config import settings

# Strategy multiplier applied to the chain's suggested priority fee.
# 'fast' is the safe default — gets you into the next block on a healthy
# network without overpaying. 'aggressive' is for contested mints / NFT drops.
STRATEGY_MULTIPLIERS: dict[str, float] = {
    "slow": 1.0,
    "standard": 1.5,
    "fast": 2.0,
    "aggressive": 3.0,
}

# Fallback when the chain doesn't expose ``eth_maxPriorityFeePerGas``.
# 2 gwei is conservative but non-zero.
DEFAULT_PRIORITY_FALLBACK_GWEI = 2

# maxFeePerGas covers up to BASE_FEE_HEADROOM * base_fee + priority.
# 2x lets the base fee spike one full block before the tx is uncovered.
BASE_FEE_HEADROOM = 2

# Multiplier applied to priority_fee on every RBF retry attempt.
# 1.5x is the de-facto minimum bump most pool operators require to evict
# the original tx and accept the replacement.
RBF_BUMP_MULTIPLIER = 1.5

# Block explorer domains per chain id. Used to render a clickable
# Etherscan-style link in pending / reverted responses so the user can
# investigate or replace the tx without copy-pasting the hash.
EXPLORER_DOMAINS: dict[int, str] = {
    1: "etherscan.io",
    11155111: "sepolia.etherscan.io",
    137: "polygonscan.com",
    8453: "basescan.org",
    42161: "arbiscan.io",
    10: "optimistic.etherscan.io",
    56: "bscscan.com",
}


def compute_eip1559_fees(
    base_fee_wei: int,
    suggested_priority_wei: int,
    strategy: str,
    max_priority_fee_gwei: int,
) -> tuple[int, int]:
    """Compute ``(maxFeePerGas, maxPriorityFeePerGas)`` in wei.

    Pure function. No chain access. Unit-testable without mocking a node.
    """
    mult = STRATEGY_MULTIPLIERS.get(strategy, STRATEGY_MULTIPLIERS["fast"])
    priority_wei = int(suggested_priority_wei * mult)
    priority_cap_wei = Web3.to_wei(max_priority_fee_gwei, "gwei")
    priority_wei = min(priority_wei, priority_cap_wei)
    max_fee_wei = base_fee_wei * BASE_FEE_HEADROOM + priority_wei
    return max_fee_wei, priority_wei


def estimate_worst_case_cost_wei(gas_limit: int, max_fee_per_gas_wei: int) -> int:
    """Worst-case wei the wallet might pay for this transaction.

    ``gas_used`` is always ``<= gas_limit`` and effective gas price is always
    ``<= max_fee_per_gas``, so the product is a true upper bound.
    """
    return gas_limit * max_fee_per_gas_wei


def explorer_tx_url(tx_hash_hex: str, chain_id: int) -> str:
    """Block-explorer URL for a tx hash on the configured chain.

    Falls back to Ethereum mainnet's Etherscan when the chain id is unknown.
    """
    domain = EXPLORER_DOMAINS.get(chain_id, "etherscan.io")
    if not tx_hash_hex.startswith("0x"):
        tx_hash_hex = "0x" + tx_hash_hex
    return f"https://{domain}/tx/{tx_hash_hex}"


def _build_submission_client(default_client: Web3) -> Web3:
    """Pick the Web3 client used to broadcast the signed tx.

    Returns a Flashbots-Protect-backed client when ``flashbots_rpc_url`` is
    set, otherwise the caller's existing client. The submission client is
    used only for ``eth_sendRawTransaction`` — everything else (nonce, gas,
    receipt polling) stays on the primary RPC.
    """
    if not settings.flashbots_rpc_url:
        return default_client
    return Web3(Web3.HTTPProvider(settings.flashbots_rpc_url))


def _scrub_private_key(message: str) -> str:
    """Defensive: never echo the configured private key back in an error.

    web3.py and the underlying signers do not normally include the PK in
    exception messages, but if a future version regresses, this hook keeps
    the leaked secret out of the agent's reply to Telegram.
    """
    pk = settings.wallet_private_key
    if pk and len(pk) >= 8 and pk in message:
        return message.replace(pk, "[REDACTED]")
    return message


class SafeTransactionTool(BaseTool):
    name: str = "safe_transaction"
    description: str = (
        "Builds, signs, and broadcasts a safe on-chain transaction. "
        "Input: a JSON string with 'action' (mint/approve/transfer), "
        "'contract_address', 'abi' (contract ABI), 'function_name', "
        "'function_args' (list), and 'risk_score' (int). "
        "Refuses to execute if risk_score >= safety threshold. "
        "Uses EIP-1559 dynamic fees with strategy-based priority bumping "
        "and (optionally) Flashbots Protect for anti-MEV submission. "
        "Honest outcome reporting: success, reverted (mined but failed), "
        "pending (stuck in mempool), or rejected (never submitted). "
        "Pre-flight budget cap on worst-case gas cost; optional RBF retry."
    )

    def _run(self, tx_request: str) -> str:
        data: dict[str, Any] = json.loads(tx_request)

        risk_score = data.get("risk_score", 100)
        if risk_score >= settings.max_risk_score:
            return json.dumps({
                "status": "rejected",
                "reason": (
                    f"Risk score {risk_score} exceeds safety threshold "
                    f"({settings.max_risk_score}). Transaction NOT executed."
                ),
            })

        placeholder = "0xYOUR_PRIVATE_KEY_HERE"
        if not settings.wallet_private_key or settings.wallet_private_key == placeholder:
            return json.dumps({
                "status": "error",
                "reason": "No wallet private key configured. Set WALLET_PRIVATE_KEY in .env",
            })

        contract_address = data.get("contract_address", "")
        abi = data.get("abi", "[]")
        function_name = data.get("function_name", "")
        function_args = data.get("function_args", [])
        value_wei = data.get("value_wei", 0)

        if not contract_address or not function_name:
            return json.dumps({
                "status": "error",
                "reason": "Missing contract_address or function_name",
            })

        try:
            w3 = Web3(Web3.HTTPProvider(settings.web3_rpc_url))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

            if not w3.is_connected():
                return json.dumps({
                    "status": "error",
                    "reason": f"Cannot connect to RPC: {settings.web3_rpc_url}",
                })

            account = w3.eth.account.from_key(settings.wallet_private_key)

            abi_parsed = json.loads(abi) if isinstance(abi, str) else abi
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=abi_parsed,
            )

            func = getattr(contract.functions, function_name)
            tx_builder = func(*function_args)

            gas_estimate = tx_builder.estimate_gas({"from": account.address})
            gas_limit = min(gas_estimate + 20_000, settings.max_gas_limit)

            latest = w3.eth.get_block("latest")
            base_fee = latest.get("baseFeePerGas")

            if base_fee is None:
                return _send_legacy(
                    w3=w3,
                    tx_builder=tx_builder,
                    account=account,
                    gas_limit=gas_limit,
                    value_wei=value_wei,
                    function_name=function_name,
                )

            try:
                suggested_priority = w3.eth.max_priority_fee
            except Exception:
                suggested_priority = Web3.to_wei(DEFAULT_PRIORITY_FALLBACK_GWEI, "gwei")

            max_fee, priority_fee = compute_eip1559_fees(
                base_fee_wei=base_fee,
                suggested_priority_wei=suggested_priority,
                strategy=settings.gas_strategy,
                max_priority_fee_gwei=settings.max_priority_fee_gwei,
            )

            budget_wei = Web3.to_wei(settings.max_tx_cost_eth, "ether")
            worst_case_wei = estimate_worst_case_cost_wei(gas_limit, max_fee)
            if worst_case_wei > budget_wei:
                return json.dumps({
                    "status": "rejected",
                    "reason": (
                        f"Estimated worst-case cost "
                        f"{Web3.from_wei(worst_case_wei, 'ether')} ETH exceeds "
                        f"MAX_TX_COST_ETH budget {settings.max_tx_cost_eth} ETH. "
                        f"Lower MAX_GAS_LIMIT / MAX_PRIORITY_FEE_GWEI or raise "
                        f"MAX_TX_COST_ETH."
                    ),
                    "gas_limit": gas_limit,
                    "max_fee_per_gas": max_fee,
                    "worst_case_cost_eth": str(Web3.from_wei(worst_case_wei, "ether")),
                    "budget_eth": settings.max_tx_cost_eth,
                })

            nonce = w3.eth.get_transaction_count(account.address)
            submit_w3 = _build_submission_client(default_client=w3)

            return _submit_with_rbf(
                w3=w3,
                submit_w3=submit_w3,
                tx_builder=tx_builder,
                account=account,
                nonce=nonce,
                gas_limit=gas_limit,
                base_fee=base_fee,
                max_fee=max_fee,
                priority_fee=priority_fee,
                value_wei=value_wei,
                function_name=function_name,
                budget_wei=budget_wei,
            )

        except Exception as e:
            return json.dumps({
                "status": "error",
                "reason": _scrub_private_key(str(e)),
            })


def _submit_with_rbf(
    *,
    w3: Web3,
    submit_w3: Web3,
    tx_builder: Any,
    account: Any,
    nonce: int,
    gas_limit: int,
    base_fee: int,
    max_fee: int,
    priority_fee: int,
    value_wei: int,
    function_name: str,
    budget_wei: int,
) -> str:
    """Submit the EIP-1559 transaction; optionally retry under RBF.

    All retries reuse ``nonce`` so on-chain they replace each other rather
    than queuing. Every iteration re-runs the worst-case budget check
    against the bumped fee — RBF can never silently push the wallet past
    ``max_tx_cost_eth``.
    """
    attempts_max = settings.max_rbf_attempts if settings.enable_auto_rbf else 0
    priority_cap_wei = Web3.to_wei(settings.max_priority_fee_gwei, "gwei")

    current_max_fee = max_fee
    current_priority = priority_fee
    last_tx_hash_hex: str | None = None

    for attempt in range(attempts_max + 1):
        worst_case_wei = estimate_worst_case_cost_wei(gas_limit, current_max_fee)
        if worst_case_wei > budget_wei:
            return _pending_response(
                last_tx_hash_hex=last_tx_hash_hex,
                nonce=nonce,
                reason=(
                    f"RBF bump would exceed MAX_TX_COST_ETH "
                    f"({settings.max_tx_cost_eth} ETH); leaving last submitted "
                    f"tx alive in the mempool."
                ),
                attempts_used=attempt,
                current_max_fee=current_max_fee,
                current_priority=current_priority,
            )

        try:
            tx = tx_builder.build_transaction({
                "from": account.address,
                "nonce": nonce,
                "gas": gas_limit,
                "maxFeePerGas": current_max_fee,
                "maxPriorityFeePerGas": current_priority,
                "value": value_wei,
                "chainId": settings.chain_id,
                "type": 2,
            })
            signed = account.sign_transaction(tx)
            tx_hash = submit_w3.eth.send_raw_transaction(signed.raw_transaction)
        except Exception as submit_err:
            # On RBF retries the prior submission is still alive in the
            # mempool — never lose its hash because the replacement failed
            # (e.g. "replacement transaction underpriced", nonce conflict,
            # node disconnect). Surface the prior tx so the user can still
            # cancel or replace it manually.
            if attempt > 0 and last_tx_hash_hex is not None:
                return _pending_response(
                    last_tx_hash_hex=last_tx_hash_hex,
                    nonce=nonce,
                    reason=(
                        f"RBF replacement attempt {attempt} failed "
                        f"({_scrub_private_key(str(submit_err))}); previously "
                        f"submitted tx is still alive in the mempool."
                    ),
                    attempts_used=attempt,
                    current_max_fee=current_max_fee,
                    current_priority=current_priority,
                )
            raise

        last_tx_hash_hex = tx_hash.hex()

        try:
            receipt = w3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=settings.tx_wait_seconds
            )
        except TimeExhausted:
            if attempt < attempts_max:
                current_priority = int(current_priority * RBF_BUMP_MULTIPLIER)
                current_priority = min(current_priority, priority_cap_wei)
                # Both maxFeePerGas AND maxPriorityFeePerGas must each rise
                # by the node's minimum replacement bump (Geth/Nethermind
                # require ~10%). baseFee dominates maxFeePerGas, so bumping
                # only priority can leave the total max_fee_per_gas under
                # the 10% threshold and the node rejects the replacement.
                # Take the max of the base-fee-recomputed cap and a direct
                # 1.5x bump of the previous max_fee.
                current_max_fee = max(
                    base_fee * BASE_FEE_HEADROOM + current_priority,
                    int(current_max_fee * RBF_BUMP_MULTIPLIER),
                )
                continue
            return _pending_response(
                last_tx_hash_hex=last_tx_hash_hex,
                nonce=nonce,
                reason=(
                    f"Transaction not mined within {settings.tx_wait_seconds}s. "
                    f"It is still alive in the mempool — replace or cancel via "
                    f"the explorer link."
                ),
                attempts_used=attempt + 1,
                current_max_fee=current_max_fee,
                current_priority=current_priority,
            )
        except Exception as wait_err:
            # Any non-timeout error from the receipt poller (HTTP 429 rate
            # limit, JSON-RPC error, connection reset, DNS hiccup, etc.).
            # The tx is ALREADY broadcast and alive in the mempool with the
            # user's funds at stake. Never collapse this into a generic
            # error — always surface the hash so the user can investigate,
            # replace, or cancel.
            return _pending_response(
                last_tx_hash_hex=last_tx_hash_hex,
                nonce=nonce,
                reason=(
                    f"RPC error while waiting for receipt "
                    f"({_scrub_private_key(str(wait_err))}); tx is broadcast "
                    f"and still alive in the mempool. Check the explorer "
                    f"link, or replace/cancel via the same nonce."
                ),
                attempts_used=attempt + 1,
                current_max_fee=current_max_fee,
                current_priority=current_priority,
            )

        return _terminal_response(
            receipt=receipt,
            function_name=function_name,
            max_fee=current_max_fee,
            priority_fee=current_priority,
            attempts_used=attempt + 1,
            fee_mode="eip1559",
        )

    # Unreachable: loop above always returns. Defensive fallback.
    return json.dumps({
        "status": "error",
        "reason": "internal: rbf loop fell through without returning",
    })


def _terminal_response(
    *,
    receipt: Any,
    function_name: str,
    max_fee: int,
    priority_fee: int,
    attempts_used: int,
    fee_mode: str,
) -> str:
    """Build the JSON response for a mined transaction.

    Honours ``receipt.status``: 1 → success, 0 → reverted on-chain (gas
    was burned). The agent — and downstream Telegram user — must never see
    ``success`` for a reverted tx; that is precisely the foot-gun this
    function exists to close.
    """
    tx_hash_hex = receipt["transactionHash"].hex()
    status_code = receipt.get("status")

    common = {
        "tx_hash": tx_hash_hex,
        "block_number": receipt["blockNumber"],
        "gas_used": receipt["gasUsed"],
        "effective_gas_price": receipt.get("effectiveGasPrice", 0),
        "max_fee_per_gas": max_fee,
        "max_priority_fee_per_gas": priority_fee,
        "gas_strategy": settings.gas_strategy,
        "via_flashbots": bool(settings.flashbots_rpc_url),
        "fee_mode": fee_mode,
        "rbf_attempts_used": attempts_used,
        "explorer_url": explorer_tx_url(tx_hash_hex, settings.chain_id),
    }

    if status_code == 0:
        return json.dumps({
            "status": "reverted",
            "reason": (
                "Transaction was mined but reverted on-chain. Gas was spent. "
                "Inspect the explorer link for the revert reason."
            ),
            **common,
        })

    return json.dumps({
        "status": "success",
        "action": function_name,
        **common,
    })


def _pending_response(
    *,
    last_tx_hash_hex: str | None,
    nonce: int,
    reason: str,
    attempts_used: int,
    current_max_fee: int,
    current_priority: int,
) -> str:
    """Build the JSON response for a tx that never mined in time."""
    payload: dict[str, Any] = {
        "status": "pending",
        "reason": reason,
        "nonce": nonce,
        "rbf_attempts_used": attempts_used,
        "max_fee_per_gas": current_max_fee,
        "max_priority_fee_per_gas": current_priority,
        "gas_strategy": settings.gas_strategy,
        "via_flashbots": bool(settings.flashbots_rpc_url),
    }
    if last_tx_hash_hex is not None:
        payload["tx_hash"] = last_tx_hash_hex
        payload["explorer_url"] = explorer_tx_url(last_tx_hash_hex, settings.chain_id)
    return json.dumps(payload)


def _send_legacy(
    *,
    w3: Web3,
    tx_builder: Any,
    account: Any,
    gas_limit: int,
    value_wei: int,
    function_name: str,
) -> str:
    """Fallback for chains without EIP-1559 (pre-London forks, some L2s).

    Uses ``gasPrice`` instead of the ``maxFeePerGas`` / ``maxPriorityFeePerGas``
    pair so the tx remains valid on those chains. Honours the same budget
    cap and reverted-receipt detection as the EIP-1559 path; RBF is not
    implemented for legacy chains.
    """
    gas_price = w3.eth.gas_price
    budget_wei = Web3.to_wei(settings.max_tx_cost_eth, "ether")
    worst_case_wei = estimate_worst_case_cost_wei(gas_limit, gas_price)
    if worst_case_wei > budget_wei:
        return json.dumps({
            "status": "rejected",
            "reason": (
                f"Estimated worst-case cost "
                f"{Web3.from_wei(worst_case_wei, 'ether')} ETH exceeds "
                f"MAX_TX_COST_ETH budget {settings.max_tx_cost_eth} ETH "
                f"(legacy gas mode)."
            ),
            "gas_limit": gas_limit,
            "gas_price": gas_price,
            "worst_case_cost_eth": str(Web3.from_wei(worst_case_wei, "ether")),
            "budget_eth": settings.max_tx_cost_eth,
            "fee_mode": "legacy",
        })

    nonce = w3.eth.get_transaction_count(account.address)
    tx = tx_builder.build_transaction({
        "from": account.address,
        "nonce": nonce,
        "gas": gas_limit,
        "gasPrice": gas_price,
        "value": value_wei,
        "chainId": settings.chain_id,
    })
    signed = account.sign_transaction(tx)
    submit_w3 = _build_submission_client(default_client=w3)
    tx_hash = submit_w3.eth.send_raw_transaction(signed.raw_transaction)

    try:
        receipt = w3.eth.wait_for_transaction_receipt(
            tx_hash, timeout=settings.tx_wait_seconds
        )
    except TimeExhausted:
        return _pending_response(
            last_tx_hash_hex=tx_hash.hex(),
            nonce=nonce,
            reason=(
                f"Transaction not mined within {settings.tx_wait_seconds}s. "
                f"It is still alive in the mempool — replace or cancel via "
                f"the explorer link. (RBF auto-retry is not available on "
                f"legacy-gas chains.)"
            ),
            attempts_used=1,
            current_max_fee=gas_price,
            current_priority=0,
        )
    except Exception as wait_err:
        # RPC rate limit / connection error while polling for the receipt.
        # The tx is already broadcast; surface its hash so the user can
        # investigate, replace, or cancel.
        return _pending_response(
            last_tx_hash_hex=tx_hash.hex(),
            nonce=nonce,
            reason=(
                f"RPC error while waiting for receipt "
                f"({_scrub_private_key(str(wait_err))}); tx is broadcast "
                f"and still alive in the mempool (legacy-gas chain). Check "
                f"the explorer link or replace/cancel via the same nonce."
            ),
            attempts_used=1,
            current_max_fee=gas_price,
            current_priority=0,
        )

    return _terminal_response(
        receipt=receipt,
        function_name=function_name,
        max_fee=gas_price,
        priority_fee=0,
        attempts_used=1,
        fee_mode="legacy",
    )
