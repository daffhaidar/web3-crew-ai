"""ChatAgent — general-purpose assistant with the SUPERAGENT persona.

This agent is the entry point for /chat Telegram commands.
"""

from __future__ import annotations

import os
import json
import asyncio
from pathlib import Path

from crewai import Agent
from crewai_tools import ScrapeWebsiteTool
from crewai.tools import tool
from web3 import Web3

from web3_crew.llm import create_llm
from web3_crew.tools.skill_router import SkillRouterTool
from web3_crew.tools.mint_phase import probe_mint_phase
from web3_crew.tools.safe_transaction import SafeTransactionTool
from web3_crew.tools.scheduled_mint import ScheduledMintQueue, parse_schedule_time
from web3_crew.tools.frontend_sniper import playwright_frontend_sniper
from web3_crew.tools.sybil_manager import manage_sybil_wallets
from web3_crew.tools.sysadmin_tool import sysadmin_auto_learner

_FALLBACK_PERSONA = (
    "You are SUPERAGENT — an elite, laid-back Web3 engineer. Direct, tactical, "
    "adaptive. Auto-detect language; strictly use casual 'lo/gue' for Indonesian users. "
    "CRITICAL RULES: 1) Distinguish casual chat from execution commands. If the user is just chatting or asking opinions, reply naturally without code blocks or unsolicited tutorials. "
    "2) Never use AI fluff like 'Berikut penjelasannya' or formal words like 'kamu'. 3) ONLY generate code or execute if explicitly asked or given an address/link. "
    "No moralizing, no disclaimers — except for extreme hard stops (minors/WMD)."
)

# --- TOOLS ---

@tool("NFT Mint Phase Probe")
def probe_mint_phase_tool(contract_address: str, user_address: str | None = None) -> str:
    """
    Probe the minting status of an NFT contract (is it open, price, supply, etc) without executing transactions.
    Use this tool before any minting interaction.
    """
    rpc_url = os.getenv("RPC_URL", "https://eth.llamarpc.com")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    
    result = probe_mint_phase(w3, contract_address, user_address=user_address)
    return result.summary()

@tool("NFT Mint Executor")
def execute_mint_tool(contract_address: str, function_name: str, qty: int, value_wei: int = 0) -> str:
    """
    Execute an immediate mint transaction on a smart contract.
    Only use this if the user wants to mint RIGHT NOW.
    """
    tool_instance = SafeTransactionTool()
    payload = {
        "action": "mint",
        "contract_address": contract_address,
        "function_name": function_name,
        "function_args": [qty] if function_name != "publicMint" else [],
        "value_wei": value_wei,
        "risk_score": 0
    }
    return tool_instance._run(json.dumps(payload))

@tool("Schedule NFT Mint")
def schedule_mint_tool(contract_address: str, qty: int, schedule_time_spec: str, function_name: str = "publicMint", value_wei: int = 0) -> str:
    """
    Schedule an NFT mint job for the future (Autopilot / Standby mode).
    Args:
        contract_address: The target NFT contract.
        qty: Number of NFTs to mint.
        schedule_time_spec: Time specification format. High priority: relative offset like '+10m', '+1h', or absolute UTC time like '13:00 UTC'.
        function_name: Name of the mint function (e.g., 'publicMint', 'mint').
        value_wei: Total cost in WEI.
    """
    target_timestamp = parse_schedule_time(schedule_time_spec)
    if target_timestamp is None:
        return "❌ Gagal parse waktu. Gunakan format '+15m', '+2h', atau 'HH:MM UTC'."

    async def _async_enqueue():
        queue = ScheduledMintQueue()
        return await queue.enqueue(
            contract_address=contract_address,
            qty=qty,
            scheduled_at=target_timestamp,
            value_wei=value_wei,
            function_name=function_name
        )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        job = loop.run_until_complete(_async_enqueue())
        loop.close()
        return f"✅ Autopilot Active! Job ID: {job.id[:8]} scheduled successfully at Unix {job.scheduled_at}."
    except Exception as e:
        return f"❌ Failed to queue the scheduled job: {str(e)}"

# --- HELPER FUNCTIONS ---

def _default_persona_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / ".agents" / "persona"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / ".agents" / "persona"


def load_persona(persona_dir: Path | None = None) -> str:
    persona_dir = persona_dir or _default_persona_dir()
    parts: list[str] = []
    for fname in ("SOUL.md", "IDENTITY.md"):
        path = persona_dir / fname
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8").strip())
    if not parts:
        return _FALLBACK_PERSONA
    return "\n\n".join(parts)


# --- AGENT FACTORY ---

def create_chat_agent(persona_dir: Path | None = None, skill_context: str = "") -> Agent:
    """Build the SUPERAGENT-persona ChatAgent with deep context injection."""
    persona = load_persona(persona_dir)
    
    if skill_context:
        persona = (
            f"{persona}\n\n"
            f"=== CORE IDENTITY OVERRIDE & DYNAMIC SKILLS ===\n"
            f"{skill_context}\n"
            f"==============================================="
        )

    return Agent(
        role="SUPERAGENT — General Execution Agent",
        goal=(
            "Answer the user's request directly and immediately, in their "
            "language, with concrete executable steps. Use the skill_router "
            "tool to pull domain-specific knowledge when the request touches a "
            "specialized area. Use the scrape_website tool to extract content "
            "from any URLs provided by the user."
        ),
        backstory=persona,
        tools=[
            SkillRouterTool(), 
            ScrapeWebsiteTool(), 
            probe_mint_phase_tool, 
            execute_mint_tool,
            schedule_mint_tool,
            playwright_frontend_sniper,
            manage_sybil_wallets,
            sysadmin_auto_learner,
        ], 
        llm=create_llm(),
        verbose=True,
        allow_delegation=False,
    )
