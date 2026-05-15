"""Centralized configuration loaded from .env via pydantic-settings.

All secrets are accessed through this module — no hardcoded keys anywhere.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM — Google Gemini via litellm/CrewAI
    gemini_api_key: str = Field(description="Google Gemini API key for CrewAI agents")
    llm_model: str = Field(
        default="gemini/gemini-2.5-flash",
        description=(
            "LiteLLM-compatible model identifier. Use the 'gemini/<model>' prefix "
            "for Google Gemini models (e.g., 'gemini/gemini-2.5-flash'). "
            "Default is 'gemini-2.5-flash' since it's available on Google's free "
            "tier; '*-pro' models currently require a billing-enabled project."
        ),
    )
    llm_temperature: float = Field(
        default=0.2,
        description="Sampling temperature for the LLM (0.0 = deterministic).",
    )

    # Blockchain RPC
    web3_rpc_url: str = Field(
        default="https://eth.public-rpc.com",
        description="JSON-RPC endpoint for the target chain",
    )

    # Block explorer
    etherscan_api_key: str = Field(default="", description="Etherscan API key")

    # Wallet — loaded ONLY when needed by the Transaction Executor
    wallet_private_key: str = Field(default="", description="Hex-encoded private key (with 0x)")

    # Chain
    chain_id: int = Field(default=1, description="EVM chain ID")

    # Optional
    dexscreener_api_key: str = Field(default="", description="DexScreener API key (optional)")

    # Safety thresholds
    max_risk_score: int = Field(
        default=50,
        description="Maximum acceptable risk score for transaction execution",
    )
    max_gas_limit: int = Field(
        default=500_000,
        description="Hard cap on gas limit for any transaction",
    )

    # Gas war — EIP-1559 dynamic fee policy
    gas_strategy: str = Field(
        default="fast",
        description=(
            "EIP-1559 priority fee strategy: 'slow' (1.0x), 'standard' (1.5x), "
            "'fast' (2.0x), or 'aggressive' (3.0x). The multiplier is applied to "
            "the chain's suggested priority fee from eth_maxPriorityFeePerGas, "
            "then capped by max_priority_fee_gwei. Unknown values fall back to "
            "'fast'."
        ),
    )
    max_priority_fee_gwei: int = Field(
        default=5,
        description=(
            "Hard cap (in gwei) on maxPriorityFeePerGas. Prevents runaway costs "
            "during volatile network conditions. 5 gwei is reasonable on Ethereum "
            "mainnet; bump higher on L2s or during NFT mints."
        ),
    )
    flashbots_rpc_url: str = Field(
        default="",
        description=(
            "Optional MEV-protected RPC for transaction submission. Suggested: "
            "'https://rpc.flashbots.net' (free, no auth). When set, the signed "
            "transaction is broadcast through Flashbots' private mempool, hiding "
            "it from MEV bots that scan the public mempool for sandwich/frontrun "
            "opportunities. All reads (nonce, gas, balance, receipt polling) "
            "still go through web3_rpc_url. Mainnet-only; leave blank on other "
            "chains."
        ),
    )

    # Telegram bridge (only required when running ``python -m web3_crew.telegram_bot``;
    # the CLI entry point in ``main.py`` works without them).
    telegram_bot_token: str = Field(
        default="",
        description="BotFather token for the Telegram bridge. Empty disables the bot.",
    )
    authorized_user_id: int = Field(
        default=0,
        description=(
            "Telegram numeric user ID allowed to issue commands. Every update from "
            "any other ID is dropped before any handler runs. 0 disables the bot."
        ),
    )


settings = Settings()
