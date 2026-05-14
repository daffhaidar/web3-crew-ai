"""Smart Contract Auditor Agent — analyzes contracts for vulnerabilities."""

from crewai import Agent

from web3_crew.llm import create_llm
from web3_crew.tools.contract_analyzer import ContractAnalyzerTool
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
        tools=[ContractAnalyzerTool(), RugPullDetectorTool()],
        llm=create_llm(),
        verbose=True,
        allow_delegation=False,
    )
