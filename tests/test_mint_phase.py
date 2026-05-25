"""Tests for the read-only mint phase prober."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from eth_abi import encode as abi_encode
from web3 import Web3
from web3.exceptions import ContractLogicError

from web3_crew.tools.mint_phase import (
    PhaseProbeResult,
    _fmt_duration,
    probe_mint_phase,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_w3(responses: dict[bytes, bytes]) -> MagicMock:
    """Build a mock web3 where eth.call returns canned responses by selector.

    Selectors are 4-byte prefixes. ``responses`` keys are the full selector
    bytes; an unknown selector raises ContractLogicError (simulating a
    revert).
    """
    w3 = MagicMock()

    def fake_call(tx: dict) -> bytes:
        data = tx["data"]
        if isinstance(data, str):
            data = bytes.fromhex(data.removeprefix("0x"))
        selector = data[:4]
        if selector not in responses:
            raise ContractLogicError("revert: function not found")
        return responses[selector]

    w3.eth.call.side_effect = fake_call
    return w3


def _selector(sig: str) -> bytes:
    return Web3.keccak(text=sig)[:4]


CONTRACT = "0x" + "ab" * 20


# ---------------------------------------------------------------------------
# Probe behavior
# ---------------------------------------------------------------------------


def test_schema_unknown_when_all_probes_revert() -> None:
    w3 = _make_w3(responses={})  # every selector reverts
    result = probe_mint_phase(w3, CONTRACT)
    assert result.schema_unknown is True
    assert result.active is None
    assert result.price_wei is None


def test_finds_simple_active_and_price() -> None:
    w3 = _make_w3(
        responses={
            _selector("mintActive()"): abi_encode(["bool"], [True]),
            _selector("mintPrice()"): abi_encode(["uint256"], [3 * 10**14]),  # 0.0003 ETH
            _selector("totalSupply()"): abi_encode(["uint256"], [1566]),
            _selector("maxSupply()"): abi_encode(["uint256"], [4999]),
        }
    )
    result = probe_mint_phase(w3, CONTRACT)
    assert result.active is True
    assert result.price_wei == 3 * 10**14
    assert result.price_eth is not None
    assert abs(result.price_eth - 0.0003) < 1e-9
    assert result.total_supply == 1566
    assert result.max_supply == 4999
    assert result.is_open is True
    assert result.schema_unknown is False


def test_first_probe_in_group_wins_subsequent_not_tried() -> None:
    """If mintActive() hits, saleIsActive() should not even be tried."""
    w3 = _make_w3(
        responses={
            _selector("mintActive()"): abi_encode(["bool"], [True]),
            # We do NOT add saleIsActive — but it should never be called.
        }
    )
    probe_mint_phase(w3, CONTRACT)
    called_selectors = [
        c.args[0]["data"][:4] for c in w3.eth.call.call_args_list
    ]
    assert _selector("mintActive()") in called_selectors
    assert _selector("saleIsActive()") not in called_selectors


def test_is_open_false_when_paused() -> None:
    w3 = _make_w3(
        responses={
            _selector("paused()"): abi_encode(["bool"], [True]),
        }
    )
    result = probe_mint_phase(w3, CONTRACT)
    assert result.paused is True
    assert result.is_open is False


def test_is_open_false_when_start_in_future() -> None:
    future = int(time.time()) + 3600
    w3 = _make_w3(
        responses={
            _selector("publicSaleStart()"): abi_encode(["uint256"], [future]),
        }
    )
    result = probe_mint_phase(w3, CONTRACT)
    assert result.start_at == future
    assert result.is_open is False
    assert result.seconds_until_open is not None
    assert 3500 < result.seconds_until_open <= 3600


def test_per_address_probes_skipped_without_user() -> None:
    w3 = _make_w3(responses={})
    probe_mint_phase(w3, CONTRACT, user_address=None)
    selectors_called = [
        c.args[0]["data"][:4] for c in w3.eth.call.call_args_list
    ]
    assert _selector("numberMinted(address)") not in selectors_called


def test_per_address_probes_run_with_user() -> None:
    user = "0x" + "cd" * 20
    w3 = _make_w3(
        responses={
            _selector("numberMinted(address)"): abi_encode(["uint256"], [3]),
        }
    )
    result = probe_mint_phase(w3, CONTRACT, user_address=user)
    assert result.user_minted == 3


def test_summary_string_when_schema_unknown() -> None:
    w3 = _make_w3(responses={})
    result = probe_mint_phase(w3, CONTRACT)
    text = result.summary()
    assert "schema unknown" in text
    assert CONTRACT.lower() in text.lower()


def test_summary_shows_remaining_supply() -> None:
    w3 = _make_w3(
        responses={
            _selector("totalSupply()"): abi_encode(["uint256"], [100]),
            _selector("maxSupply()"): abi_encode(["uint256"], [500]),
        }
    )
    text = probe_mint_phase(w3, CONTRACT).summary()
    assert "100/500" in text
    assert "400 remaining" in text


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


def test_phase_probe_result_defaults() -> None:
    r = PhaseProbeResult(address=CONTRACT)
    assert r.is_open is None  # no signals
    assert r.price_eth is None
    assert r.seconds_until_open is None


def test_fmt_duration_human_readable() -> None:
    assert _fmt_duration(-1) == "now"
    assert _fmt_duration(0) == "now"
    assert _fmt_duration(45) == "45s"
    assert _fmt_duration(90) == "1m 30s"
    assert _fmt_duration(7200) == "2h 0m"
    assert _fmt_duration(90000) == "1d 1h"
