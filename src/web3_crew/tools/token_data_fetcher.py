"""Tool for fetching on-chain token metadata via Etherscan API.

LLM-context discipline
----------------------
This tool used to return the **full** Etherscan ABI (a 10–50 KB JSON
string) inside its output. The auditor and executor agents then carried
that ABI in their LLM context all the way through the pipeline, which
on small-context models (e.g. ``cerebras/gpt-oss-120b`` at 8K tokens)
overflowed and silently truncated mid-mint.

The tool now returns an :data:`abi_summary` string instead — a short,
human-readable list of mint-shaped function signatures parsed from the
ABI **inside Python**. The full ABI JSON never leaves this module.
Downstream agents that actually need to call a function go through
:class:`web3_crew.tools.safe_transaction.SafeTransactionTool`, which
re-fetches the ABI from Etherscan and parses it server-side.

The ``source_code`` field is preserved because the contract auditor's
static analyzer is regex-based and runs against the raw Solidity text;
trimming it would break the rug-pull detector.
"""

import json
from typing import Any

import httpx
from crewai.tools import BaseTool
from pydantic import Field

from web3_crew.config import settings
from web3_crew.tools.abi_constants import summarize_mint_signatures


class TokenDataFetcherTool(BaseTool):
    name: str = "token_data_fetcher"
    description: str = (
        "Fetches on-chain token metadata from Etherscan: contract source code, "
        "creator address, supply, and a SHORT summary of mint-shaped functions. "
        "Does NOT return the raw contract ABI — only an `abi_summary` string. "
        "Downstream tools fetch their own ABI internally when needed. "
        "Input: a valid EVM token contract address."
    )
    api_key: str = Field(default_factory=lambda: settings.etherscan_api_key)

    def _run(self, token_address: str) -> str:
        base_url = "https://api.etherscan.io/v2/api"
        results: dict[str, Any] = {"token_address": token_address}

        with httpx.Client(timeout=30) as client:
            # 1. Get contract source code + ABI from getsourcecode.
            #
            # We pull the raw ABI from Etherscan, but immediately parse and
            # discard it inside Python. The LLM only ever sees the summary.
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
                results["source_code"] = contract_info.get("SourceCode", "")
                abi_val = contract_info.get("ABI", "")
                is_verified = bool(abi_val) and abi_val != "Contract source code not verified"
                results["is_verified"] = is_verified
                results["abi_summary"] = _summarize_abi(abi_val) if is_verified else (
                    "Contract unverified on Etherscan — ABI unavailable. "
                    "Executor will fall back to GENERIC_ERC721/ERC20 ABI or "
                    "blind calldata at mint time."
                )
            else:
                results["source_code"] = ""
                results["is_verified"] = False
                results["abi_summary"] = "Etherscan returned no data for this address."

            # 2. Get contract creator and creation tx
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

            # 3. Get token supply info
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
