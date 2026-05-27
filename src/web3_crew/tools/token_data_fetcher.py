"""Tool for fetching on-chain token metadata via Etherscan API.

LLM-context discipline
----------------------
This tool used to return two LLM-hostile fields:

1. The **full** Etherscan ABI (10–50 KB JSON string) — fixed in the
   Blind Execution PR; replaced with :data:`abi_summary` plus
   server-side resolution inside
   :class:`web3_crew.tools.safe_transaction.SafeTransactionTool`.
2. The **flattened Solidity source code** (often 5–80 KB of text) —
   fixed in this module. The static analyzer
   :func:`web3_crew.tools.source_analyzer.analyze_source_code` runs
   *inline* here, and the result is condensed into:

   * ``source_findings`` — short JSON list of regex-matched patterns
     (each entry < 200 chars).
   * ``source_summary`` — one-line digest the auditor LLM can read.

The raw ``source_code`` field is no longer included in the response.
On small-context models (``cerebras/gpt-oss-120b`` at 8K tokens, or
locally-hosted Qwen2 at similar limits) the previous payload regularly
overflowed mid-pipeline and crashed ``/mint``. This refactor keeps the
full audit signal while shrinking the LLM payload by ~95 %.
"""

import json
from typing import Any

import httpx
from crewai.tools import BaseTool
from pydantic import Field

from web3_crew.config import settings
from web3_crew.tools.abi_constants import summarize_mint_signatures
from web3_crew.tools.source_analyzer import analyze_source_code


class TokenDataFetcherTool(BaseTool):
    name: str = "token_data_fetcher"
    description: str = (
        "Fetches on-chain token metadata from Etherscan and runs static "
        "analysis INTERNALLY on the contract source. Returns: contract "
        "name, deployer address, total supply, an `abi_summary` string, "
        "a `source_summary` headline, and a `source_findings` list of "
        "pattern hits (each < 200 chars). Does NOT return the raw ABI "
        "or the raw Solidity source code — both are processed inside "
        "Python and discarded before the response is built. Downstream "
        "tools (rug_pull_detector, safe_transaction) consume the "
        "structured findings directly. Input: a valid EVM token "
        "contract address."
    )
    api_key: str = Field(default_factory=lambda: settings.etherscan_api_key)

    def _run(self, token_address: str) -> str:
        base_url = "https://api.etherscan.io/v2/api"
        results: dict[str, Any] = {"token_address": token_address}

        with httpx.Client(timeout=30) as client:
            # 1. Pull source code + ABI from getsourcecode. Both stay
            # local to this function — only digests reach the response.
            source_resp = client.get(
                base_url,
                params={
                    "chainid": settings.chain_id,
                    "module": "contract",
                    "action": "getsourcecode",
                    "address": token_address,
                    "apikey": self.api_key,
                },
            )
            source_data = source_resp.json()
            if source_data.get("status") == "1" and source_data.get("result"):
                contract_info = source_data["result"][0]
                results["contract_name"] = contract_info.get("ContractName", "")
                results["compiler_version"] = contract_info.get("CompilerVersion", "")

                raw_source = contract_info.get("SourceCode", "")
                abi_val = contract_info.get("ABI", "")
                is_verified = bool(abi_val) and abi_val != "Contract source code not verified"
                results["is_verified"] = is_verified

                # Run regex static analysis inline. ``raw_source`` is
                # consumed here and never echoed back into ``results``.
                analysis = analyze_source_code(raw_source)
                results["source_findings"] = analysis["findings"]
                results["source_summary"] = analysis["summary"]
                results["has_critical_finding"] = analysis["has_critical"]
                results["has_high_finding"] = analysis["has_high"]

                results["abi_summary"] = _summarize_abi(abi_val) if is_verified else (
                    "Contract unverified on Etherscan — ABI unavailable. "
                    "Executor will fall back to GENERIC_ERC721/ERC20 ABI or "
                    "blind calldata at mint time."
                )
            else:
                results["contract_name"] = ""
                results["compiler_version"] = ""
                results["is_verified"] = False
                # Run analyze on empty source so the response shape stays
                # consistent across the verified / unverified / Etherscan-down
                # branches. The function returns an explicit "no source"
                # finding in that case.
                analysis = analyze_source_code("")
                results["source_findings"] = analysis["findings"]
                results["source_summary"] = analysis["summary"]
                results["has_critical_finding"] = analysis["has_critical"]
                results["has_high_finding"] = analysis["has_high"]
                results["abi_summary"] = "Etherscan returned no data for this address."

            # 2. Contract creator + creation tx
            creation_resp = client.get(
                base_url,
                params={
                    "chainid": settings.chain_id,
                    "module": "contract",
                    "action": "getcontractcreation",
                    "contractaddresses": token_address,
                    "apikey": self.api_key,
                },
            )
            creation_data = creation_resp.json()
            if creation_data.get("status") == "1" and creation_data.get("result"):
                results["deployer_address"] = creation_data["result"][0].get("contractCreator", "")
                results["creation_tx"] = creation_data["result"][0].get("txHash", "")
            else:
                results["deployer_address"] = ""
                results["creation_tx"] = ""

            # 3. Token supply info
            supply_resp = client.get(
                base_url,
                params={
                    "chainid": settings.chain_id,
                    "module": "stats",
                    "action": "tokensupply",
                    "contractaddress": token_address,
                    "apikey": self.api_key,
                },
            )
            supply_data = supply_resp.json()
            if supply_data.get("status") == "1":
                results["total_supply"] = supply_data.get("result", "0")
            else:
                results["total_supply"] = "0"

        return json.dumps(results, indent=2)


def _summarize_abi(raw_abi: str) -> str:
    """Parse a raw Etherscan ABI string and return a short LLM-safe summary.

    Returns the mint-signature digest from
    :func:`web3_crew.tools.abi_constants.summarize_mint_signatures` plus
    the total function count. Returns a fallback message if the ABI
    is malformed JSON.
    """
    try:
        parsed = json.loads(raw_abi)
    except json.JSONDecodeError:
        return "ABI present on Etherscan but not parseable as JSON."

    if not isinstance(parsed, list):
        return "ABI present on Etherscan but not a list."

    function_count = sum(1 for entry in parsed if entry.get("type") == "function")
    mint_digest = summarize_mint_signatures(parsed)
    return f"{function_count} function entries on-chain. {mint_digest}"
