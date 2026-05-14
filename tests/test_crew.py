"""Tests for crew assembly and configuration."""

from crewai import Process

from web3_crew.crew import build_crew


class TestCrewAssembly:
    def test_crew_has_three_agents(self):
        crew = build_crew("0x0000000000000000000000000000000000000001")
        assert len(crew.agents) == 3

    def test_crew_has_three_tasks(self):
        crew = build_crew("0x0000000000000000000000000000000000000001")
        assert len(crew.tasks) == 3

    def test_crew_uses_sequential_process(self):
        crew = build_crew("0x0000000000000000000000000000000000000001")
        assert crew.process == Process.sequential

    def test_agent_roles(self):
        crew = build_crew("0x0000000000000000000000000000000000000001")
        roles = [a.role for a in crew.agents]
        assert "Web3 Data Research Specialist" in roles
        assert "Smart Contract Security Analyst" in roles
        assert "Secure Transaction Executor" in roles

    def test_agents_have_tools(self):
        crew = build_crew("0x0000000000000000000000000000000000000001")
        for agent in crew.agents:
            assert len(agent.tools) >= 1
