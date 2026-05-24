"""Regression tests for the source-code leak in ``TokenDataFetcherTool``.

These tests are the canonical guard for the "OOM 8192 still happening"
bug. They mock the Etherscan V2 HTTP layer so we can feed deliberately
**huge** Solidity source bodies into the tool and assert that:

1. The raw ``source_code`` field never appears in the response.
2. Instead, ``source_findings`` (a compact list) + ``source_summary``
   (a short headline) are returned.
3. The total response size stays well below the small-context window
   (8K tokens ~= 32 KB UTF-8) even for a 100 KB input source.
4. Known dangerous patterns from the input are still surfaced via
   findings (the analyzer must run inline, not be skipped).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from web3_crew.tools.token_data_fetcher import TokenDataFetcherTool

# A 100 KB synthetic Solidity blob — far above the 8K context window for
# small models. If the tool echoed this back, the test would catch it.
_HUGE_SOLIDITY = (
    "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\n"
    "contract Token {\n"
    "    function mint(uint256 amount) public {}\n"
    "    function setFee(uint256 f) external onlyOwner {}\n"
    "    function nuke() public { selfdestruct(payable(msg.sender)); }\n"
    "    mapping(address => bool) public _blacklist;\n"
    "    function check(address u) public view returns (bool) { return _blacklist[u]; }\n"
    + ("    // padding line to grow the source bigger than the LLM window\n" * 1500)
    + "}\n"
)


def _make_response(payload: dict[str, Any]) -> MagicMock:
    """Build a httpx-style mock response that returns ``payload`` from .json()."""
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _build_etherscan_mock(*, source_code: str, abi: str) -> MagicMock:
    """Return a mock ``httpx.Client`` whose .get cycles through:
    getsourcecode → getcontractcreation → tokensupply."""
    getsource = _make_response(
        {
            "status": "1",
            "result": [
                {
                    "ContractName": "Token",
                    "CompilerVersion": "v0.8.20+commit.a1b79de6",
                    "SourceCode": source_code,
                    "ABI": abi,
                }
            ],
        }
    )
    creation = _make_response(
        {
            "status": "1",
            "result": [
                {
                    "contractCreator": "0x" + "ab" * 20,
                    "txHash": "0x" + "cd" * 32,
                }
            ],
        }
    )
    supply = _make_response({"status": "1", "result": "1000000000000000000"})

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.side_effect = [getsource, creation, supply]
    return client


@pytest.fixture
def tool() -> TokenDataFetcherTool:
    return TokenDataFetcherTool(api_key="dummy")


class TestNoSourceCodeLeak:
    """The raw ``source_code`` field MUST NOT be in the response."""

    def test_huge_source_is_not_echoed(self, tool: TokenDataFetcherTool) -> None:
        mock_client = _build_etherscan_mock(
            source_code=_HUGE_SOLIDITY,
            abi='[{"type":"function","name":"mint","inputs":[{"type":"uint256"}]}]',
        )
        with patch("web3_crew.tools.token_data_fetcher.httpx.Client", return_value=mock_client):
            raw_response = tool._run("0x" + "ab" * 20)
        parsed = json.loads(raw_response)

        # The leak guards.
        assert "source_code" not in parsed
        assert "SourceCode" not in parsed
        # And the raw blob must not appear anywhere in the payload as
        # a substring either.
        snippet = _HUGE_SOLIDITY[200:500]
        assert snippet not in raw_response

    def test_response_size_stays_small(self, tool: TokenDataFetcherTool) -> None:
        """Response size must stay LLM-friendly even with a 100 KB source.

        8K tokens ~= 32 KB of UTF-8 in practice. We assert << that.
        """
        mock_client = _build_etherscan_mock(
            source_code=_HUGE_SOLIDITY,
            abi='[{"type":"function","name":"mint","inputs":[{"type":"uint256"}]}]',
        )
        with patch("web3_crew.tools.token_data_fetcher.httpx.Client", return_value=mock_client):
            raw_response = tool._run("0x" + "ab" * 20)

        # Source blob is ~100 KB; response should be < 5 KB.
        assert len(_HUGE_SOLIDITY) > 50_000
        assert len(raw_response) < 5_000, (
            f"Response is {len(raw_response)} bytes — source code is leaking"
        )


class TestFindingsStillSurfaced:
    """Inline analysis must still detect known dangerous patterns."""

    def test_known_patterns_present_in_findings(
        self, tool: TokenDataFetcherTool
    ) -> None:
        mock_client = _build_etherscan_mock(
            source_code=_HUGE_SOLIDITY,
            abi='[{"type":"function","name":"mint","inputs":[]}]',
        )
        with patch("web3_crew.tools.token_data_fetcher.httpx.Client", return_value=mock_client):
            parsed = json.loads(tool._run("0x" + "ab" * 20))

        assert "source_findings" in parsed
        names = {f["name"] for f in parsed["source_findings"]}
        # All four patterns embedded in _HUGE_SOLIDITY must be reported.
        assert "hidden_mint" in names
        assert "fee_manipulation" in names
        assert "selfdestruct" in names
        assert "blacklist" in names
        assert parsed["has_critical_finding"] is True
        assert parsed["has_high_finding"] is True

    def test_source_summary_is_short(self, tool: TokenDataFetcherTool) -> None:
        mock_client = _build_etherscan_mock(
            source_code=_HUGE_SOLIDITY,
            abi='[{"type":"function","name":"mint","inputs":[]}]',
        )
        with patch("web3_crew.tools.token_data_fetcher.httpx.Client", return_value=mock_client):
            parsed = json.loads(tool._run("0x" + "ab" * 20))

        assert isinstance(parsed["source_summary"], str)
        assert len(parsed["source_summary"]) < 400


class TestUnverifiedContract:
    """Unverified contracts must produce an explicit ``analyzed=False`` digest."""

    def test_unverified_response_shape(self, tool: TokenDataFetcherTool) -> None:
        mock_client = _build_etherscan_mock(
            source_code="",
            abi="Contract source code not verified",
        )
        with patch("web3_crew.tools.token_data_fetcher.httpx.Client", return_value=mock_client):
            parsed = json.loads(tool._run("0x" + "ab" * 20))

        assert parsed["is_verified"] is False
        assert "source_code" not in parsed
        assert parsed["source_findings"] == []
        assert "unverified" in parsed["source_summary"].lower()
        assert parsed["abi_summary"].startswith("Contract unverified")


class TestEtherscanDown:
    """Etherscan returning a non-1 status must still produce a clean response."""

    def test_etherscan_failure_branch(self, tool: TokenDataFetcherTool) -> None:
        # Both getsourcecode and getcontractcreation return "0".
        failing = _make_response({"status": "0", "result": []})
        # tokensupply still works (web3 fallback shape) — but the test
        # only really cares about the first call. Mock all three to be
        # defensive.
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.get.side_effect = [failing, failing, failing]

        with patch("web3_crew.tools.token_data_fetcher.httpx.Client", return_value=client):
            parsed = json.loads(tool._run("0x" + "ab" * 20))

        assert "source_code" not in parsed
        assert parsed["is_verified"] is False
        assert "source_findings" in parsed
        assert parsed["abi_summary"].startswith("Etherscan returned no data")
