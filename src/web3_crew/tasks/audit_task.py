"""Task definition for the Smart Contract Auditor agent."""

from crewai import Agent, Task


def create_audit_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Using the token data from the previous research task — which "
            "already contains `source_findings` (a list of regex-matched "
            "dangerous patterns produced server-side by the token_data_fetcher "
            "tool) plus `is_verified` and `liquidity_usd` — produce a security "
            "audit. "
            "DO NOT request the raw contract source code: it never enters the "
            "agent context by design and would overflow the LLM. The findings "
            "list is the canonical input. "
            "Call the rug_pull_detector tool with a JSON payload containing "
            "{'findings': <the source_findings from the previous task>, "
            "'liquidity_usd': <number>, 'is_verified': <bool>} to compute the "
            "risk score. "
            "Produce a detailed audit report with risk_score, risk_label, "
            "findings, and a clear recommendation on whether it is safe to "
            "interact with this contract."
        ),
        expected_output=(
            "A JSON audit report containing: risk_score (0-100), risk_label "
            "(safe/suspicious/dangerous), can_execute (boolean), detailed "
            "findings with severity levels, and a recommendation."
        ),
        agent=agent,
    )
