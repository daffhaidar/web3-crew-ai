"""Smart Contract Auditor Agent — analyzes contracts for vulnerabilities.

Tool surface
------------
The auditor used to also hold :class:`ContractAnalyzerTool`, which
required the agent to pass the raw Solidity source as a tool argument.
That argument round-trips through the LLM context and overflows the
8K window on ``cerebras/gpt-oss-120b`` / self-hosted Qwen2.

Static analysis has moved upstream into
:class:`web3_crew.tools.token_data_fetcher.TokenDataFetcherTool`, which
runs the regex scan inline and emits ``source_findings`` directly. The
auditor now only owns :class:`RugPullDetectorTool`, which consumes those
pre-computed findings to compute the risk score. No raw source ever
reaches the agent context.
"""

from crewai import Agent

from web3_crew.llm import create_llm
from web3_crew.tools.rug_pull_detector import RugPullDetectorTool


def create_contract_auditor() -> Agent:
    return Agent(
        role="Smart Contract Security Analyst",
        goal=(
            "Analyze smart contract source code for security vulnerabilities, "
            "rug-pull patterns, honeypot indicators, and other red flags. "
            "Produce a risk score and a clear go/no-go recommendation."
        ),
        backstory=(
            "You are a senior smart contract auditor with deep expertise in "
            "Solidity security patterns. You have audited hundreds of token "
            "contracts and can quickly identify dangerous patterns like hidden "
            "mint functions, blacklist mechanisms, fee manipulation, and proxy "
            "abuse. Your audits protect users from losing funds to malicious "
            "contracts. You always err on the side of caution."
        ),
        tools=[RugPullDetectorTool()],
        llm=create_llm(),
        verbose=True,
        allow_delegation=False,
    )
