"""Unit tests for :mod:`web3_crew.tools.source_analyzer`.

These tests guard the regex-based Solidity static analyzer that now
runs **inside** :class:`TokenDataFetcherTool` so the raw source code
never reaches the LLM. They verify that:

* Known dangerous patterns are detected and graded correctly.
* The ``summary`` headline stays short (< 200 chars) for any input.
* Unverified / empty sources are handled without raising.
* Owner-restricted function names are capped to a sane upper bound.

Together with :mod:`tests.test_token_data_fetcher_source_leak` these
tests are the regression suite for the "source code OOM" fix.
"""

from __future__ import annotations

import pytest

from web3_crew.tools.source_analyzer import (
    DANGEROUS_PATTERNS,
    UNVERIFIED_PLACEHOLDER,
    analyze_source_code,
    summarize_findings,
)


class TestAnalyzeSourceCodeEmpty:
    """Empty / unverified inputs must short-circuit cleanly."""

    def test_empty_string(self) -> None:
        result = analyze_source_code("")
        assert result["analyzed"] is False
        assert result["findings"] == []
        assert result["pattern_count"] == 0
        assert result["has_critical"] is False
        assert result["has_high"] is False
        assert "unverified" in result["summary"].lower()

    def test_whitespace_only(self) -> None:
        result = analyze_source_code("   \n\t  ")
        assert result["analyzed"] is False
        assert result["findings"] == []

    def test_none_input(self) -> None:
        result = analyze_source_code(None)
        assert result["analyzed"] is False
        assert result["findings"] == []

    def test_unverified_placeholder(self) -> None:
        result = analyze_source_code(UNVERIFIED_PLACEHOLDER)
        assert result["analyzed"] is False
        assert result["findings"] == []


class TestAnalyzeSourceCodeClean:
    """A trivial, clean contract should produce zero findings."""

    SOURCE = """
    // SPDX-License-Identifier: MIT
    pragma solidity ^0.8.20;

    contract Greeter {
        string public greeting = "Hello, world!";
    }
    """

    def test_no_findings(self) -> None:
        result = analyze_source_code(self.SOURCE)
        assert result["analyzed"] is True
        assert result["findings"] == []
        assert result["pattern_count"] == 0
        assert result["has_critical"] is False
        assert result["has_high"] is False
        assert "0 dangerous patterns" in result["summary"]


class TestAnalyzeSourceCodeDangerous:
    """Patterns we explicitly screen for must be detected."""

    def test_hidden_mint(self) -> None:
        source = """
        function mint(uint256 amount) public {
            _balances[msg.sender] += amount;
        }
        """
        result = analyze_source_code(source)
        names = {f["name"] for f in result["findings"]}
        assert "hidden_mint" in names
        assert result["has_high"] is True

    def test_selfdestruct_is_critical(self) -> None:
        source = "function nuke() public { selfdestruct(payable(owner)); }"
        result = analyze_source_code(source)
        names = {f["name"] for f in result["findings"]}
        assert "selfdestruct" in names
        assert result["has_critical"] is True

    def test_blacklist_pattern(self) -> None:
        source = (
            "mapping(address => bool) public isBlacklisted; "
            "function check() { isBlacklisted[user]; }"
        )
        result = analyze_source_code(source)
        names = {f["name"] for f in result["findings"]}
        assert "blacklist" in names

    def test_fee_manipulation(self) -> None:
        source = "function setFee(uint256 newFee) external onlyOwner { _taxFee = newFee; }"
        result = analyze_source_code(source)
        names = {f["name"] for f in result["findings"]}
        assert "fee_manipulation" in names

    def test_proxy_pattern(self) -> None:
        source = "function upgradeTo(address newImplementation) external { delegatecall(); }"
        result = analyze_source_code(source)
        names = {f["name"] for f in result["findings"]}
        assert "proxy_pattern" in names
        assert result["has_high"] is True

    def test_occurrences_counted(self) -> None:
        source = """
        function mint(uint256 a) public {}
        function mintBatch(uint256 b) public {}
        function publicMint() public {}
        """
        result = analyze_source_code(source)
        mint_finding = next(f for f in result["findings"] if f["name"] == "hidden_mint")
        # The hidden_mint regex matches any function name containing 'mint'.
        # Should fire on at least three of the four lines.
        assert mint_finding["occurrences"] >= 3


class TestOwnerOnlyDetection:
    """``onlyOwner`` modifier scan must list functions and cap the count."""

    def test_basic_owner_function_listed(self) -> None:
        source = "function setBaseURI(string memory uri) public onlyOwner { _uri = uri; }"
        result = analyze_source_code(source)
        owner_finding = next(
            (f for f in result["findings"] if f["name"] == "owner_restricted_functions"),
            None,
        )
        assert owner_finding is not None
        assert "setBaseURI" in owner_finding["description"]

    def test_many_owner_functions_capped_in_description(self) -> None:
        # 25 owner-only functions — description should only list the first 10.
        lines = [
            f"function admin{i}(uint256 v) public onlyOwner {{}}"
            for i in range(25)
        ]
        source = "\n".join(lines)
        result = analyze_source_code(source)
        owner_finding = next(
            f for f in result["findings"] if f["name"] == "owner_restricted_functions"
        )
        assert owner_finding["occurrences"] == 25
        # admin0..admin9 listed, admin10..admin24 excluded from the string.
        for i in range(10):
            assert f"admin{i}" in owner_finding["description"]
        for i in range(10, 25):
            assert f"admin{i}" not in owner_finding["description"]


class TestSummary:
    """Headline must stay short and bounded — it goes into the LLM context."""

    def test_zero_findings_summary(self) -> None:
        assert summarize_findings([]) == (
            "0 dangerous patterns matched. Source code passes static checks."
        )

    def test_single_finding_singular(self) -> None:
        findings = [
            {
                "name": "selfdestruct",
                "severity": "CRITICAL",
                "description": "...",
                "occurrences": 1,
            }
        ]
        assert "1 pattern flagged" in summarize_findings(findings)
        assert "Highest: CRITICAL" in summarize_findings(findings)

    def test_caps_names_in_summary(self) -> None:
        many = [
            {
                "name": f"finding_{i}",
                "severity": "INFO",
                "description": "x",
                "occurrences": 1,
            }
            for i in range(10)
        ]
        summary = summarize_findings(many)
        # Should list 5 names + "+5 more"
        assert "+5 more" in summary
        for i in range(5):
            assert f"finding_{i}" in summary
        for i in range(5, 10):
            assert f"finding_{i}" not in summary

    def test_summary_length_bounded(self) -> None:
        """Even with worst-case input, summary must stay < 400 chars."""
        many = [
            {
                "name": "x" * 50,
                "severity": "CRITICAL",
                "description": "y" * 200,
                "occurrences": 1,
            }
            for _ in range(20)
        ]
        summary = summarize_findings(many)
        assert len(summary) < 400


class TestPatternRegistry:
    """The DANGEROUS_PATTERNS registry must stay well-formed."""

    @pytest.mark.parametrize("pattern", DANGEROUS_PATTERNS)
    def test_each_pattern_has_required_fields(self, pattern: dict) -> None:
        for required in ("name", "pattern", "severity", "description"):
            assert required in pattern, f"missing {required!r} in {pattern!r}"
        assert pattern["severity"] in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}

    def test_pattern_names_are_unique(self) -> None:
        names = [p["name"] for p in DANGEROUS_PATTERNS]
        assert len(names) == len(set(names))
