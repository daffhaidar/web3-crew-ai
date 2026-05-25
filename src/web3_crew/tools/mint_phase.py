"""Read-only NFT mint phase + supply prober.

Most NFT collections expose a small set of view functions that, together,
fully describe whether minting is currently possible: is the sale open,
what does it cost, when does it start, how many have already minted, and
what is the per-wallet cap. There is **no standard** for these — names
vary across projects (``mintActive``, ``saleIsActive``, ``isPublicSale``,
``mintPhase``, ``currentPhase`` ...) — so this module probes the most
common signatures and returns whatever fires.

It is intentionally **read-only**: every call goes through ``eth_call``,
never broadcasts a transaction, and never touches the wallet private key.
Safe to run on any contract address without funds at risk.

Design notes
------------
* The probe list is deliberately bounded (~25 functions). If none match
  we return a "schema unknown" result so the bot can tell the user
  honestly rather than halu-halu fabricate phase info.
* All probes are wrapped in try/except — a single revert / decode error
  must not nuke the whole probe.
* No external services involved (no Etherscan, no Alchemy). Everything
  comes from ``eth_call`` on the configured RPC.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Final

from eth_abi import decode as abi_decode
from web3 import Web3
from web3.exceptions import BadFunctionCallOutput, ContractLogicError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Probe definitions
# ---------------------------------------------------------------------------
# Each entry: (function_signature, return_abi_types, semantic_key).
# Probes are tried in order; the first non-reverting result wins per key.
#
# semantic_key groups probes that mean the same thing -- e.g. ``saleIsActive``
# and ``mintActive`` both populate the ``active`` slot. Once a key is
# populated we skip the rest of its group on the next iteration.

_NO_ARG_PROBES: Final[list[tuple[str, list[str], str]]] = [
    # is-active bool probes
    ("mintActive()", ["bool"], "active"),
    ("mintEnabled()", ["bool"], "active"),
    ("saleIsActive()", ["bool"], "active"),
    ("isMintActive()", ["bool"], "active"),
    ("isPublicSaleActive()", ["bool"], "active"),
    ("publicSaleActive()", ["bool"], "active"),
    ("isPublicSale()", ["bool"], "active"),
    # paused bool probe (semantically inverted -- handled at use-site)
    ("paused()", ["bool"], "paused"),
    # phase enum probes (0=closed, 1=allowlist, 2=public, by convention)
    ("currentPhase()", ["uint256"], "phase"),
    ("mintPhase()", ["uint256"], "phase"),
    ("phase()", ["uint256"], "phase"),
    ("stage()", ["uint256"], "phase"),
    # price probes (wei)
    ("mintPrice()", ["uint256"], "price_wei"),
    ("price()", ["uint256"], "price_wei"),
    ("cost()", ["uint256"], "price_wei"),
    ("PRICE()", ["uint256"], "price_wei"),
    ("publicSalePrice()", ["uint256"], "price_wei"),
    # start time (unix seconds)
    ("publicSaleStart()", ["uint256"], "start_at"),
    ("mintStartTime()", ["uint256"], "start_at"),
    ("startTime()", ["uint256"], "start_at"),
    ("saleStart()", ["uint256"], "start_at"),
    ("publicMintStart()", ["uint256"], "start_at"),
    # total / max supply
    ("totalSupply()", ["uint256"], "total_supply"),
    ("maxSupply()", ["uint256"], "max_supply"),
    ("MAX_SUPPLY()", ["uint256"], "max_supply"),
    ("collectionSize()", ["uint256"], "max_supply"),
    # per-wallet cap
    ("maxPerWallet()", ["uint256"], "max_per_wallet"),
    ("maxMintPerWallet()", ["uint256"], "max_per_wallet"),
    ("MAX_PER_WALLET()", ["uint256"], "max_per_wallet"),
    ("maxMintsPerAddress()", ["uint256"], "max_per_wallet"),
]

_ADDR_ARG_PROBES: Final[list[tuple[str, list[str], str]]] = [
    # per-address mint count
    ("numberMinted(address)", ["uint256"], "user_minted"),
    ("mintedBy(address)", ["uint256"], "user_minted"),
    ("mintsPerWallet(address)", ["uint256"], "user_minted"),
    ("_numberMinted(address)", ["uint256"], "user_minted"),
    ("balanceOf(address)", ["uint256"], "user_balance"),
]


@dataclass
class PhaseProbeResult:
    """Aggregated result from probing a contract.

    Empty fields = probe couldn't find a matching function. Use
    :meth:`summary` for a human-readable string suitable for Telegram.
    """

    address: str
    active: bool | None = None
    paused: bool | None = None
    phase: int | None = None
    price_wei: int | None = None
    start_at: int | None = None
    total_supply: int | None = None
    max_supply: int | None = None
    max_per_wallet: int | None = None
    user_minted: int | None = None
    user_balance: int | None = None
    probes_hit: list[str] = field(default_factory=list)
    probes_tried: int = 0
    schema_unknown: bool = False

    @property
    def price_eth(self) -> float | None:
        if self.price_wei is None:
            return None
        return self.price_wei / 1e18

    @property
    def is_open(self) -> bool | None:
        """Best guess if minting is currently open. None = can't tell."""
        if self.paused is True:
            return False
        if self.active is False:
            return False
        if self.start_at is not None and self.start_at > int(time.time()):
            return False
        if self.active is True or self.phase == 2:
            return True
        # If we have a start_at in the past and no explicit "active" flag,
        # cautiously assume open.
        if self.start_at is not None and self.start_at <= int(time.time()):
            return True
        return None

    @property
    def seconds_until_open(self) -> int | None:
        if self.start_at is None:
            return None
        delta = self.start_at - int(time.time())
        return max(0, delta)

    def summary(self) -> str:
        lines: list[str] = [f"Mint phase probe -> {self.address}"]
        if self.schema_unknown:
            lines.append(
                "  schema unknown -- contract does not expose common phase "
                "view functions. Proceed manually."
            )
            return "\n".join(lines)

        # Status
        is_open = self.is_open
        if is_open is True:
            lines.append("  status: OPEN")
        elif is_open is False:
            if self.paused is True:
                lines.append("  status: PAUSED")
            elif self.start_at is not None:
                wait = self.seconds_until_open or 0
                lines.append(f"  status: CLOSED -- opens in {_fmt_duration(wait)}")
            else:
                lines.append("  status: CLOSED")
        else:
            lines.append("  status: UNKNOWN (no active/paused/start flag found)")

        if self.phase is not None:
            lines.append(f"  phase: {self.phase}")
        if self.price_eth is not None:
            lines.append(f"  price: {self.price_eth:.6f} ETH ({self.price_wei} wei)")
        if self.start_at is not None:
            lines.append(f"  start_at: {self.start_at} (unix UTC)")
        if self.total_supply is not None and self.max_supply is not None:
            remaining = max(0, self.max_supply - self.total_supply)
            lines.append(
                f"  supply: {self.total_supply}/{self.max_supply} minted, "
                f"{remaining} remaining"
            )
        elif self.total_supply is not None:
            lines.append(f"  total_minted: {self.total_supply}")
        if self.max_per_wallet is not None:
            lines.append(f"  max_per_wallet: {self.max_per_wallet}")
        if self.user_minted is not None:
            lines.append(f"  you_minted: {self.user_minted}")
        elif self.user_balance is not None:
            lines.append(f"  your_balance (ERC721A proxy): {self.user_balance}")
        lines.append(f"  probes_hit: {len(self.probes_hit)} / {self.probes_tried}")
        return "\n".join(lines)


