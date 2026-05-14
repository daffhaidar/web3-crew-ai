"""Task definition for the Smart Contract Auditor agent."""

from crewai import Agent, Task


def create_audit_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Using the token data from the previous research task, perform a "
            "security audit of the smart contract. "
            "1. Use the contract_analyzer tool with the contract source code to "
            "   detect dangerous patterns (hidden mints, blacklists, fee manipulation, etc). "
            "2. Use the rug_pull_detector tool with the analysis findings, liquidity data, "
            "   and verification status to calculate a risk score. "
            "Produce a detailed audit report with risk score, risk label, findings, "
            "and a clear recommendation on whether it is safe to interact with this contract."
        ),
        expected_output=(
            "A JSON audit report containing: risk_score (0-100), risk_label "
            "(safe/suspicious/dangerous), can_execute (boolean), detailed findings "
            "with severity levels, and a recommendation."
        ),
        agent=agent,
    )
