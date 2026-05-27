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
    force_execution: bool = False,
    skill_context: str = "",
) -> Crew:
    """Build a sequential crew for Web3 token analysis and (optionally) execution."""
    data_gatherer = create_data_gatherer()
    contract_auditor = create_contract_auditor()
    
    gather_task = create_gather_task(data_gatherer, token_address)
    audit_task = create_audit_task(contract_auditor)

    if skill_context:
        context_header = f"=== DYNAMIC SKILLS & RULES ===\n{skill_context}\n=============================\n\n"
        gather_task.description = context_header + gather_task.description
        audit_task.description = context_header + audit_task.description

    if audit_only:
        return Crew(
            agents=[data_gatherer, contract_auditor],
            tasks=[gather_task, audit_task],
            process=Process.sequential,
            verbose=True,
        )

    tx_executor = create_tx_executor()
    execute_task = create_execute_task(tx_executor, action, force_execution=force_execution)

    if skill_context:
        execute_task.description = context_header + execute_task.description

    return Crew(
        agents=[data_gatherer, contract_auditor, tx_executor],
        tasks=[gather_task, audit_task, execute_task],
        process=Process.sequential,
        verbose=True,
    )


def build_chat_crew(user_input: str, skill_context: str = "") -> Crew:
    """Build a single-agent crew that answers a free-form chat request.
    
    Accepts an optional skill_context parameter to deeply inject custom
    knowledge and behaviors into the agent's core backstory.
    """
    # Kirim skill_context langsung ke fungsi pembuat agen
    chat_agent = create_chat_agent(skill_context=skill_context)
    chat_task = create_chat_task(chat_agent, user_input)
    return Crew(
        agents=[chat_agent],
        tasks=[chat_task],
        process=Process.sequential,
        verbose=True,
    )