def probe_mint_phase(
    w3: Web3,
    contract_address: str,
    *,
    user_address: str | None = None,
) -> PhaseProbeResult:
    """Probe ``contract_address`` for common mint-phase view functions.

    All calls go through ``eth_call`` -- this never sends a transaction
    and never costs gas. Wallet credentials are not used.

    :param w3: Web3 client (must be connected).
    :param contract_address: Contract to probe (checksummed or lowercased).
    :param user_address: Optional wallet to query per-address probes
        (``numberMinted``, ``balanceOf``). Skip per-address probes when
        ``None``.
    """
    addr = Web3.to_checksum_address(contract_address)
    result = PhaseProbeResult(address=addr)
    populated: set[str] = set()

    for sig, ret_types, key in _NO_ARG_PROBES:
        if key in populated:
            continue
        result.probes_tried += 1
        value = _probe_view(w3, addr, sig, ret_types, args=b"")
        if value is None:
            continue
        result.probes_hit.append(sig)
        _assign(result, key, value)
        populated.add(key)

    if user_address is not None:
        user_addr = Web3.to_checksum_address(user_address)
        # ABI-encode the address as a 32-byte left-padded word.
        addr_arg = bytes.fromhex("00" * 12 + user_addr[2:].lower())
        for sig, ret_types, key in _ADDR_ARG_PROBES:
            if key in populated:
                continue
            result.probes_tried += 1
            value = _probe_view(w3, addr, sig, ret_types, args=addr_arg)
            if value is None:
                continue
            result.probes_hit.append(sig)
            _assign(result, key, value)
            populated.add(key)

    # If nothing hit at all, mark schema as unknown so the caller can tell
    # the user honestly rather than infer bogus state from empty fields.
    if not result.probes_hit:
        result.schema_unknown = True

    return result


def _probe_view(
    w3: Web3,
    contract_addr: str,
    signature: str,
    return_types: list[str],
    *,
    args: bytes,
) -> int | bool | None:
    """Call a view function. Returns decoded value or None on revert/decode error."""
    try:
        selector = Web3.keccak(text=signature)[:4]
        data = selector + args
        raw = w3.eth.call({"to": contract_addr, "data": data})
        if not raw:
            return None
        decoded = abi_decode(return_types, raw)
        if not decoded:
            return None
        return decoded[0]
    except (ContractLogicError, BadFunctionCallOutput, ValueError):
        return None
    except Exception as exc:  # pragma: no cover -- defensive
        logger.debug("Probe %s on %s failed: %s", signature, contract_addr, exc)
        return None


def _assign(result: PhaseProbeResult, key: str, value: object) -> None:
    """Set the appropriate field on ``result`` based on the semantic key."""
    if key == "active" and isinstance(value, bool):
        result.active = value
    elif key == "paused" and isinstance(value, bool):
        result.paused = value
    elif key == "phase" and isinstance(value, int):
        result.phase = value
    elif key == "price_wei" and isinstance(value, int):
        result.price_wei = value
    elif key == "start_at" and isinstance(value, int):
        result.start_at = value
    elif key == "total_supply" and isinstance(value, int):
        result.total_supply = value
    elif key == "max_supply" and isinstance(value, int):
        result.max_supply = value
    elif key == "max_per_wallet" and isinstance(value, int):
        result.max_per_wallet = value
    elif key == "user_minted" and isinstance(value, int):
        result.user_minted = value
    elif key == "user_balance" and isinstance(value, int):
        result.user_balance = value


def _fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "now"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"
