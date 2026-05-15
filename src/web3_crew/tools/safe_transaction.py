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
"""

import json
from typing import Any

from crewai.tools import BaseTool
from web3 import Web3
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
        "and (optionally) Flashbots Protect for anti-MEV submission."
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

            tx = tx_builder.build_transaction({
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address),
                "gas": gas_limit,
                "maxFeePerGas": max_fee,
                "maxPriorityFeePerGas": priority_fee,
                "value": value_wei,
                "chainId": settings.chain_id,
                "type": 2,
            })

            signed = account.sign_transaction(tx)

            submit_w3 = _build_submission_client(default_client=w3)
            tx_hash = submit_w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "success",
                "action": function_name,
                "tx_hash": receipt["transactionHash"].hex(),
                "block_number": receipt["blockNumber"],
                "gas_used": receipt["gasUsed"],
                "effective_gas_price": receipt.get("effectiveGasPrice", 0),
                "max_fee_per_gas": max_fee,
                "max_priority_fee_per_gas": priority_fee,
                "gas_strategy": settings.gas_strategy,
                "via_flashbots": bool(settings.flashbots_rpc_url),
                "fee_mode": "eip1559",
            })

        except Exception as e:
            return json.dumps({
                "status": "error",
                "reason": _scrub_private_key(str(e)),
            })


def _send_legacy(
    *,
    w3: Web3,
    tx_builder: Any,
    account: Any,
    gas_limit: int,
    value_wei: int,
) -> str:
    """Fallback for chains without EIP-1559 (pre-London forks, some L2s).

    Uses ``gasPrice`` instead of the ``maxFeePerGas`` / ``maxPriorityFeePerGas``
    pair so the tx remains valid on those chains.
    """
    tx = tx_builder.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": gas_limit,
        "gasPrice": w3.eth.gas_price,
        "value": value_wei,
        "chainId": settings.chain_id,
    })
    signed = account.sign_transaction(tx)
    submit_w3 = _build_submission_client(default_client=w3)
    tx_hash = submit_w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    return json.dumps({
        "status": "success",
        "tx_hash": receipt["transactionHash"].hex(),
        "block_number": receipt["blockNumber"],
        "gas_used": receipt["gasUsed"],
        "effective_gas_price": receipt.get("effectiveGasPrice", 0),
        "fee_mode": "legacy",
        "via_flashbots": bool(settings.flashbots_rpc_url),
    })
