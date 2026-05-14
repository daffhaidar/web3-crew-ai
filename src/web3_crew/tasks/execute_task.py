"""Task definition for the Transaction Executor agent."""

from crewai import Agent, Task


def create_execute_task(agent: Agent, action: str = "mint") -> Task:
    return Task(
        description=(
            f"Based on the audit results from the previous task, determine if it is "
            f"safe to execute a '{action}' transaction on the target contract. "
            "If the risk_score is below the safety threshold and can_execute is true, "
            "use the safe_transaction tool to build and execute the transaction. "
            "If the risk score is too high or can_execute is false, DO NOT execute "
            "the transaction. Instead, return a rejection report explaining why."
        ),
        expected_output=(
            "Either a transaction receipt (tx_hash, gas_used, block_number) if the "
            "transaction was executed, or a rejection report explaining why the "
            "transaction was refused due to safety concerns."
        ),
        agent=agent,
    )
