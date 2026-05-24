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

    # LLM provider selection. Default 'gemini' (free-tier, no setup change for
    # existing users). Set to 'cerebras' to route through Cerebras Cloud
    # (extremely fast Llama / GPT-OSS inference, also free-tier). Switching
    # provider only requires changing this var and supplying the matching
    # API key — no source edits needed.
    llm_provider: str = Field(
        default="gemini",
        description=(
            "LLM provider name. Supported: 'gemini' (Google AI Studio) or "
            "'cerebras' (Cerebras Cloud). The matching *_API_KEY must be set."
        ),
    )

    # Per-provider API keys. Only the one matching ``llm_provider`` is required
    # at runtime; the others can stay empty.
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key (required when LLM_PROVIDER=gemini).",
    )
    cerebras_api_key: str = Field(
        default="",
        description="Cerebras Cloud API key (required when LLM_PROVIDER=cerebras).",
    )

    llm_model: str = Field(
        default="",
        description=(
            "LiteLLM-compatible model identifier, e.g. 'gemini/gemini-2.5-flash' "
            "or 'cerebras/llama3.1-8b'. Leave empty to use the provider's default "
            "model picked by :func:`web3_crew.llm.create_llm`."
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
    alchemy_api_key: str = Field(
        default="",
        description=(
            "Optional Alchemy API key for the post-mint metadata fetcher "
            "(NFT name, image, traits). When empty, the fetcher gracefully "
            "degrades to a static Etherscan + OpenSea link in the Telegram "
            "response. Get a free key at https://dashboard.alchemy.com/."
        ),
    )

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

    # Defensive execution
    max_tx_cost_eth: float = Field(
        default=0.05,
        description=(
            "Per-transaction worst-case cost budget in ETH. Before signing, the "
            "executor refuses to submit any transaction whose "
            "gas_limit * max_fee_per_gas exceeds this value. Default 0.05 ETH "
            "(~$150 at ETH=$3k) is a sane cap for one-off mints; raise it "
            "deliberately for high-value drops."
        ),
    )
    tx_wait_seconds: int = Field(
        default=120,
        description=(
            "How long the executor waits for the transaction receipt before "
            "treating the tx as stuck. A stuck tx is reported with status='pending' "
            "plus tx_hash + nonce + explorer link so the user can replace or cancel."
        ),
    )
    enable_auto_rbf: bool = Field(
        default=False,
        description=(
            "Opt-in Replace-By-Fee: when a tx is stuck after tx_wait_seconds, "
            "automatically resubmit the same nonce with a 1.5x bumped priority "
            "fee, up to max_rbf_attempts times. Each retry still respects "
            "max_priority_fee_gwei and max_tx_cost_eth so it cannot drain the "
            "wallet. Default OFF — keep the conservative one-shot behaviour."
        ),
    )
    max_rbf_attempts: int = Field(
        default=1,
        description=(
            "Maximum number of Replace-By-Fee retries when enable_auto_rbf=True. "
            "1 means: one original submission plus one bumped resubmission. "
            "Ignored when enable_auto_rbf=False."
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
