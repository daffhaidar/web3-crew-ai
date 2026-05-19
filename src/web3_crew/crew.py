"""Crew definition — wires agents, tasks, and the sequential process together."""

from crewai import Crew, Process

from web3_crew.agents import (
    create_chat_agent,
    create_contract_auditor,
    create_data_gatherer,
    create_tx_executor,
)
from web3_crew.tasks import (
    create_audit_task,
    create_chat_task,
    create_execute_task,
    create_gather_task,
)


def build_crew(
    token_address: str,
    action: str = "mint",
    *,
    audit_only: bool = False,
) -> Crew:
    """Build a sequential crew for Web3 token analysis and (optionally) execution.

    Pipeline:
        1. Data Gatherer  → collects token metadata and liquidity data
        2. Contract Auditor → analyzes source code and produces risk score
        3. Transaction Executor → executes safe transaction (or rejects)

    Args:
        token_address: EVM contract address to analyze.
        action: On-chain action the executor should attempt if audit passes
            (ignored when ``audit_only=True``).
        audit_only: When ``True``, build a 2-step crew that stops after the
            Auditor produces its JSON risk report. Used by the Telegram
            ``/check`` command, which must never trigger a transaction.
    """
    data_gatherer = create_data_gatherer()
    contract_auditor = create_contract_auditor()
    gather_task = create_gather_task(data_gatherer, token_address)
    audit_task = create_audit_task(contract_auditor)

    if audit_only:
        return Crew(
            agents=[data_gatherer, contract_auditor],
            tasks=[gather_task, audit_task],
            process=Process.sequential,
            verbose=True,
        )

    tx_executor = create_tx_executor()
    execute_task = create_execute_task(tx_executor, action)

    return Crew(
        agents=[data_gatherer, contract_auditor, tx_executor],
        tasks=[gather_task, audit_task, execute_task],
        process=Process.sequential,
        verbose=True,
    )


def build_chat_crew(user_input: str) -> Crew:
    """Build a single-agent crew that answers a free-form chat request.

    This is a completely separate pipeline from :func:`build_crew`: it uses
    its own :func:`create_chat_agent` (SUPERAGENT persona) and its own task,
    and shares only the LLM factory. The existing 3-agent audit/mint pipeline
    is unaffected — its agents have distinct backstories so the SUPERAGENT
    persona never leaks into ``/check`` or ``/mint`` output.

    Args:
        user_input: The user's natural-language request from ``/chat``.
    """
    chat_agent = create_chat_agent()
    chat_task = create_chat_task(chat_agent, user_input)
    return Crew(
        agents=[chat_agent],
        tasks=[chat_task],
        process=Process.sequential,
        verbose=True,
    )
