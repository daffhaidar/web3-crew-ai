"""ChatAgent — general-purpose assistant with the SUPERAGENT persona.

This agent is the entry point for ``/chat <text>`` Telegram commands. It:

1. Loads the SUPERAGENT persona (``SOUL.md`` + ``IDENTITY.md``) as its
   ``backstory`` so its tone, traits, and hard stops are baked into every
   reply.
2. Uses :class:`web3_crew.tools.skill_router.SkillRouterTool` to dynamically
   pull the relevant ``SKILL.md`` body for the user's request, then synthesizes
   an answer in SUPERAGENT style.
3. Uses ScrapeWebsiteTool to extract content from URLs provided by users.

The persona is loaded from ``.agents/persona/*.md`` at agent-creation time.
Failure to find a persona file is non-fatal — we fall back to a minimal
in-code persona so the bot keeps working even if the persona files are
missing or renamed.
"""

from __future__ import annotations
from datetime import datetime

import os
from pathlib import Path

from crewai import Agent
from crewai.tools import tool
from crewai_tools import ScrapeWebsiteTool
from web3 import Web3

from web3_crew.llm import create_llm
from web3_crew.tools.evm_balance import EVMBalanceCheckerTool
from web3_crew.tools.mint_phase import probe_mint_phase
from web3_crew.tools.skill_router import SkillRouterTool

# Fallback persona used if .agents/persona/*.md is missing. Kept short to
# avoid drifting from the canonical SUPERAGENT spec.
_FALLBACK_PERSONA = (
    "You are SUPERAGENT — an elite, laid-back Web3 engineer. Direct, tactical, "
    "adaptive. Auto-detect language; strictly use casual 'lo/gue' for Indonesian users. "
    "CRITICAL RULES: 1) Distinguish casual chat from execution commands. If the user is just chatting or asking opinions, reply naturally without code blocks or unsolicited tutorials. "
    "2) Never use AI fluff like 'Berikut penjelasannya' or formal words like 'kamu'. 3) ONLY generate code or execute if explicitly asked or given an address/link. "
    "No moralizing, no disclaimers — except for extreme hard stops (minors/WMD)."
)


# ---------------------------------------------------------------------------
# Web3 helper for tools that need on-chain access
# ---------------------------------------------------------------------------

_w3_instance: Web3 | None = None


def _get_web3() -> Web3:
    """Return a shared Web3 instance, lazy-initialised from ``ETH_RPC_URL``."""
    global _w3_instance
    if _w3_instance is None:
        rpc_url = os.environ.get("ETH_RPC_URL", "https://eth.llamarpc.com")
        _w3_instance = Web3(Web3.HTTPProvider(rpc_url))
    return _w3_instance


# ---------------------------------------------------------------------------
# CrewAI @tool wrappers
# ---------------------------------------------------------------------------


@tool("mint_phase_probe")
def mint_phase_probe(contract_address: str, user_address: str = "") -> str:
    """Probe the minting status of an NFT contract (is it open, price, supply, etc) without executing transactions.

    Args:
        contract_address: The NFT contract address to probe (checksummed or lowercased).
        user_address: Optional wallet address to check per-wallet minted counts.
    """
    w3 = _get_web3()
    user_addr = user_address.strip() or None
    result = probe_mint_phase(w3, contract_address, user_address=user_addr)
    return result.summary()


# ---------------------------------------------------------------------------
# Persona loading
# ---------------------------------------------------------------------------


def _default_persona_dir() -> Path:
    """Resolve ``.agents/persona/`` by walking up from this module's path."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / ".agents" / "persona"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / ".agents" / "persona"


def load_persona(persona_dir: Path | None = None) -> str:
    """Load and concatenate the persona files into a single backstory string.

    Reads ``SOUL.md`` then ``IDENTITY.md`` from ``persona_dir``. Missing files
    are skipped silently. Returns the fallback persona if nothing loadable is
    found.
    """
    persona_dir = persona_dir or _default_persona_dir()
    parts: list[str] = []
    for fname in ("SOUL.md", "IDENTITY.md"):
        path = persona_dir / fname
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8").strip())
    if not parts:
        return _FALLBACK_PERSONA
    return "\n\n".join(parts)


def create_chat_agent(persona_dir: Path | None = None, skill_context: str = "") -> Agent:
    """Build the SUPERAGENT-persona ChatAgent with dynamic context support.

    The agent has two tools: skill_router for domain-specific knowledge and
    scrape_website for extracting content from URLs. The persona and dynamic 
    skills are injected directly into ``backstory`` to form its core identity.
    """
    base_persona = load_persona(persona_dir)
    
    current_date = f"Today's date: {datetime.now().strftime('%Y-%m-%d %A')}. Your knowledge cutoff date is December 2024.\n\n"
    base_persona = current_date + base_persona
    
    # Masukkan dynamic skills langsung ke DNA backstory jika ada data masuk
    if skill_context:
        full_backstory = (
            f"{base_persona}\n\n"
            f"=== CRITICAL CURRENT CORE PERSONA EXTENSION (DYNAMIC SKILLS) ===\n"
            f"{skill_context}\n"
            f"================================================================"
        )
    else:
        full_backstory = base_persona

    return Agent(
        role="SUPERAGENT — General Execution Agent",
        goal=(
            "Answer the user's request directly and immediately, in their "
            "language, with concrete executable steps. Use the skill_router "
            "tool to pull domain-specific knowledge when the request touches a "
            "specialized area (server, monetize, content, automation, data, "
            "API, AI, files, frontend, audit, strategy, debug). Use the "
            "scrape_website tool to extract content from any URLs provided by "
            "the user. Use the EVMBalanceCheckerTool to validate and check the "
            "simulated balance of any EVM wallet address provided by the user. "
            "Use the mint_phase_probe tool to check whether an NFT contract's "
            "minting is open, its price, supply, and per-wallet caps. "
            "For Web3 questions about THIS bot itself, the "
            "skill_router will surface the matching repo skill — synthesize "
            "from it, do not paste it raw."
        ),
        backstory=full_backstory,
        tools=[
            SkillRouterTool(),
            ScrapeWebsiteTool(),
            EVMBalanceCheckerTool(),
            mint_phase_probe,
        ],
        llm=create_llm(),
        verbose=True,
        allow_delegation=False,
    )
