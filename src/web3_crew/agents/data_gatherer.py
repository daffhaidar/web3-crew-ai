"""Data Gatherer Agent — collects on-chain and off-chain token data."""

from crewai import Agent

from web3_crew.tools.dex_screener import DexScreenerTool
from web3_crew.tools.token_data_fetcher import TokenDataFetcherTool


def create_data_gatherer() -> Agent:
    return Agent(
        role="Web3 Data Research Specialist",
        goal=(
            "Collect comprehensive on-chain and off-chain data about a token project, "
            "including contract source code, ABI, deployer info, total supply, "
            "and DEX liquidity data."
        ),
        backstory=(
            "You are an expert blockchain researcher who specializes in gathering "
            "intelligence about token projects. You know how to pull data from "
            "block explorers and DEX aggregators to build a complete picture of "
            "any token's on-chain footprint. Your research is thorough and "
            "structured, providing the foundation for security analysis."
        ),
        tools=[TokenDataFetcherTool(), DexScreenerTool()],
        verbose=True,
        allow_delegation=False,
    )
