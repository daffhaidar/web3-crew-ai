"""Task definition for the Transaction Executor agent."""

from crewai import Agent, Task


def create_execute_task(agent: Agent, action: str = "mint") -> Task:
    return Task(
        description=(
            f"Based on the audit results from the previous task, determine if "
            f"it is safe to execute a '{action}' transaction on the target "
            "contract. If the risk_score is below the safety threshold and "
            "can_execute is true, call the safe_transaction tool with a JSON "
            "string containing: action, contract_address, function_name "
            "(e.g. 'mint', 'publicMint', 'safeMint', 'transfer'), "
            "function_args (list), value_wei (default 0), and risk_score. "
            "DO NOT include the contract ABI in the payload — the tool "
            "fetches it from Etherscan internally and falls back to a "
            "generic ERC-721/ERC-20 ABI when the contract is unverified. "
            "For non-standard signatures the tool also accepts "
            "action='raw' with raw_calldata (a 0x-prefixed hex string). "
            "If the risk score is too high or can_execute is false, DO NOT "
            "execute the transaction. Instead, return a rejection report "
            "explaining why."
        ),
        expected_output=(
            "Either a transaction receipt (tx_hash, gas_used, block_number, "
            "abi_source, function_signature) if the transaction was executed, "
            "or a rejection report explaining why the transaction was refused "
            "due to safety concerns."
        ),
        agent=agent,
    )
