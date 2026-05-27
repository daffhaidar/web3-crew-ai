"""Tool for fetching DEX liquidity and pair data via the DexScreener public API."""

import json
from typing import Any

import httpx
from crewai.tools import BaseTool


class DexScreenerTool(BaseTool):
    name: str = "dex_screener"
    description: str = (
        "Fetches DEX trading pair data from DexScreener: liquidity, price, volume, "
        "pair address, and DEX name. Input: a valid EVM token contract address."
    )

    def _run(self, token_address: str) -> str:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"

        with httpx.Client(timeout=30) as client:
            resp = client.get(url)
            data = resp.json()

        pairs = data.get("pairs") or []
        if not pairs:
            return json.dumps({
                "token_address": token_address,
                "pairs_found": 0,
                "pairs": [],
                "total_liquidity_usd": 0,
            })

        formatted_pairs: list[dict[str, Any]] = []
        total_liquidity = 0.0

        for pair in pairs[:10]:  # Limit to top 10 pairs
            liquidity = pair.get("liquidity", {})
            liquidity_usd = liquidity.get("usd", 0) if isinstance(liquidity, dict) else 0
            total_liquidity += liquidity_usd

            formatted_pairs.append({
                "pair_address": pair.get("pairAddress", ""),
                "dex": pair.get("dexId", ""),
                "chain": pair.get("chainId", ""),
                "base_token": pair.get("baseToken", {}).get("symbol", ""),
                "quote_token": pair.get("quoteToken", {}).get("symbol", ""),
                "price_usd": pair.get("priceUsd", "0"),
                "volume_24h": pair.get("volume", {}).get("h24", 0),
                "liquidity_usd": liquidity_usd,
                "price_change_24h": pair.get("priceChange", {}).get("h24", 0),
                "fdv": pair.get("fdv", 0),
            })

        result = {
            "token_address": token_address,
            "pairs_found": len(pairs),
            "total_liquidity_usd": total_liquidity,
            "pairs": formatted_pairs,
        }

        return json.dumps(result, indent=2)
