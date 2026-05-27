"""Integration test for the post-tx metadata hook in safe_transaction.

These tests exercise the **terminal-response branch only** — the tiny
addition we made to :func:`safe_transaction._terminal_response`. The
hook must:

* Run only on the success path (status code 1).
* Never appear on the reverted path (status code 0).
* Never crash the success response even if the metadata fetcher were
  to misbehave (belt-and-suspenders try/except inside the hook).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from web3_crew.tools import safe_transaction

_TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _padded_int(value: int) -> str:
    return "0x" + format(value, "x").rjust(64, "0")


def _padded_addr(addr: str) -> str:
    return "0x" + addr[2:].rjust(64, "0")


def _success_receipt(*, token_id: int = 7) -> dict[str, Any]:
    return {
        "transactionHash": MagicMock(hex=lambda: "0xfeedface"),
        "blockNumber": 18_000_000,
        "gasUsed": 92_000,
        "effectiveGasPrice": 25_000_000_000,
        "status": 1,
        "logs": [
            {
                "topics": [
                    _TRANSFER_TOPIC0,
                    _padded_addr("0x" + "00" * 20),
                    _padded_addr("0x" + "ab" * 20),
                    _padded_int(token_id),
                ],
                "data": "0x",
            }
        ],
    }


def _reverted_receipt() -> dict[str, Any]:
    return {
        "transactionHash": MagicMock(hex=lambda: "0xbeef"),
        "blockNumber": 18_000_000,
        "gasUsed": 21_000,
        "effectiveGasPrice": 25_000_000_000,
        "status": 0,
        "logs": [],
    }


class TestSuccessAddsMetadata:
    def test_success_response_includes_metadata_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No Alchemy key -> fallback path, but metadata_summary still
        # populated with Etherscan + OpenSea links.
        monkeypatch.setattr(
            "web3_crew.tools.post_tx_metadata.settings.alchemy_api_key", ""
        )
        out = safe_transaction._terminal_response(
            receipt=_success_receipt(),
            function_name="mint",
            max_fee=30_000_000_000,
            priority_fee=2_000_000_000,
            attempts_used=1,
            fee_mode="eip1559",
            abi_source="etherscan_parsed",
            resolved_signature="mint(uint256)",
            contract_address="0x" + "cd" * 20,
        )
        parsed = json.loads(out)
        assert parsed["status"] == "success"
        assert parsed["metadata_status"] in {"ok", "fallback"}
        assert "metadata_summary" in parsed
        # The token id from the receipt log should make it into the
        # summary string.
        assert "7" in parsed["metadata_summary"]

    def test_metadata_summary_is_short_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "web3_crew.tools.post_tx_metadata.settings.alchemy_api_key", ""
        )
        out = safe_transaction._terminal_response(
            receipt=_success_receipt(),
            function_name="mint",
            max_fee=30_000_000_000,
            priority_fee=2_000_000_000,
            attempts_used=1,
            fee_mode="eip1559",
            abi_source="etherscan_parsed",
            resolved_signature="mint(uint256)",
            contract_address="0x" + "cd" * 20,
        )
        parsed = json.loads(out)
        # Must stay LLM-friendly even on the success path.
        assert len(parsed["metadata_summary"]) < 1024

    def test_success_with_no_contract_address_does_not_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "web3_crew.tools.post_tx_metadata.settings.alchemy_api_key", ""
        )
        out = safe_transaction._terminal_response(
            receipt=_success_receipt(),
            function_name="mint",
            max_fee=30_000_000_000,
            priority_fee=2_000_000_000,
            attempts_used=1,
            fee_mode="eip1559",
            abi_source="raw_calldata",
            resolved_signature="raw(0x...)",
            # Defaults to "" — the raw-calldata path may set it empty.
        )
        parsed = json.loads(out)
        assert parsed["status"] == "success"
        # Skipped status is fine; the response must still parse.
        assert "metadata_summary" in parsed


class TestRevertedSkipsMetadata:
    def test_reverted_response_does_not_include_metadata(self) -> None:
        out = safe_transaction._terminal_response(
            receipt=_reverted_receipt(),
            function_name="mint",
            max_fee=30_000_000_000,
            priority_fee=2_000_000_000,
            attempts_used=1,
            fee_mode="eip1559",
            abi_source="etherscan_parsed",
            resolved_signature="mint(uint256)",
            contract_address="0x" + "cd" * 20,
        )
        parsed = json.loads(out)
        assert parsed["status"] == "reverted"
        # metadata_summary/status are deliberately NOT added on revert —
        # there's no NFT to surface and the user needs the revert reason
        # not a generic link.
        assert "metadata_summary" not in parsed
        assert "metadata_status" not in parsed


class TestFetcherCrashIsContained:
    """Belt-and-suspenders: even if the fetcher raises, success survives."""

    def test_fetcher_raising_still_returns_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**kwargs: Any) -> dict[str, str]:
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "web3_crew.tools.safe_transaction.fetch_post_tx_metadata", _boom
        )
        out = safe_transaction._terminal_response(
            receipt=_success_receipt(),
            function_name="mint",
            max_fee=30_000_000_000,
            priority_fee=2_000_000_000,
            attempts_used=1,
            fee_mode="eip1559",
            abi_source="etherscan_parsed",
            resolved_signature="mint(uint256)",
            contract_address="0x" + "cd" * 20,
        )
        parsed = json.loads(out)
        assert parsed["status"] == "success"
        assert parsed["metadata_status"] == "fallback"
        summary_lower = parsed["metadata_summary"].lower()
        assert "failed" in summary_lower or "pending" in summary_lower
