"""Tests for the eligibility checker (phase + allowlist + per-wallet)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from eth_abi import encode as abi_encode
from web3 import Web3
from web3.exceptions import ContractLogicError

from web3_crew.tools.eligibility import check_eligibility


def _make_w3(responses: dict[bytes, bytes]) -> MagicMock:
    w3 = MagicMock()

    def fake_call(tx: dict) -> bytes:
        data = tx["data"]
        if isinstance(data, str):
            data = bytes.fromhex(data.removeprefix("0x"))
        selector = data[:4]
        if selector not in responses:
            raise ContractLogicError("revert")
        return responses[selector]

    w3.eth.call.side_effect = fake_call
    return w3


def _sel(sig: str) -> bytes:
    return Web3.keccak(text=sig)[:4]


CONTRACT = "0x" + "ab" * 20
USER = "0x" + "cd" * 20


def test_not_eligible_when_mint_paused() -> None:
    w3 = _make_w3(responses={_sel("paused()"): abi_encode(["bool"], [True])})
    v = check_eligibility(w3, CONTRACT, USER)
    assert v.eligible is False
    assert "paused" in v.reason.lower()


def test_not_eligible_when_sale_not_started() -> None:
    future = int(time.time()) + 1800
    w3 = _make_w3(
        responses={_sel("publicSaleStart()"): abi_encode(["uint256"], [future])}
    )
    v = check_eligibility(w3, CONTRACT, USER)
    assert v.eligible is False
    assert "not open yet" in v.reason


def test_not_eligible_when_wallet_cap_exceeded() -> None:
    w3 = _make_w3(
        responses={
            _sel("mintActive()"): abi_encode(["bool"], [True]),
            _sel("maxPerWallet()"): abi_encode(["uint256"], [2]),
            _sel("numberMinted(address)"): abi_encode(["uint256"], [2]),
        }
    )
    v = check_eligibility(w3, CONTRACT, USER, requested_qty=1)
    assert v.eligible is False
    assert "cap" in v.reason.lower()
    assert v.remaining_for_wallet == 0


def test_eligible_when_room_left_under_cap() -> None:
    w3 = _make_w3(
        responses={
            _sel("mintActive()"): abi_encode(["bool"], [True]),
            _sel("maxPerWallet()"): abi_encode(["uint256"], [5]),
            _sel("numberMinted(address)"): abi_encode(["uint256"], [2]),
        }
    )
    v = check_eligibility(w3, CONTRACT, USER, requested_qty=2)
    assert v.eligible is True
    assert v.remaining_for_wallet == 3


def test_not_eligible_when_sold_out() -> None:
    w3 = _make_w3(
        responses={
            _sel("mintActive()"): abi_encode(["bool"], [True]),
            _sel("totalSupply()"): abi_encode(["uint256"], [4999]),
            _sel("maxSupply()"): abi_encode(["uint256"], [4999]),
        }
    )
    v = check_eligibility(w3, CONTRACT, USER, requested_qty=1)
    assert v.eligible is False
    assert "sold out" in v.reason.lower()


def test_needs_proof_when_merkle_root_set() -> None:
    nonzero_root = b"\x01" * 32
    w3 = _make_w3(
        responses={
            _sel("mintActive()"): abi_encode(["bool"], [True]),
            _sel("merkleRoot()"): abi_encode(["bytes32"], [nonzero_root]),
        }
    )
    v = check_eligibility(w3, CONTRACT, USER)
    assert v.eligible is False
    assert "merkle" in v.reason.lower() or "proof" in v.reason.lower()
    assert v.allowlist_status == "needs_proof"


def test_not_eligible_when_allowlist_bool_returns_false() -> None:
    w3 = _make_w3(
        responses={
            _sel("mintActive()"): abi_encode(["bool"], [True]),
            _sel("isAllowlisted(address)"): abi_encode(["bool"], [False]),
        }
    )
    v = check_eligibility(w3, CONTRACT, USER)
    assert v.eligible is False
    assert "allowlist" in v.reason.lower()
    assert v.allowlist_status == "no"


def test_eligible_when_allowlist_bool_true() -> None:
    w3 = _make_w3(
        responses={
            _sel("mintActive()"): abi_encode(["bool"], [True]),
            _sel("isAllowlisted(address)"): abi_encode(["bool"], [True]),
        }
    )
    v = check_eligibility(w3, CONTRACT, USER)
    assert v.eligible is True
    assert v.allowlist_status == "yes"


def test_zero_merkle_root_does_not_block() -> None:
    """An all-zero merkle root means allowlist not configured -- allow."""
    w3 = _make_w3(
        responses={
            _sel("mintActive()"): abi_encode(["bool"], [True]),
            _sel("merkleRoot()"): abi_encode(["bytes32"], [b"\x00" * 32]),
        }
    )
    v = check_eligibility(w3, CONTRACT, USER)
    assert v.eligible is True
    assert v.allowlist_status != "needs_proof"


def test_summary_includes_reason_and_remaining() -> None:
    w3 = _make_w3(
        responses={
            _sel("mintActive()"): abi_encode(["bool"], [True]),
            _sel("maxPerWallet()"): abi_encode(["uint256"], [5]),
            _sel("numberMinted(address)"): abi_encode(["uint256"], [1]),
        }
    )
    text = check_eligibility(w3, CONTRACT, USER).summary()
    assert "ELIGIBLE" in text
    assert "remaining_for_wallet: 4" in text
