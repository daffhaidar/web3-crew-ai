"""Pytest configuration — set test-only env defaults BEFORE any imports.

Pydantic-settings reads environment variables at ``Settings()`` construction
time (which happens at module import, since ``settings = Settings()`` is a
module-level singleton in :mod:`web3_crew.config.settings`). If a single test
file imports settings before another test file sets its env defaults, those
defaults are baked in for the rest of the session.

Centralising the defaults in a top-level conftest guarantees they are in
place before any test module — or any source module — is imported. Tests
that need different values can override per-test with ``monkeypatch.setenv``.
"""

from __future__ import annotations

import os

# These are dummies. Tests that need real chain access are explicitly skipped
# or mocked. The values just need to be non-empty so the bot's env-presence
# checks pass and the executor doesn't short-circuit with "no wallet
# configured" before our validation logic runs.
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("GEMINI_API_KEY", "dummy-gemini-key")
os.environ.setdefault("CEREBRAS_API_KEY", "dummy-cerebras-key")
os.environ.setdefault("WEB3_RPC_URL", "https://example.invalid")
os.environ.setdefault("ETHERSCAN_API_KEY", "dummy-etherscan-key")
os.environ.setdefault("WALLET_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy-bot-token")
os.environ.setdefault("AUTHORIZED_USER_ID", "0")
os.environ.setdefault("ALCHEMY_API_KEY", "")
