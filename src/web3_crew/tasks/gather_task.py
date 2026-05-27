"""Task definition for the Data Gatherer agent."""

from crewai import Agent, Task


def create_gather_task(agent: Agent, token_address: str) -> Task:
    return Task(
        description=(
            f"Research the token at address {token_address}. "
            "Use the token_data_fetcher tool to get the contract name, "
            "deployer address, total supply, the `abi_summary` string, "
            "and the `source_findings` list (already analyzed inside the "
            "tool — DO NOT request the raw source code or the raw ABI, "
            "those would overflow the LLM context). "
            "The tool runs regex-based static analysis on the contract "
            "source server-side and returns only the structured findings "
            "plus a `source_summary` headline. "
            "Then use the dex_screener tool to get DEX liquidity and pair "
            "data. Compile all findings into a structured JSON report."
        ),
        expected_output=(
            "A JSON report containing: token_address, contract_name, "
            "compiler_version, is_verified, deployer_address, "
            "total_supply, abi_summary (short string), source_summary "
            "(one-line headline), source_findings (a list of "
            "{name, severity, description, occurrences} entries — NOT "
            "the raw source code), has_critical_finding, "
            "has_high_finding, liquidity_usd, and dex pairs data."
        ),
        agent=agent,
    )
