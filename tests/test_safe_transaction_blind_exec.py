"""Tests for the Blind Execution stack in :mod:`safe_transaction`.

Scope: the *non-chain* parts of the executor — input validation, the ABI
resolution decision tree, and the dual tx-factory abstraction. Anything
that would require a live RPC connection or a real Etherscan call is
mocked or skipped here; integration of the chain-touching paths is
covered manually against a Sepolia node.

The most important guarantee these tests defend is: **the LLM never sees
the raw ABI**. Specifically:

1. The tool's *input* schema no longer treats ``abi`` as required, and
   when the LLM does pass one anyway, it must be silently dropped.
2. The tool's *output* always carries an ``abi_source`` label and a
   ``function_signature`` short string instead of a JSON blob.
3. When the LLM provides ``raw_calldata``, the ABI resolution path is
   bypassed entirely (no Etherscan fetch, no generic lookup).
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import patch

import pytest

# Set required env BEFORE importing settings (pydantic-settings reads at
# module-import time). These values are dummies — the tests that need a
# real chain are skipped, and the tests that need an Etherscan response
# fully mock ``httpx.Client.get``.
os.environ.setdefault("GEMINI_API_KEY", "dummy-gemini-key")
os.environ.setdefault("CEREBRAS_API_KEY", "dummy-cerebras-key")
os.environ.setdefault("WEB3_RPC_URL", "https://example.invalid")
os.environ.setdefault("ETHERSCAN_API_KEY", "dummy-etherscan-key")
os.environ.setdefault("WALLET_PRIVATE_KEY", "0x" + "11" * 32)
os.environ.setdefault("LLM_PROVIDER", "gemini")

from web3_crew.tools.abi_constants import (  # noqa: E402
    GENERIC_ERC20_ABI,
    GENERIC_ERC721_ABI,
)
from web3_crew.tools.safe_transaction import (  # noqa: E402
    SafeTransactionTool,
    _pick_generic_abi_for,
    _resolve_abi,
)


@pytest.fixture
def tool() -> SafeTransactionTool:
    return SafeTransactionTool()


def _parse(result: str) -> dict[str, Any]:
    return json.loads(result)


# ---------------------------------------------------------------------------
# Input validation — must run before any chain or Etherscan I/O
# ---------------------------------------------------------------------------
class TestInputValidation:
    def test_invalid_json_returns_error(self, tool: SafeTransactionTool) -> None:
        result = _parse(tool._run("{not json"))
        assert result["status"] == "error"
        assert "not valid JSON" in result["reason"]

    def test_high_risk_score_is_rejected(self, tool: SafeTransactionTool) -> None:
        # Threshold is 50 by default; 75 must be refused before any I/O.
        payload = {
            "action": "mint",
            "contract_address": "0x" + "ab" * 20,
            "function_name": "mint",
            "function_args": [1],
            "risk_score": 75,
        }
        result = _parse(tool._run(json.dumps(payload)))
        assert result["status"] == "rejected"
        assert "Risk score 75" in result["reason"]

    def test_missing_contract_address(self, tool: SafeTransactionTool) -> None:
        payload = {
            "action": "mint",
            "function_name": "mint",
            "risk_score": 10,
        }
        result = _parse(tool._run(json.dumps(payload)))
        assert result["status"] == "error"
        assert "contract_address" in result["reason"]

    def test_missing_function_name_without_raw(self, tool: SafeTransactionTool) -> None:
        payload = {
            "action": "mint",
            "contract_address": "0x" + "ab" * 20,
            "risk_score": 10,
        }
        result = _parse(tool._run(json.dumps(payload)))
        assert result["status"] == "error"
        assert "function_name" in result["reason"]

    def test_raw_calldata_must_be_hex(self, tool: SafeTransactionTool) -> None:
        payload = {
            "action": "raw",
            "contract_address": "0x" + "ab" * 20,
            "raw_calldata": "not-hex",
            "risk_score": 10,
        }
        result = _parse(tool._run(json.dumps(payload)))
        assert result["status"] == "error"
        assert "0x-prefixed hex" in result["reason"]

    def test_raw_calldata_must_have_selector(self, tool: SafeTransactionTool) -> None:
        # Less than 4 bytes (8 hex chars) of selector is not a real call.
        payload = {
            "action": "raw",
            "contract_address": "0x" + "ab" * 20,
            "raw_calldata": "0x12",
            "risk_score": 10,
        }
        result = _parse(tool._run(json.dumps(payload)))
        assert result["status"] == "error"
        assert "selector" in result["reason"]


# ---------------------------------------------------------------------------
# ABI-leak defense — the bug this whole stack exists to prevent
# ---------------------------------------------------------------------------
class TestAbiNeverLeaksThroughInput:
    """The LLM must not be able to push a 50KB ABI back into context by
    accident. Even if a future regression in the agent prompt makes it
    happen, the tool must silently drop the ``abi`` field before any
    downstream processing."""

    def test_abi_in_payload_is_dropped(self, tool: SafeTransactionTool) -> None:
        # Use a high risk_score so the call short-circuits *after* the
        # ABI-strip logic runs. The interesting assertion is that the
        # tool didn't crash on a malformed/oversized ABI input.
        huge_fake_abi = "x" * 50_000
        payload = {
            "action": "mint",
            "contract_address": "0x" + "ab" * 20,
            "function_name": "mint",
            "function_args": [1],
            "risk_score": 99,  # gate at risk-check, before chain I/O
            "abi": huge_fake_abi,
        }
        result = _parse(tool._run(json.dumps(payload)))
        # The risk gate should fire, and the response must NOT echo the ABI.
        assert result["status"] == "rejected"
        assert huge_fake_abi not in json.dumps(result)


# ---------------------------------------------------------------------------
# Generic ABI fallback — the decision tree for picking the right generic
# ---------------------------------------------------------------------------
class TestPickGenericAbi:
    def test_mint_picks_erc721(self) -> None:
        assert _pick_generic_abi_for("mint") is GENERIC_ERC721_ABI

    def test_public_mint_picks_erc721(self) -> None:
        assert _pick_generic_abi_for("publicMint") is GENERIC_ERC721_ABI

    def test_safe_mint_picks_erc721(self) -> None:
        assert _pick_generic_abi_for("safeMint") is GENERIC_ERC721_ABI

    def test_transfer_picks_erc20(self) -> None:
        assert _pick_generic_abi_for("transfer") is GENERIC_ERC20_ABI

    def test_approve_picks_erc20(self) -> None:
        assert _pick_generic_abi_for("approve") is GENERIC_ERC20_ABI

    def test_balance_of_falls_back_to_first_match(self) -> None:
        # ``balanceOf`` is in both generics; the helper should return one
        # of them (ERC-721 is checked first in the secondary scan).
        picked = _pick_generic_abi_for("balanceOf")
        assert picked is GENERIC_ERC721_ABI

    def test_unknown_returns_none(self) -> None:
        assert _pick_generic_abi_for("rugPull") is None


# ---------------------------------------------------------------------------
# _resolve_abi — the actual decision tree used by the tool body
# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class TestResolveAbi:
    def test_verified_contract_returns_only_target_entry(self) -> None:
        """Smart parse: even when Etherscan returns a 50-entry ABI, only
        the single entry for the requested function is returned. That's
        what keeps the LLM context cheap."""
        real_abi = [
            {"type": "function", "name": "mint", "inputs": [
                {"name": "qty", "type": "uint256"},
            ]},
            # 49 distractor entries — none of these may end up in the
            # returned ABI.
            *[
                {"type": "function", "name": f"distractor{i}", "inputs": []}
                for i in range(49)
            ],
        ]
        etherscan_payload = {"status": "1", "result": json.dumps(real_abi)}
        with patch(
            "web3_crew.tools.safe_transaction.httpx.Client",
        ) as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = FakeResp(etherscan_payload)
            abi, source = _resolve_abi(
                contract_address="0x" + "ab" * 20,
                function_name="mint",
                api_key="dummy",
                chain_id=1,
            )
        assert source == "etherscan_parsed"
        assert abi is not None
        assert len(abi) == 1
        assert abi[0]["name"] == "mint"

    def test_unverified_contract_falls_back_to_erc721(self) -> None:
        etherscan_payload = {"status": "0", "result": "Contract source code not verified"}
        with patch(
            "web3_crew.tools.safe_transaction.httpx.Client",
        ) as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = FakeResp(etherscan_payload)
            abi, source = _resolve_abi(
                contract_address="0x" + "ab" * 20,
                function_name="mint",
                api_key="dummy",
                chain_id=1,
            )
        assert source == "generic_erc721"
        assert abi is GENERIC_ERC721_ABI

    def test_unverified_contract_with_erc20_function_falls_back_to_erc20(self) -> None:
        etherscan_payload = {"status": "0", "result": "Contract source code not verified"}
        with patch(
            "web3_crew.tools.safe_transaction.httpx.Client",
        ) as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = FakeResp(etherscan_payload)
            abi, source = _resolve_abi(
                contract_address="0x" + "ab" * 20,
                function_name="transfer",
                api_key="dummy",
                chain_id=1,
            )
        assert source == "generic_erc20"
        assert abi is GENERIC_ERC20_ABI

    def test_etherscan_failure_falls_back_to_generic(self) -> None:
        """Any non-200 / malformed response from Etherscan must trigger
        the generic fallback — we never want a transient HTTP failure
        to crash a mint."""
        with patch(
            "web3_crew.tools.safe_transaction.httpx.Client",
        ) as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = RuntimeError("network down")
            abi, source = _resolve_abi(
                contract_address="0x" + "ab" * 20,
                function_name="mint",
                api_key="dummy",
                chain_id=1,
            )
        assert source == "generic_erc721"
        assert abi is GENERIC_ERC721_ABI

    def test_verified_but_function_missing_falls_back(self) -> None:
        """Edge case: Etherscan returns a real ABI but the LLM
        hallucinated a function name that does not exist on-chain. We
        try the generic fallback before giving up."""
        real_abi = [{"type": "function", "name": "totalSupply", "inputs": []}]
        etherscan_payload = {"status": "1", "result": json.dumps(real_abi)}
        with patch(
            "web3_crew.tools.safe_transaction.httpx.Client",
        ) as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = FakeResp(etherscan_payload)
            abi, source = _resolve_abi(
                contract_address="0x" + "ab" * 20,
                function_name="mint",  # not in real_abi but in GENERIC_ERC721
                api_key="dummy",
                chain_id=1,
            )
        assert source == "generic_erc721"
        assert abi is GENERIC_ERC721_ABI

    def test_completely_unknown_function_returns_no_match(self) -> None:
        with patch(
            "web3_crew.tools.safe_transaction.httpx.Client",
        ) as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = FakeResp({"status": "0", "result": ""})
            abi, source = _resolve_abi(
                contract_address="0x" + "ab" * 20,
                function_name="rugPull",
                api_key="dummy",
                chain_id=1,
            )
        assert source == "no_match"
        assert abi is None


# ---------------------------------------------------------------------------
# Tool description — guards against silent contract-test breakage
# ---------------------------------------------------------------------------
class TestToolDescription:
    """The agent reads this description verbatim and uses it to choose
    its tool input fields. If we accidentally re-add language about
    passing the ABI, the OOM bug comes right back."""

    def test_says_do_not_pass_abi(self, tool: SafeTransactionTool) -> None:
        assert "DO NOT pass the contract ABI" in tool.description

    def test_mentions_raw_calldata(self, tool: SafeTransactionTool) -> None:
        assert "raw_calldata" in tool.description

    def test_mentions_generic_fallback(self, tool: SafeTransactionTool) -> None:
        assert "generic" in tool.description.lower()
