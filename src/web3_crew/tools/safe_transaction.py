"""Tool for building, signing, and broadcasting transactions via web3.py.

Private key is loaded from .env through pydantic-settings — never hardcoded.
Transactions are gated by the audit risk score.
"""

import json
from typing import Any

from crewai.tools import BaseTool
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from web3_crew.config import settings


class SafeTransactionTool(BaseTool):
    name: str = "safe_transaction"
    description: str = (
        "Builds, signs, and broadcasts a safe on-chain transaction. "
        "Input: a JSON string with 'action' (mint/approve/transfer), "
        "'contract_address', 'abi' (contract ABI), 'function_name', "
        "'function_args' (list), and 'risk_score' (int). "
        "Refuses to execute if risk_score >= safety threshold."
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

            tx = tx_builder.build_transaction({
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address),
                "gas": gas_limit,
                "gasPrice": w3.eth.gas_price,
                "value": value_wei,
                "chainId": settings.chain_id,
            })

            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "success",
                "action": function_name,
                "tx_hash": receipt["transactionHash"].hex(),
                "block_number": receipt["blockNumber"],
                "gas_used": receipt["gasUsed"],
                "effective_gas_price": receipt.get("effectiveGasPrice", 0),
            })

        except Exception as e:
            return json.dumps({
                "status": "error",
                "reason": str(e),
            })
