"""Tests for the hardcoded generic ABIs and ABI helper functions.

These are the building blocks of the Blind Execution stack — if these
break, every fallback path in :mod:`safe_transaction` breaks with them.
The tests are deliberately small and dependency-free (no chain, no
mocks, no network) so they run in milliseconds and never flake.
"""

from __future__ import annotations

from web3_crew.tools.abi_constants import (
    ERC20_TRANSFER_FUNCTIONS,
    ERC721_MINT_FUNCTIONS,
    GENERIC_ERC20_ABI,
    GENERIC_ERC721_ABI,
    find_function_entry,
    function_signature,
    summarize_mint_signatures,
)


# ---------------------------------------------------------------------------
# GENERIC_ERC721_ABI — guarantees the executor can fall back on standard NFTs
# ---------------------------------------------------------------------------
class TestErc721Abi:
    """Every NFT collection we care about exposes at least one of these
    mint variants. If any of them silently disappears, the generic
    fallback stops working without anyone noticing until a mint fails.
    """

    def test_contains_mint_uint256(self) -> None:
        entry = find_function_entry(GENERIC_ERC721_ABI, "mint")
        assert entry is not None
        assert entry["inputs"] == [{"name": "quantity", "type": "uint256"}]

    def test_contains_public_mint_zero_arg(self) -> None:
        entry = find_function_entry(GENERIC_ERC721_ABI, "publicMint")
        assert entry is not None
        assert entry["inputs"] == []

    def test_contains_safe_mint_two_arg(self) -> None:
        entry = find_function_entry(GENERIC_ERC721_ABI, "safeMint")
        assert entry is not None
        types = [i["type"] for i in entry["inputs"]]
        assert types == ["address", "uint256"]

    def test_mint_functions_constant_matches_abi(self) -> None:
        """The frozenset must enumerate everything in the generic ABI."""
        for name in ERC721_MINT_FUNCTIONS:
            assert find_function_entry(GENERIC_ERC721_ABI, name) is not None


# ---------------------------------------------------------------------------
# GENERIC_ERC20_ABI — canonical interface; do not silently grow this
# ---------------------------------------------------------------------------
class TestErc20Abi:
    """The ERC-20 fallback is intentionally tight: just the canonical
    interface plus the read-only views the executor uses for parameter
    sanity. Adding ``mint`` or ``approve(uint256.max)`` here would
    create a rug-pull vector the auditor explicitly screens for."""

    def test_canonical_transfer(self) -> None:
        entry = find_function_entry(GENERIC_ERC20_ABI, "transfer")
        assert entry is not None
        types = [i["type"] for i in entry["inputs"]]
        assert types == ["address", "uint256"]

    def test_canonical_approve(self) -> None:
        entry = find_function_entry(GENERIC_ERC20_ABI, "approve")
        assert entry is not None
        types = [i["type"] for i in entry["inputs"]]
        assert types == ["address", "uint256"]

    def test_canonical_transfer_from(self) -> None:
        entry = find_function_entry(GENERIC_ERC20_ABI, "transferFrom")
        assert entry is not None
        types = [i["type"] for i in entry["inputs"]]
        assert types == ["address", "address", "uint256"]

    def test_no_mint_present(self) -> None:
        """A mint on an ERC-20 fallback would be a rug-pull foot-gun."""
        assert find_function_entry(GENERIC_ERC20_ABI, "mint") is None

    def test_no_owner_only_extensions(self) -> None:
        """The fallback must not expose ``setFee``, ``setOwner`` etc.
        Those are exactly the patterns the rug-pull detector flags."""
        for name in ("setFee", "setOwner", "blacklist", "renounceOwnership"):
            assert find_function_entry(GENERIC_ERC20_ABI, name) is None

    def test_transfer_functions_constant_matches_abi(self) -> None:
        for name in ERC20_TRANSFER_FUNCTIONS:
            assert find_function_entry(GENERIC_ERC20_ABI, name) is not None


# ---------------------------------------------------------------------------
# function_signature — Solidity-style rendering for LLM-safe summaries
# ---------------------------------------------------------------------------
class TestFunctionSignature:
    def test_zero_arg_function(self) -> None:
        entry = {"name": "publicMint", "inputs": []}
        assert function_signature(entry) == "publicMint()"

    def test_named_args_are_rendered(self) -> None:
        entry = {
            "name": "safeMint",
            "inputs": [
                {"name": "to", "type": "address"},
                {"name": "qty", "type": "uint256"},
            ],
        }
        assert function_signature(entry) == "safeMint(address to, uint256 qty)"

    def test_unnamed_args_render_without_name(self) -> None:
        entry = {
            "name": "transfer",
            "inputs": [
                {"name": "", "type": "address"},
                {"name": "", "type": "uint256"},
            ],
        }
        assert function_signature(entry) == "transfer(address, uint256)"

    def test_missing_inputs_treated_as_empty(self) -> None:
        # Some Etherscan ABI rows omit ``inputs`` entirely (e.g. constructors
        # or receive fallbacks); we must not crash on those.
        assert function_signature({"name": "fallback"}) == "fallback()"


# ---------------------------------------------------------------------------
# summarize_mint_signatures — what the LLM actually sees in tool output
# ---------------------------------------------------------------------------
class TestSummarizeMintSignatures:
    def test_picks_only_mint_like_names(self) -> None:
        abi = [
            {"type": "function", "name": "totalSupply", "inputs": []},
            {"type": "function", "name": "mint", "inputs": [
                {"name": "qty", "type": "uint256"},
            ]},
            {"type": "function", "name": "publicMint", "inputs": []},
            {"type": "function", "name": "transfer", "inputs": []},
        ]
        summary = summarize_mint_signatures(abi)
        assert "mint(uint256 qty)" in summary
        assert "publicMint()" in summary
        assert "transfer" not in summary
        assert "totalSupply" not in summary

    def test_case_insensitive_match(self) -> None:
        abi = [{"type": "function", "name": "PrivateMINT", "inputs": []}]
        assert "PrivateMINT()" in summarize_mint_signatures(abi)

    def test_returns_friendly_message_when_no_match(self) -> None:
        abi = [{"type": "function", "name": "transfer", "inputs": []}]
        assert summarize_mint_signatures(abi) == "No mint-like functions found."

    def test_respects_limit(self) -> None:
        abi = [
            {"type": "function", "name": f"mint{i}", "inputs": []}
            for i in range(10)
        ]
        summary = summarize_mint_signatures(abi, limit=3)
        # 3 picks plus the prefix; check there are exactly 3 commas (one per
        # picked signature is rendered as ``mintN()``, joined with ", ").
        # We just count signatures by splitting on ", ".
        functions = summary.removeprefix("Mint-like functions: ").split(", ")
        assert len(functions) == 3

    def test_ignores_non_function_entries(self) -> None:
        abi = [
            {"type": "constructor", "name": "mint", "inputs": []},
            {"type": "event", "name": "Mint", "inputs": []},
        ]
        assert summarize_mint_signatures(abi) == "No mint-like functions found."
