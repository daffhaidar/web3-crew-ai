"""Tool for fetching on-chain token metadata via Etherscan API."""

import json
from typing import Any

import httpx
from crewai.tools import BaseTool
from pydantic import Field

from web3_crew.config import settings


class TokenDataFetcherTool(BaseTool):
    name: str = "token_data_fetcher"
    description: str = (
        "Fetches on-chain token metadata from Etherscan: contract source code, ABI, "
        "creator address, and transaction count. Input: a valid EVM token contract address."
    )
    api_key: str = Field(default_factory=lambda: settings.etherscan_api_key)

    def _run(self, token_address: str) -> str:
        base_url = "https://api.etherscan.io/v2/api"
        results: dict[str, Any] = {"token_address": token_address}

        with httpx.Client(timeout=30) as client:
            # 1. Get contract source code + ABI
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
                results["abi"] = abi_val
                results["is_verified"] = abi_val != "Contract source code not verified"
            else:
                results["source_code"] = ""
                results["abi"] = ""
                results["is_verified"] = False

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
