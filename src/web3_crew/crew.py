"""Crew definition — wires agents, tasks, and the sequential process together."""

from crewai import Crew, Process

from web3_crew.agents import (
    create_contract_auditor,
    create_data_gatherer,
    create_tx_executor,
)
from web3_crew.tasks import create_audit_task, create_execute_task, create_gather_task


def build_crew(token_address: str, action: str = "mint") -> Crew:
    """Build a 3-agent sequential crew for Web3 token analysis and execution.

    Pipeline:
        1. Data Gatherer  → collects token metadata and liquidity data
        2. Contract Auditor → analyzes source code and produces risk score
        3. Transaction Executor → executes safe transaction (or rejects)
    """
    # Create agents
    data_gatherer = create_data_gatherer()
    contract_auditor = create_contract_auditor()
    tx_executor = create_tx_executor()

    # Create tasks (sequential — each feeds into the next)
    gather_task = create_gather_task(data_gatherer, token_address)
    audit_task = create_audit_task(contract_auditor)
    execute_task = create_execute_task(tx_executor, action)

    return Crew(
        agents=[data_gatherer, contract_auditor, tx_executor],
        tasks=[gather_task, audit_task, execute_task],
        process=Process.sequential,
        verbose=True,
    )
