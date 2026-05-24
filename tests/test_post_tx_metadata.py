"""Unit tests for the post-tx metadata fetcher.

These tests are the regression suite for the Task-1 mandate:

* The fetcher MUST run strictly after a successful broadcast (verified
  by integration in ``test_safe_transaction_metadata_hook.py``).
* The fetcher MUST never raise — every network / API / parsing failure
  has to land on the same graceful fallback string.
* The LLM-visible payload MUST stay short and structured (no raw
  Alchemy JSON, no oversized strings).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from web3_crew.tools.post_tx_metadata import (
    _coerce_topic_hex,
    _extract_erc721_token_ids,
    _render_summary,
    _truncate,
    fetch_post_tx_metadata,
)

# Canonical ERC-721 Transfer topic0 (keccak256("Transfer(address,address,uint256)")).
_TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _padded(value: int | str, width: int = 64) -> str:
    """Pad a hex value to the 32-byte width used in event topics."""
    if isinstance(value, int):
        hex_str = format(value, "x")
    else:
        hex_str = value[2:] if value.startswith("0x") else value
    return "0x" + hex_str.rjust(width, "0")


def _make_receipt(*, logs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "transactionHash": MagicMock(hex=lambda: "0xdead"),
        "blockNumber": 100,
        "gasUsed": 50_000,
        "status": 1,
        "logs": logs,
    }


def _erc721_transfer_log(*, token_id: int, sender: str = "0x" + "00" * 20) -> dict[str, Any]:
    """A canonical ERC-721 ``Transfer`` log: 4 indexed topics."""
    return {
        "topics": [
            _TRANSFER_TOPIC0,
            _padded(sender),
            _padded("0x" + "ab" * 20),
            _padded(token_id),
        ],
        "data": "0x",
    }


def _erc20_transfer_log(*, amount: int) -> dict[str, Any]:
    """A canonical ERC-20 ``Transfer`` log: 3 topics, value in data."""
    return {
        "topics": [
            _TRANSFER_TOPIC0,
            _padded("0x" + "00" * 20),
            _padded("0x" + "ab" * 20),
        ],
        "data": _padded(amount),
    }


class TestExtractErc721TokenIds:
    """Receipt-log parsing — pure function, no network."""

    def test_returns_token_id_for_single_erc721_log(self) -> None:
        receipt = _make_receipt(logs=[_erc721_transfer_log(token_id=42)])
        assert _extract_erc721_token_ids(receipt) == [42]

    def test_returns_multiple_token_ids_for_batch_mint(self) -> None:
        receipt = _make_receipt(
            logs=[
                _erc721_transfer_log(token_id=1),
                _erc721_transfer_log(token_id=2),
                _erc721_transfer_log(token_id=3),
            ]
        )
        assert _extract_erc721_token_ids(receipt) == [1, 2, 3]

    def test_ignores_erc20_transfer_logs(self) -> None:
        # 3-topic Transfer log = ERC-20, not an NFT mint.
        receipt = _make_receipt(logs=[_erc20_transfer_log(amount=1000)])
        assert _extract_erc721_token_ids(receipt) == []

    def test_ignores_unrelated_topics(self) -> None:
        receipt = _make_receipt(
            logs=[
                {
                    "topics": [
                        "0x" + "ff" * 32,
                        _padded(0),
                        _padded(0),
                        _padded(7),
                    ],
                    "data": "0x",
                }
            ]
        )
        assert _extract_erc721_token_ids(receipt) == []

    def test_empty_logs_returns_empty(self) -> None:
        assert _extract_erc721_token_ids(_make_receipt(logs=[])) == []

    def test_malformed_log_skipped_silently(self) -> None:
        # Log with completely broken shape — must NOT raise, must NOT
        # poison the rest of the list.
        receipt = _make_receipt(
            logs=[
                {"topics": None},
                _erc721_transfer_log(token_id=99),
            ]
        )
        assert _extract_erc721_token_ids(receipt) == [99]

    def test_handles_hexbytes_topics(self) -> None:
        """web3.py returns topics as HexBytes — make sure we coerce."""
        class _HexBytes(bytes):
            def hex(self) -> str:  # type: ignore[override]
                return super().hex()

        log = {
            "topics": [
                _HexBytes.fromhex(_TRANSFER_TOPIC0[2:]),
                _HexBytes.fromhex("00" * 32),
                _HexBytes.fromhex("00" * 32),
                _HexBytes.fromhex("00" * 31 + "07"),
            ],
            "data": "0x",
        }
        assert _extract_erc721_token_ids(_make_receipt(logs=[log])) == [7]


class TestCoerceTopicHex:
    """Topic-format coercion handles every web3.py shape we see in the wild."""

    def test_string_with_prefix(self) -> None:
        assert _coerce_topic_hex("0xabc") == "0xabc"

    def test_string_without_prefix(self) -> None:
        assert _coerce_topic_hex("abc") == "0xabc"

    def test_bytes(self) -> None:
        assert _coerce_topic_hex(b"\x01\x02") == "0x0102"


class TestGracefulDegradation:
    """The fetcher must never raise; every failure mode is a fallback."""

    def test_empty_contract_address(self) -> None:
        result = fetch_post_tx_metadata(
            receipt=_make_receipt(logs=[]),
            contract_address="",
            chain_id=1,
        )
        assert result["metadata_status"] == "skipped"
        summary_lower = result["metadata_summary"].lower()
        assert "failed" in summary_lower or "pending" in summary_lower

    def test_no_alchemy_key_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "web3_crew.tools.post_tx_metadata.settings.alchemy_api_key", ""
        )
        result = fetch_post_tx_metadata(
            receipt=_make_receipt(logs=[_erc721_transfer_log(token_id=42)]),
            contract_address="0x" + "cd" * 20,
            chain_id=1,
        )
        assert result["metadata_status"] == "fallback"
        # Even without Alchemy, OpenSea + Etherscan links must appear.
        assert "etherscan.io" in result["metadata_summary"]
        assert "opensea.io" in result["metadata_summary"]
        # And the token id we extracted must be rendered.
        assert "42" in result["metadata_summary"]

    def test_alchemy_http_error_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "web3_crew.tools.post_tx_metadata.settings.alchemy_api_key", "dummy"
        )

        class _BoomClient:
            def __enter__(self) -> Any:
                return self

            def __exit__(self, *args: Any) -> bool:
                return False

            def get(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("Alchemy unreachable")

        result = fetch_post_tx_metadata(
            receipt=_make_receipt(logs=[_erc721_transfer_log(token_id=7)]),
            contract_address="0x" + "cd" * 20,
            chain_id=1,
            http_client_factory=_BoomClient,
        )
        # Must NOT raise; metadata_status drops to fallback.
        assert result["metadata_status"] == "fallback"
        assert "etherscan.io" in result["metadata_summary"]
        assert "opensea.io" in result["metadata_summary"]
        assert "7" in result["metadata_summary"]

    def test_alchemy_404_response_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "web3_crew.tools.post_tx_metadata.settings.alchemy_api_key", "dummy"
        )

        class _NotFoundClient:
            def __enter__(self) -> Any:
                return self

            def __exit__(self, *args: Any) -> bool:
                return False

            def get(self, *args: Any, **kwargs: Any) -> MagicMock:
                resp = MagicMock()
                resp.status_code = 404
                return resp

        result = fetch_post_tx_metadata(
            receipt=_make_receipt(logs=[_erc721_transfer_log(token_id=7)]),
            contract_address="0x" + "cd" * 20,
            chain_id=1,
            http_client_factory=_NotFoundClient,
        )
        assert result["metadata_status"] == "fallback"

    def test_unsupported_chain_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "web3_crew.tools.post_tx_metadata.settings.alchemy_api_key", "dummy"
        )
        # Chain 999999 is not in _ALCHEMY_NFT_BASE nor _OPENSEA_CHAIN_SLUG.
        result = fetch_post_tx_metadata(
            receipt=_make_receipt(logs=[_erc721_transfer_log(token_id=1)]),
            contract_address="0x" + "cd" * 20,
            chain_id=999999,
        )
        assert result["metadata_status"] == "fallback"
        # Etherscan (default domain) is still surfaced; OpenSea is not.
        assert "etherscan.io" in result["metadata_summary"]
        assert "opensea.io" not in result["metadata_summary"]


class TestAlchemyHappyPath:
    """When Alchemy returns a valid NFT body the summary should include the name."""

    def test_renders_name_collection_and_links(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "web3_crew.tools.post_tx_metadata.settings.alchemy_api_key", "dummy"
        )

        @contextmanager
        def _ok_client() -> Any:
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(
                return_value={
                    "name": "UNIX Punk #42",
                    "description": "A rare punk.",
                    "image": {"originalUrl": "https://nft.example/punk/42.png"},
                    "contract": {"name": "UNIX Punks"},
                    "raw": {"metadata": {}},
                }
            )
            client = MagicMock()
            client.get = MagicMock(return_value=resp)
            yield client

        result = fetch_post_tx_metadata(
            receipt=_make_receipt(logs=[_erc721_transfer_log(token_id=42)]),
            contract_address="0x" + "cd" * 20,
            chain_id=1,
            http_client_factory=_ok_client,
        )
        assert result["metadata_status"] == "ok"
        assert "UNIX Punk #42" in result["metadata_summary"]
        assert "UNIX Punks" in result["metadata_summary"]
        assert "42" in result["metadata_summary"]
        # Direct asset URL on OpenSea.
        assert "/0x" + "cd" * 20 + "/42" in result["metadata_summary"]


class TestRenderSummary:
    """Pure-function rendering of the HTML snippet."""

    def test_html_is_escaped(self) -> None:
        # Malicious name should not produce raw HTML tags.
        summary = _render_summary(
            contract_address="0x" + "ab" * 20,
            token_ids=[1],
            chain_id=1,
            nft_meta={"name": "<script>alert(1)</script>", "collection_name": ""},
        )
        assert "<script>" not in summary
        assert "&lt;script&gt;" in summary

    def test_caps_displayed_token_ids_at_five(self) -> None:
        summary = _render_summary(
            contract_address="0x" + "ab" * 20,
            token_ids=list(range(1, 11)),  # 10 ids
            chain_id=1,
            nft_meta=None,
        )
        # First 5 listed, rest summarised.
        for n in (1, 2, 3, 4, 5):
            assert str(n) in summary
        assert "+5 more" in summary

    def test_no_token_no_meta_uses_pending_prefix(self) -> None:
        summary = _render_summary(
            contract_address="0x" + "ab" * 20,
            token_ids=[],
            chain_id=1,
            nft_meta=None,
        )
        assert "pending" in summary.lower()
        # Still must include the collection-level OpenSea link.
        assert "opensea.io/assets/ethereum/0x" in summary

    def test_summary_length_bounded(self) -> None:
        """Even with worst-case names + ids the summary stays < 1 KB."""
        summary = _render_summary(
            contract_address="0x" + "ab" * 20,
            token_ids=[i for i in range(20)],
            chain_id=1,
            nft_meta={"name": "x" * 200, "collection_name": "y" * 200},
        )
        assert len(summary) < 1024


class TestTruncate:
    def test_short_passthrough(self) -> None:
        assert _truncate("hi", 10) == "hi"

    def test_long_truncated_with_ellipsis(self) -> None:
        out = _truncate("a" * 100, 10)
        assert len(out) == 10
        assert out.endswith("\u2026")

    def test_empty(self) -> None:
        assert _truncate("", 10) == ""
