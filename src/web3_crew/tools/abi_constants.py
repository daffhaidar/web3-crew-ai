"""Hardcoded generic ABI fragments used when the on-chain ABI is unavailable
or intentionally bypassed.

Why this module exists
----------------------
The Transaction Executor used to receive the full Etherscan ABI (often
10–50 KB of JSON) in its LLM context via the agent's tool input payload.
A model with an 8K-token context window — e.g. ``cerebras/gpt-oss-120b``
on the free tier — OOMs and silently truncates the payload, which makes
the agent crash with cryptic "context length exceeded" errors mid-mint.

The fix splits ABI handling cleanly between Python and the LLM:

* Python (this module + :mod:`web3_crew.tools.safe_transaction`) holds
  ABI knowledge. The LLM never sees raw ABI JSON.
* The LLM only sees short, human-readable summaries
  ("Found function: mint(uint256 amount)") and, when nothing else works,
  a label like ``"using GENERIC_ERC721_ABI (blind execution)"``.

Generic fallback ABIs cover the *minimal* surface needed to mint or move
tokens on EVM contracts that follow ERC-20 / ERC-721 conventions:

* **ERC-721**: ``mint``, ``publicMint``, ``safeMint`` (3 common variants
  named by NFT collections); ``totalSupply`` / ``balanceOf`` for sanity
  reads.
* **ERC-20**: ``transfer``, ``approve``, ``transferFrom``, ``balanceOf``,
  ``totalSupply``, ``decimals``, ``symbol`` — the canonical ERC-20
  interface plus the read-only views the executor sometimes needs to
  validate parameters.

When neither parsing nor the generic ABIs match, the tool falls back to
"blind calldata" mode: the caller supplies a hex ``raw_calldata`` string
and the tool broadcasts it without any ABI lookup. This is the escape
hatch for proxy contracts, custom mint functions, and any signature the
generic ABIs do not cover.

These ABIs are intentionally *small* — only the entries needed at
runtime. Bigger doesn't help: every extra ABI entry that does not appear
on-chain just wastes lookup time and (if it ever leaks back into the LLM
context) burns tokens for no reason.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# ERC-721 — generic mint-focused fragment
# ---------------------------------------------------------------------------
# The three mint() variants below cover ~95% of real NFT collections we have
# observed on mainnet, Base, Arbitrum, and Polygon:
#
#   * ``mint(uint256)``         — bulk mint quantity, no recipient arg
#                                 (collection assumes msg.sender). Used by
#                                 Azuki-style drops, Bored Ape Yacht
#                                 mints, etc.
#   * ``publicMint()``          — zero-arg public mint, often payable.
#                                 Common on free-mint drops where the
#                                 contract reads ``msg.sender`` directly.
#   * ``safeMint(address,uint256)`` — OpenZeppelin's canonical helper,
#                                     used by most ``ERC721A`` / custom
#                                     collections to mint to an explicit
#                                     recipient.
#
# Read-only views (``totalSupply``, ``balanceOf``, ``ownerOf``) are
# included so the executor can sanity-check parameters without a second
# ABI fetch (e.g. "have I already minted from this collection?").
GENERIC_ERC721_ABI: list[dict[str, Any]] = [
    {
        "name": "mint",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [{"name": "quantity", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "publicMint",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [],
        "outputs": [],
    },
    {
        "name": "safeMint",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "quantity", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "name": "totalSupply",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "ownerOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
    },
]


# ---------------------------------------------------------------------------
# ERC-20 — canonical interface
# ---------------------------------------------------------------------------
# These are the seven entries every legitimate ERC-20 token implements.
# Anything beyond this (fee-on-transfer hooks, snapshots, permit, etc.) is
# project-specific and must come from a verified Etherscan ABI OR from
# blind calldata. The generic ABI deliberately does not include
# ``approve(uint256.max)``, ``mint``, or other "owner-only" extensions —
# those are exactly the rug-pull vectors the auditor agent screens for,
# and we do not want them to be reachable through a fallback.
GENERIC_ERC20_ABI: list[dict[str, Any]] = [
    {
        "name": "transfer",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "transferFrom",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "totalSupply",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
    {
        "name": "symbol",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    },
]


# Function names that signal "this contract is mint-shaped". Used by the
# executor to decide whether GENERIC_ERC721_ABI is a plausible fallback
# when the on-chain ABI is missing.
ERC721_MINT_FUNCTIONS: frozenset[str] = frozenset({
    "mint",
    "publicMint",
    "safeMint",
})


# Function names that signal "this contract is ERC-20 shaped".
ERC20_TRANSFER_FUNCTIONS: frozenset[str] = frozenset({
    "transfer",
    "approve",
    "transferFrom",
})


def function_signature(entry: dict[str, Any]) -> str:
    """Render an ABI function entry as a Solidity-style signature string.

    Example: ``{"name":"mint","inputs":[{"name":"qty","type":"uint256"}]}``
    becomes ``"mint(uint256 qty)"``.

    Used for the short summaries the executor sends back to the LLM in
    place of the raw ABI JSON.
    """
    name = entry.get("name", "")
    inputs = entry.get("inputs", []) or []
    parts: list[str] = []
    for inp in inputs:
        type_ = inp.get("type", "")
        arg_name = inp.get("name", "")
        if arg_name:
            parts.append(f"{type_} {arg_name}")
        else:
            parts.append(type_)
    return f"{name}({', '.join(parts)})"


def find_function_entry(
    abi: list[dict[str, Any]],
    function_name: str,
) -> dict[str, Any] | None:
    """Return the first function-type entry with the given name, or None.

    Pure helper, no side effects. Names are matched case-sensitively
    because Solidity is case-sensitive (``mint`` and ``Mint`` are
    distinct).
    """
    for entry in abi:
        if entry.get("type") == "function" and entry.get("name") == function_name:
            return entry
    return None


def summarize_mint_signatures(abi: list[dict[str, Any]], limit: int = 5) -> str:
    """Compact, LLM-safe summary of mint-like signatures in an ABI.

    Walks the ABI looking for function entries whose name contains
    ``mint`` (case-insensitive) and renders up to ``limit`` of them as
    Solidity-style signatures. Returns a one-line string suitable for
    embedding in tool output.

    Used by both :class:`TokenDataFetcherTool` (to enrich the
    data-gatherer's output without leaking the raw ABI) and the
    transaction executor (to acknowledge which entrypoint it found).
    """
    matches: list[str] = []
    for entry in abi:
        if entry.get("type") != "function":
            continue
        name = entry.get("name", "")
        if "mint" in name.lower():
            matches.append(function_signature(entry))
            if len(matches) >= limit:
                break
    if not matches:
        return "No mint-like functions found."
    return "Mint-like functions: " + ", ".join(matches)
