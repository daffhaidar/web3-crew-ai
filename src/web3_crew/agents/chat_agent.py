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

from pathlib import Path

from crewai import Agent
from crewai_tools import ScrapeWebsiteTool

from web3_crew.llm import create_llm
from web3_crew.tools import EVMBalanceCheckerTool
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
            "For Web3 questions about THIS bot itself, the "
            "skill_router will surface the matching repo skill — synthesize "
            "from it, do not paste it raw."
        ),
        backstory=full_backstory,
        tools=[SkillRouterTool(), ScrapeWebsiteTool(), EVMBalanceCheckerTool()],
        llm=create_llm(),
        verbose=True,
        allow_delegation=False,
    )
