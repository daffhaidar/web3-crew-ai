"""SybilManagerTool — manage a squad of burner wallets from one commander.

Actions:
  • check  — report ETH balances for all 4 burners.
  • fund   — send `fund_amount_eth` from the commander wallet to every burner.
"""

from __future__ import annotations

import os

from crewai.tools import tool
from web3 import Web3
from web3.exceptions import TransactionNotFound

_BURNER_KEYS = [
    os.getenv("PRIV_KEY_1", ""),
    os.getenv("PRIV_KEY_2", ""),
    os.getenv("PRIV_KEY_3", ""),
    os.getenv("PRIV_KEY_4", ""),
]


def _get_w3() -> Web3:
    rpc_url = os.getenv("RPC_URL", "https://eth.llamarpc.com")
    return Web3(Web3.HTTPProvider(rpc_url))


def _address_from_key(w3: Web3, key: str) -> str:
    return w3.eth.account.from_key(key).address


@tool("Sybil Wallet Manager")
def manage_sybil_wallets(action: str, fund_amount_eth: float = 0.0) -> str:
    """Manage a squad of sybil (burner) wallets.

    Args:
        action: 'check' to list balances, 'fund' to distribute ETH from the commander.
        fund_amount_eth: Amount of ETH to send to each burner (used with 'fund').
    """
    w3 = _get_w3()

    # Gather burner addresses
    burners: list[tuple[str, str]] = []  # (label, address)
    for idx, key in enumerate(_BURNER_KEYS, start=1):
        if not key:
            continue
        addr = _address_from_key(w3, key)
        burners.append((f"Burner-{idx}", addr))

    if not burners:
        return "⚠️ No burner keys found in environment (PRIV_KEY_1 … PRIV_KEY_4)."

    # ── CHECK ────────────────────────────────────────────────────────────
    if action == "check":
        lines: list[str] = ["📋 SYBIL WALLET STATUS", "=" * 42]
        for label, addr in burners:
            balance_wei = w3.eth.get_balance(addr)
            balance_eth = w3.from_wei(balance_wei, "ether")
            lines.append(f"  {label}  {addr}")
            lines.append(f"    Balance : {balance_eth:.6f} ETH")
        lines.append("=" * 42)
        lines.append(f"  Total burners scanned: {len(burners)}")
        return "\n".join(lines)

    # ── FUND ─────────────────────────────────────────────────────────────
    if action == "fund":
        commander_key = os.getenv("WALLET_PRIVATE_KEY", "")
        if not commander_key:
            return "❌ WALLET_PRIVATE_KEY not set — cannot fund burners without a commander."

        commander_addr = _address_from_key(w3, commander_key)
        commander_balance = w3.from_wei(w3.eth.get_balance(commander_addr), "ether")

        if fund_amount_eth <= 0:
            return "❌ fund_amount_eth must be greater than 0."

        total_cost = fund_amount_eth * len(burners)
        if commander_balance < total_cost:
            return (
                f"❌ Commander balance insufficient.\n"
                f"   Commander : {commander_addr}\n"
                f"   Balance   : {commander_balance:.6f} ETH\n"
                f"   Required  : {total_cost:.6f} ETH ({fund_amount_eth} × {len(burners)})"
            )

        lines = [
            f"🚀 FUNDING OPERATION — sending {fund_amount_eth} ETH to each burner",
            f"   Commander: {commander_addr}  (balance: {commander_balance:.6f} ETH)",
            "=" * 58,
        ]

        value_wei = w3.to_wei(fund_amount_eth, "ether")
        nonce = w3.eth.get_transaction_count(commander_addr)

        for label, burner_addr in burners:
            try:
                tx = {
                    "from": commander_addr,
                    "to": burner_addr,
                    "value": value_wei,
                    "nonce": nonce,
                    "gas": 21_000,
                    "maxFeePerGas": w3.eth.gas_price * 2,
                    "maxPriorityFeePerGas": w3.to_wei(1, "gwei"),
                }
                signed = w3.eth.account.sign_transaction(tx, commander_key)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                if receipt.status == 1:
                    lines.append(f"  ✅ {label}  →  {burner_addr}  |  tx: {tx_hash.hex()}")
                else:
                    lines.append(f"  ⚠️ {label}  →  {burner_addr}  |  tx reverted: {tx_hash.hex()}")
                nonce += 1
            except Exception as exc:
                lines.append(f"  ❌ {label}  →  {burner_addr}  |  error: {exc}")

        new_balance = w3.from_wei(w3.eth.get_balance(commander_addr), "ether")
        lines.append("=" * 58)
        lines.append(f"   Commander remaining balance: {new_balance:.6f} ETH")
        lines.append("🏁 Funding operation complete.")
        return "\n".join(lines)

    return f"⚠️ Unknown action '{action}'. Use 'check' or 'fund'."
