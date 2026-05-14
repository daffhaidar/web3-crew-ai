"""Transaction Executor Agent — executes safe on-chain interactions."""

from crewai import Agent

from web3_crew.llm import create_llm
from web3_crew.tools.safe_transaction import SafeTransactionTool


def create_tx_executor() -> Agent:
    return Agent(
        role="Secure Transaction Executor",
        goal=(
            "Execute safe on-chain transactions (mint, approve, transfer) ONLY when "
            "the smart contract audit has passed the safety threshold. Refuse to "
            "execute if the risk score is too high."
        ),
        backstory=(
            "You are a cautious blockchain transaction specialist. You never execute "
            "a transaction without first verifying the audit results. Safety is your "
            "top priority — you would rather refuse a transaction than risk losing "
            "funds. You carefully construct transactions with proper gas limits and "
            "validate all parameters before signing. Your private key is loaded "
            "securely from the environment and never exposed."
        ),
        tools=[SafeTransactionTool()],
        llm=create_llm(),
        verbose=True,
        allow_delegation=False,
    )
