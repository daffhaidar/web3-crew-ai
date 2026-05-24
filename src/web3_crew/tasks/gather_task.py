"""Task definition for the Data Gatherer agent."""

from crewai import Agent, Task


def create_gather_task(agent: Agent, token_address: str) -> Task:
    return Task(
        description=(
            f"Research the token at address {token_address}. "
            "Use the token_data_fetcher tool to get the contract source code, "
            "deployer address, total supply, and an `abi_summary` string from "
            "Etherscan. The tool DOES NOT return the raw ABI — only a short "
            "summary of mint-shaped function signatures. Do not request the "
            "ABI separately; the transaction executor will fetch and parse "
            "it server-side when (and if) it needs to mint. "
            "Then use the dex_screener tool to get DEX liquidity and pair data. "
            "Compile all findings into a structured JSON report."
        ),
        expected_output=(
            "A comprehensive JSON report containing: token_address, "
            "contract_name, source_code, abi_summary (a short string, NOT "
            "the raw ABI), is_verified, deployer_address, total_supply, "
            "liquidity_usd, and dex pairs data."
        ),
        agent=agent,
    )
