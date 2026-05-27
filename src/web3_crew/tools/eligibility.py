"""Mint eligibility checker.

Builds on :mod:`web3_crew.tools.mint_phase` to answer "can wallet X mint
N tokens right now?". Combines per-wallet limit + already-minted count
+ allowlist presence to produce a yes/no/needs-proof verdict.

Allowlist policy
----------------
Many modern NFT collections gate mint phases behind a Merkle proof
(``mintAllowlist(bytes32[] proof, ...)``). Generating a valid proof
requires the **entire** allowlist tree, which is published off-chain
(usually on Vercel/IPFS/Arweave). This bot does not scrape allowlist
trees, so allowlist-gated mints are *honestly reported as unsupported*
rather than silently failing later.

If a contract exposes a plain ``isAllowlisted(address) -> bool`` view
without proof requirements, we read it. Most modern collections do NOT
expose this (they only validate the proof at mint time), so this check
is best-effort.
"""

from __future__ import annotations

from dataclasses import dataclass

from web3 import Web3

from web3_crew.tools.mint_phase import PhaseProbeResult, _probe_view, probe_mint_phase


@dataclass
class EligibilityVerdict:
    eligible: bool
    reason: str
    remaining_for_wallet: int | None = None
    phase_result: PhaseProbeResult | None = None
    allowlist_status: str | None = None  # "yes" | "no" | "unknown" | "needs_proof"

    def summary(self) -> str:
        verdict = "ELIGIBLE" if self.eligible else "NOT ELIGIBLE"
        lines = [f"Eligibility: {verdict}", f"  reason: {self.reason}"]
        if self.remaining_for_wallet is not None:
            lines.append(f"  remaining_for_wallet: {self.remaining_for_wallet}")
        if self.allowlist_status:
            lines.append(f"  allowlist: {self.allowlist_status}")
        return "\n".join(lines)


# Allowlist probes that take an address argument and return bool.
_ALLOWLIST_BOOL_PROBES: tuple[str, ...] = (
    "isAllowlisted(address)",
    "isWhitelisted(address)",
    "allowlisted(address)",
    "whitelisted(address)",
)

# Probes for *presence* of a merkle root -- if the contract publishes a
# merkle root, allowlist mint requires an off-chain proof we can't build.
_MERKLE_ROOT_PROBES: tuple[str, ...] = (
    "merkleRoot()",
    "allowlistMerkleRoot()",
    "whitelistMerkleRoot()",
)


def check_eligibility(
    w3: Web3,
    contract_address: str,
    user_address: str,
    *,
    requested_qty: int = 1,
) -> EligibilityVerdict:
    """Decide whether ``user_address`` can mint ``requested_qty`` tokens.

    Combines phase probe + per-wallet limit + allowlist probe.

    The verdict is conservative: when a signal is missing or ambiguous
    we lean toward "eligible if no blocker found" but report the unknown
    fields in :attr:`EligibilityVerdict.reason`.
    """
    addr = Web3.to_checksum_address(contract_address)
    user = Web3.to_checksum_address(user_address)

    phase = probe_mint_phase(w3, addr, user_address=user)

    # ------------------------------------------------------------------
    # 1. Phase status -- hard gate
    # ------------------------------------------------------------------
    is_open = phase.is_open
    if is_open is False:
        if phase.paused is True:
            reason = "mint is paused"
        elif phase.start_at is not None:
            reason = (
                f"mint not open yet -- starts at unix {phase.start_at} "
                f"(in {phase.seconds_until_open}s)"
            )
        else:
            reason = "mint is closed"
        return EligibilityVerdict(
            eligible=False,
            reason=reason,
            phase_result=phase,
        )

    # ------------------------------------------------------------------
    # 2. Per-wallet limit
    # ------------------------------------------------------------------
    remaining: int | None = None
    if phase.max_per_wallet is not None:
        already = phase.user_minted if phase.user_minted is not None else 0
        remaining = max(0, phase.max_per_wallet - already)
        if remaining < requested_qty:
            return EligibilityVerdict(
                eligible=False,
                reason=(
                    f"wallet cap exceeded -- limit {phase.max_per_wallet}, "
                    f"already minted {already}, requested {requested_qty}"
                ),
                remaining_for_wallet=remaining,
                phase_result=phase,
            )

    # ------------------------------------------------------------------
    # 3. Supply cap
    # ------------------------------------------------------------------
    if phase.max_supply is not None and phase.total_supply is not None:
        supply_left = phase.max_supply - phase.total_supply
        if supply_left < requested_qty:
            return EligibilityVerdict(
                eligible=False,
                reason=(
                    f"sold out -- {phase.total_supply}/{phase.max_supply} minted, "
                    f"only {max(0, supply_left)} left, requested {requested_qty}"
                ),
                remaining_for_wallet=remaining,
                phase_result=phase,
            )

    # ------------------------------------------------------------------
    # 4. Allowlist signal (best-effort)
    # ------------------------------------------------------------------
    allowlist_status = _probe_allowlist(w3, addr, user)

    if allowlist_status == "needs_proof":
        return EligibilityVerdict(
            eligible=False,
            reason=(
                "contract publishes a Merkle root for allowlist mint -- "
                "off-chain proof required, not supported by this bot"
            ),
            remaining_for_wallet=remaining,
            phase_result=phase,
            allowlist_status="needs_proof",
        )

    if allowlist_status == "no":
        return EligibilityVerdict(
            eligible=False,
            reason="wallet is not on the allowlist",
            remaining_for_wallet=remaining,
            phase_result=phase,
            allowlist_status="no",
        )

    # ------------------------------------------------------------------
    # 5. Default: eligible
    # ------------------------------------------------------------------
    reason_bits: list[str] = []
    if phase.is_open is True:
        reason_bits.append("mint open")
    if remaining is not None:
        reason_bits.append(f"{remaining} remaining for wallet")
    if allowlist_status == "yes":
        reason_bits.append("allowlisted")
    elif allowlist_status == "unknown":
        reason_bits.append("allowlist gate not detectable (likely public-only)")

    return EligibilityVerdict(
        eligible=True,
        reason="; ".join(reason_bits) or "no blocking signals found",
        remaining_for_wallet=remaining,
        phase_result=phase,
        allowlist_status=allowlist_status,
    )


def _probe_allowlist(w3: Web3, contract_addr: str, user_addr: str) -> str:
    """Return 'yes' | 'no' | 'needs_proof' | 'unknown'."""
    addr_arg = bytes.fromhex("00" * 12 + user_addr[2:].lower())

    for sig in _ALLOWLIST_BOOL_PROBES:
        value = _probe_view(w3, contract_addr, sig, ["bool"], args=addr_arg)
        if value is True:
            return "yes"
        if value is False:
            return "no"

    for sig in _MERKLE_ROOT_PROBES:
        value = _probe_view(w3, contract_addr, sig, ["bytes32"], args=b"")
        if value is None:
            continue
        # Empty merkle root (all zeros) = allowlist not configured.
        if isinstance(value, bytes | bytearray) and any(value):
            return "needs_proof"

    return "unknown"
