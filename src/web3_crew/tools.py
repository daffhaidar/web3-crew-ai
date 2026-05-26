import re

from crewai.tools import BaseTool


class EVMBalanceCheckerTool(BaseTool):
    """
    Custom CrewAI tool for checking EVM wallet balances (simulated).

    Accepts a wallet address, validates that it is a proper EVM address
    (0x-prefixed, 40 hexadecimal characters), and returns a dummy balance string.
    """

    name: str = "EVM Balance Checker"
    description: str = (
        "Menerima wallet address EVM dan mengembalikan saldo ETH (simulasi). "
        "Input harus berupa string wallet address yang valid (0x + 40 hex chars)."
    )

    # Pre-compile regex once for performance and safety
    _EVM_ADDRESS_RE: re.Pattern[str] = re.compile(
        r"^0x[0-9a-fA-F]{40}$"
    )

    def _run(self, wallet_address: str) -> str:
        """Execute the balance check with EVM address validation."""

        # --- input sanitization ---
        if not isinstance(wallet_address, str):
            return (
                "Error: wallet_address harus berupa string. "
                f"Tipe yang diterima: {type(wallet_address).__name__}"
            )

        address = wallet_address.strip()

        if not address:
            return "Error: wallet_address tidak boleh kosong."

        # --- regex validation ---
        if not self._EVM_ADDRESS_RE.match(address):
            return (
                f"Error: '{address}' bukan format EVM address yang valid. "
                "Address harus diawali dengan '0x' dan diikuti 40 karakter heksadesimal "
                "(contoh: 0xAbCdEf0123456789AbCdEf0123456789AbCdEf01)."
            )

        # --- simulated balance response ---
        return f"Saldo untuk address {address} adalah 0.0 ETH (Simulasi)"
