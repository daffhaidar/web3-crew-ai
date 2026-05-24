"""Post-transaction NFT / ERC-20 metadata fetcher.

This module runs **strictly after** a transaction has been successfully
broadcast and mined. It is layered on top of
:class:`web3_crew.tools.safe_transaction.SafeTransactionTool` as a
side-effect-free post-processor: it never builds, signs, or replaces a
transaction, and any failure inside it is swallowed by
:func:`fetch_post_tx_metadata` so the executor's user-facing result
(``tx_hash``, ``status``, etc.) is never lost or corrupted.

Isolation rules (from the implementation mandate)
-------------------------------------------------
1. **No core-tx surgery.** This module is import-only. It does not patch
   ``SafeTransactionTool._run`` — that tool calls this module from
   exactly one spot, inside the ``status == success`` branch of
   :func:`_terminal_response`.
2. **Graceful degradation.** Every external call is wrapped in a broad
   ``try / except Exception`` that returns a Telegram-friendly fallback
   string rather than raising. Network timeouts, Alchemy 404s,
   un-indexed contracts, malformed responses, and missing API keys all
   land on the same fallback path.
3. **LLM-context discipline.** The agent only sees a short
   ``metadata_summary`` HTML string (≤ ~400 chars on the happy path,
   ≤ 100 chars on fallback). Raw Alchemy JSON never reaches the model.

API surface
-----------
* :func:`fetch_post_tx_metadata` — the single entry point. Takes a tx
  receipt, the contract address, and the chain id; returns a dict with
  exactly two keys: ``metadata_summary`` (HTML string for Telegram) and
  ``metadata_status`` (``"ok"`` / ``"fallback"`` / ``"skipped"``).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from web3_crew.config import settings

logger = logging.getLogger(__name__)


# ERC-721 ``Transfer(address indexed from, address indexed to,
# uint256 indexed tokenId)`` topic-0. ERC-20 emits the same name but
# with only 3 topics (``tokenId`` would actually be ``value`` and is
# not indexed) — we distinguish by topic count below.
_TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# OpenSea collection / asset URL fragments per chain id. Keys mirror
# :data:`web3_crew.tools.safe_transaction.EXPLORER_DOMAINS`. Chains we
# don't recognise fall back to a plain Etherscan tx link with no
# OpenSea row in the summary.
_OPENSEA_CHAIN_SLUG: dict[int, str] = {
    1: "ethereum",
    137: "matic",
    8453: "base",
    42161: "arbitrum",
    10: "optimism",
}

# Alchemy NFT API v3 base URL per chain id. Only chains Alchemy
# supports for ``getNFTMetadata`` are listed; others skip the API call
# and use the static-link fallback.
_ALCHEMY_NFT_BASE: dict[int, str] = {
    1: "https://eth-mainnet.g.alchemy.com/nft/v3",
    137: "https://polygon-mainnet.g.alchemy.com/nft/v3",
    8453: "https://base-mainnet.g.alchemy.com/nft/v3",
    42161: "https://arb-mainnet.g.alchemy.com/nft/v3",
    10: "https://opt-mainnet.g.alchemy.com/nft/v3",
}

# Block explorer domains. Kept local to this module to avoid a circular
# import with :mod:`safe_transaction`.
_EXPLORER_DOMAINS: dict[int, str] = {
    1: "etherscan.io",
    11155111: "sepolia.etherscan.io",
    137: "polygonscan.com",
    8453: "basescan.org",
    42161: "arbiscan.io",
    10: "optimistic.etherscan.io",
}

# Hard upper bound on the Telegram metadata line. Keeps the LLM context
# small and the Telegram message inside the 4096-char limit even when
# stacked with the existing tx report.
_MAX_NAME_LEN = 120
_MAX_SUMMARY_LEN = 600

# Generic fallback string used when the fetch fails and we don't even
# have a token id to point the user to.
_FALLBACK_GENERIC = "(Metadata fetch failed/pending)"


def fetch_post_tx_metadata(
    receipt: Any,
    contract_address: str,
    chain_id: int,
    *,
    http_client_factory: Any = None,
) -> dict[str, str]:
    """Build a Telegram-ready metadata digest for a freshly-mined tx.

    Parameters
    ----------
    receipt:
        The full ``web3.py`` :class:`TxReceipt` dict for the mined tx.
        We use its ``logs`` list to extract the minted token id(s) from
        any ``Transfer`` event. The receipt itself is not mutated.
    contract_address:
        The contract the tx interacted with. Used to build OpenSea /
        Etherscan links and (optionally) call Alchemy.
    chain_id:
        Used to pick the right explorer domain, OpenSea slug, and
        Alchemy base URL.
    http_client_factory:
        Optional callable returning an httpx-compatible context-manager
        client. Tests inject a mock here; production callers leave it
        ``None`` and we use the default :class:`httpx.Client`.

    Returns
    -------
    A dict with two string fields:

    * ``metadata_summary`` — short HTML snippet ready to drop into a
      Telegram ``parse_mode="HTML"`` message. Always Telegram-safe.
    * ``metadata_status`` — ``"ok"`` if Alchemy returned a name,
      ``"fallback"`` if we degraded to a generic link, ``"skipped"``
      if there was nothing to fetch (e.g. no contract address).

    This function NEVER raises. Any internal error is logged at debug
    level and the response degrades to a generic fallback string.
    """
    try:
        if not contract_address or not contract_address.startswith("0x"):
            return {
                "metadata_summary": _FALLBACK_GENERIC,
                "metadata_status": "skipped",
            }

        token_ids = _extract_erc721_token_ids(receipt)
        first_token_id = token_ids[0] if token_ids else None

        nft_meta = _try_alchemy_nft_metadata(
            contract_address=contract_address,
            token_id=first_token_id,
            chain_id=chain_id,
            http_client_factory=http_client_factory,
        )

        return {
            "metadata_summary": _render_summary(
                contract_address=contract_address,
                token_ids=token_ids,
                chain_id=chain_id,
                nft_meta=nft_meta,
            ),
            "metadata_status": "ok" if nft_meta else "fallback",
        }
    except Exception as exc:  # defensive: never let this break a mint
        logger.debug("post-tx metadata fetch failed: %r", exc)
        return {
            "metadata_summary": _FALLBACK_GENERIC,
            "metadata_status": "fallback",
        }


def _extract_erc721_token_ids(receipt: Any) -> list[int]:
    """Pull every ERC-721 ``Transfer`` token id out of a tx receipt.

    ERC-721 emits a Transfer log with **4 topics** (the third being the
    indexed ``tokenId``). ERC-20 emits the same event with 3 topics —
    those are excluded so we don't surface raw transfer amounts as
    fake token ids.

    Returns an empty list on any malformed receipt rather than raising.
    """
    out: list[int] = []
    try:
        if isinstance(receipt, dict):
            logs = receipt.get("logs", [])
        else:
            logs = getattr(receipt, "logs", [])
    except Exception:
        return out

    for log in logs:
        try:
            topics = log.get("topics") if isinstance(log, dict) else getattr(log, "topics", None)
            if not topics or len(topics) != 4:
                continue

            topic0 = _coerce_topic_hex(topics[0])
            if topic0.lower() != _TRANSFER_TOPIC0:
                continue

            token_id = int(_coerce_topic_hex(topics[3]), 16)
            out.append(token_id)
        except Exception:
            # Skip malformed log entries — log everything else still works.
            continue

    return out


def _coerce_topic_hex(topic: Any) -> str:
    """Return a topic as a ``0x``-prefixed hex string.

    web3.py sometimes returns ``HexBytes``, sometimes plain ``bytes``,
    sometimes already a string — normalize them all.
    """
    if isinstance(topic, str):
        return topic if topic.startswith("0x") else "0x" + topic
    if isinstance(topic, (bytes, bytearray)):
        return "0x" + bytes(topic).hex()
    if hasattr(topic, "hex"):
        h = topic.hex()
        return h if h.startswith("0x") else "0x" + h
    return str(topic)


def _try_alchemy_nft_metadata(
    *,
    contract_address: str,
    token_id: int | None,
    chain_id: int,
    http_client_factory: Any = None,
) -> dict[str, str] | None:
    """Call Alchemy's ``getNFTMetadata`` endpoint and return a slim dict.

    Returns ``None`` (graceful skip) when:

    * ``ALCHEMY_API_KEY`` is unset.
    * The chain is not supported by Alchemy NFT v3.
    * No token id was extracted from the receipt logs.
    * The HTTP call fails, times out, or returns a non-2xx status.
    * The response body is missing the fields we care about.

    On success returns a dict with up to four keys: ``name``,
    ``collection_name``, ``image_url``, ``description``. All values are
    truncated to ``_MAX_NAME_LEN`` chars so they cannot blow up the
    Telegram message budget.
    """
    api_key = settings.alchemy_api_key
    if not api_key or token_id is None:
        return None

    base = _ALCHEMY_NFT_BASE.get(chain_id)
    if not base:
        return None

    url = f"{base}/{api_key}/getNFTMetadata"
    params = {
        "contractAddress": contract_address,
        "tokenId": str(token_id),
        "refreshCache": "false",
    }

    client_factory = http_client_factory or (lambda: httpx.Client(timeout=10))
    try:
        with client_factory() as client:
            resp = client.get(url, params=params)
            if resp.status_code != 200:
                return None
            body = resp.json()
    except Exception as exc:
        logger.debug("alchemy getNFTMetadata failed: %r", exc)
        return None

    if not isinstance(body, dict):
        return None

    raw = body.get("raw") or {}
    raw_metadata = raw.get("metadata") or {}
    contract_block = body.get("contract") or {}

    name = (
        body.get("name")
        or raw_metadata.get("name")
        or ""
    )
    collection = (
        contract_block.get("name")
        or raw_metadata.get("collection")
        or ""
    )
    image = (
        (body.get("image") or {}).get("originalUrl")
        or raw_metadata.get("image")
        or ""
    )
    description = body.get("description") or raw_metadata.get("description") or ""

    if not (name or collection):
        return None

    return {
        "name": _truncate(name, _MAX_NAME_LEN),
        "collection_name": _truncate(collection, _MAX_NAME_LEN),
        "image_url": _truncate(image, _MAX_NAME_LEN),
        "description": _truncate(description, _MAX_NAME_LEN),
    }


def _render_summary(
    *,
    contract_address: str,
    token_ids: list[int],
    chain_id: int,
    nft_meta: dict[str, str] | None,
) -> str:
    """Render the final HTML snippet for the Telegram response.

    The format is intentionally compact — at most ~6 lines of HTML —
    so the LLM context impact is minimal and the message fits inside
    Telegram's 4096-char body limit alongside the existing tx report.
    """
    import html as _html

    lines: list[str] = []

    if nft_meta:
        name = nft_meta.get("name") or "(unnamed)"
        collection = nft_meta.get("collection_name")
        lines.append(f"\U0001f5bc <b>NFT</b>: <code>{_html.escape(name)}</code>")
        if collection and collection != name:
            lines.append(f"\u2022 Collection: <code>{_html.escape(collection)}</code>")

    if token_ids:
        ids_str = ", ".join(str(t) for t in token_ids[:5])
        if len(token_ids) > 5:
            ids_str += f", \u2026 (+{len(token_ids) - 5} more)"
        lines.append(f"\u2022 Token ID: <code>{_html.escape(ids_str)}</code>")

    explorer_domain = _EXPLORER_DOMAINS.get(chain_id, "etherscan.io")
    explorer_url = f"https://{explorer_domain}/address/{contract_address}"
    lines.append(f'\u2022 <a href="{explorer_url}">Etherscan</a>')

    opensea_slug = _OPENSEA_CHAIN_SLUG.get(chain_id)
    if opensea_slug:
        if token_ids:
            opensea_url = (
                f"https://opensea.io/assets/{opensea_slug}/{contract_address}/{token_ids[0]}"
            )
            opensea_label = "OpenSea (your NFT)"
        else:
            opensea_url = f"https://opensea.io/assets/{opensea_slug}/{contract_address}"
            opensea_label = "OpenSea (collection)"
        lines.append(f'\u2022 <a href="{opensea_url}">{opensea_label}</a>')

    if not nft_meta and not token_ids:
        lines.insert(
            0,
            "<i>(Metadata pending — links below; refresh in 1-2 min for full art)</i>",
        )

    summary = "\n".join(lines)
    return _truncate(summary, _MAX_SUMMARY_LEN)


def _truncate(value: str, limit: int) -> str:
    """Trim a string to ``limit`` chars, suffixing with ``\u2026`` if cut."""
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "\u2026"
