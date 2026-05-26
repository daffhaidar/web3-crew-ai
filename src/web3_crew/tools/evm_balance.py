import re
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel


class EVMBalanceInput(BaseModel):
    """Input schema for EVMBalanceCheckerTool."""
    wallet_address: str


class EVMBalanceCheckerTool(BaseTool):
    """
    A tool that checks the balance of an EVM wallet address.

    Validates the address format and returns a simulated balance response.
    """

    name: str = "EVM Balance Checker"
    description: str = (
        "Checks the ETH balance of a given EVM wallet address. "
        "Returns a simulated balance in ETH."
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

        return f"Saldo untuk address {wallet_address} adalah 0.0 ETH (Simulasi)"

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
