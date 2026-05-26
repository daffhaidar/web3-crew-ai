import re
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel
from web3 import Web3

# Public Ethereum RPC endpoints (tried in order)
_RPC_URLS = [
    "https://rpc.ankr.com/eth",
    "https://cloudflare-eth.com",
]


class EVMBalanceInput(BaseModel):
    """Input schema for EVMBalanceCheckerTool."""
    wallet_address: str


class EVMBalanceCheckerTool(BaseTool):
    """
    A tool that checks the balance of an EVM wallet address.

    Connects to a public Ethereum RPC to fetch the real on-chain ETH balance.
    """

    name: str = "EVM Balance Checker"
    description: str = (
        "Checks the ETH balance of a given EVM wallet address. "
        "Returns the live on-chain balance in ETH."
    )
    args_schema: Type[BaseModel] = EVMBalanceInput

    def _run(self, wallet_address: str) -> str:
        """
        Execute the balance check.

        Args:
            wallet_address: The EVM wallet address to check.

        Returns:
            A string containing the balance information or an error message.
        """
        if not self._is_valid_evm_address(wallet_address):
            return (
                f"Error: '{wallet_address}' bukan alamat EVM yang valid. "
                "Format yang benar: 0x diikuti 40 karakter heksadesimal."
            )

        last_error: str | None = None
        for rpc_url in _RPC_URLS:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
                if not w3.is_connected():
                    last_error = f"Tidak dapat terhubung ke RPC {rpc_url}"
                    continue

                balance_wei = w3.eth.get_balance(
                    Web3.to_checksum_address(wallet_address)
                )
                balance_eth = w3.from_wei(balance_wei, "ether")
                balance_rounded = round(float(balance_eth), 4)

                return (
                    f"Saldo untuk address {wallet_address} adalah "
                    f"{balance_rounded} ETH"
                )

            except Exception as exc:
                last_error = f"Gagal mengambil saldo dari {rpc_url}: {exc}"
                continue

        return (
            f"Error: Gagal mengambil saldo untuk {wallet_address}. "
            f"Semua RPC endpoint tidak tersedia. Detail terakhir: {last_error}"
        )

    @staticmethod
    def _is_valid_evm_address(address: str) -> bool:
        """
        Validate if the given string is a valid EVM address.

        Args:
            address: The string to validate.

        Returns:
            True if the address matches the EVM format (0x + 40 hex chars).
        """
        pattern = r"^0x[0-9a-fA-F]{40}$"
        return bool(re.match(pattern, address))
