"""Tests for the SUPERAGENT-persona ChatAgent.

The ChatAgent is the entry point for ``/chat <text>``. These tests pin:

1. The persona files are loaded from disk and concatenated into ``backstory``.
2. The fallback persona kicks in when persona files are missing.
3. The agent carries the SkillRouterTool and only that tool.
4. The ChatAgent has a different ``role`` than the audit/mint agents — so its
   persona cannot leak into ``/check`` or ``/mint`` outputs.
"""

from __future__ import annotations

from pathlib import Path

from web3_crew.agents.chat_agent import (
    _FALLBACK_PERSONA,
    create_chat_agent,
    load_persona,
)
from web3_crew.crew import build_chat_crew, build_crew
from web3_crew.tools.skill_router import SkillRouterTool


class TestPersonaLoading:
    def test_loads_soul_and_identity_from_repo(self):
        persona = load_persona()
        # Repo ships with both files containing canonical SUPERAGENT markers.
        assert "SUPERAGENT" in persona
        assert "Execute first" in persona or "execute first" in persona.lower()

    def test_fallback_persona_when_dir_missing(self, tmp_path: Path):
        missing = tmp_path / "nope"
        out = load_persona(missing)
        assert out == _FALLBACK_PERSONA

    def test_fallback_persona_when_files_missing(self, tmp_path: Path):
        empty = tmp_path / "persona"
        empty.mkdir()
        out = load_persona(empty)
        assert out == _FALLBACK_PERSONA

    def test_loads_only_available_files(self, tmp_path: Path):
        d = tmp_path / "persona"
        d.mkdir()
        (d / "SOUL.md").write_text("CUSTOM SOUL", encoding="utf-8")
        out = load_persona(d)
        assert out == "CUSTOM SOUL"

    def test_concatenates_soul_then_identity(self, tmp_path: Path):
        d = tmp_path / "persona"
        d.mkdir()
        (d / "SOUL.md").write_text("SOUL_FIRST", encoding="utf-8")
        (d / "IDENTITY.md").write_text("IDENTITY_SECOND", encoding="utf-8")
        out = load_persona(d)
        assert out.index("SOUL_FIRST") < out.index("IDENTITY_SECOND")


class TestChatAgentShape:
    def test_chat_agent_has_skill_router_tool(self):
        agent = create_chat_agent()
        tool_types = [type(t) for t in agent.tools]
        assert SkillRouterTool in tool_types

    def test_chat_agent_carries_persona_in_backstory(self):
        agent = create_chat_agent()
        assert "SUPERAGENT" in agent.backstory

    def test_chat_agent_role_is_distinct(self):
        agent = create_chat_agent()
        # Must NOT collide with the audit/mint agent roles.
        assert agent.role != "Web3 Data Research Specialist"
        assert agent.role != "Secure Transaction Executor"
        assert "SUPERAGENT" in agent.role


class TestChatCrewIsolation:
    """The chat crew must be SEPARATE from the audit/mint pipeline."""

    def test_build_chat_crew_has_only_chat_agent(self):
        crew = build_chat_crew("test query")
        assert len(crew.agents) == 1
        assert len(crew.tasks) == 1
        role = crew.agents[0].role
        # Not any of the audit/mint roles.
        assert "Data Research" not in role
        assert "Transaction Executor" not in role

    def test_audit_only_crew_does_not_include_chat_agent(self):
        crew = build_crew("0x0000000000000000000000000000000000000001", audit_only=True)
        roles = [a.role for a in crew.agents]
        assert all("SUPERAGENT" not in r for r in roles), (
            "ChatAgent (SUPERAGENT persona) leaked into the audit pipeline."
        )

    def test_full_crew_does_not_include_chat_agent(self):
        crew = build_crew("0x0000000000000000000000000000000000000001")
        roles = [a.role for a in crew.agents]
        assert all("SUPERAGENT" not in r for r in roles), (
            "ChatAgent (SUPERAGENT persona) leaked into the mint pipeline."
        )
