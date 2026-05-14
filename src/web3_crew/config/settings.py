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

    # LLM
    openai_api_key: str = Field(description="OpenAI API key for CrewAI agents")

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


settings = Settings()
