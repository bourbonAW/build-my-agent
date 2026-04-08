"""Tests for agent deferred tool discovery."""

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestAgentDiscoveredTools:
    def _make_agent(self, tmp_path: Path):
        """Create an Agent with isolated home/session state."""
        from bourbon.agent import Agent
        from bourbon.config import Config

        with (
            patch("bourbon.agent.create_client", return_value=MagicMock()),
            patch("bourbon.agent.Path.home", return_value=tmp_path),
        ):
            return Agent(config=Config(), workdir=tmp_path)

    def test_agent_has_discovered_tools_attr(self, tmp_path):
        agent = self._make_agent(tmp_path)
        assert hasattr(agent, "_discovered_tools")
        assert isinstance(agent._discovered_tools, set)
        assert len(agent._discovered_tools) == 0

    def test_make_tool_context_passes_workdir(self, tmp_path):
        agent = self._make_agent(tmp_path)
        ctx = agent._make_tool_context()
        assert ctx.workdir == tmp_path

    def test_make_tool_context_passes_skill_manager(self, tmp_path):
        agent = self._make_agent(tmp_path)
        ctx = agent._make_tool_context()
        assert ctx.skill_manager is agent.skills

    def test_make_tool_context_on_tools_discovered_updates_set(self, tmp_path):
        agent = self._make_agent(tmp_path)
        ctx = agent._make_tool_context()
        ctx.on_tools_discovered({"WebFetch", "CsvAnalyze"})
        assert "WebFetch" in agent._discovered_tools
        assert "CsvAnalyze" in agent._discovered_tools

    def test_definitions_called_with_discovered(self, tmp_path):
        agent = self._make_agent(tmp_path)
        agent._discovered_tools.add("WebFetch")
        agent._max_tool_rounds = 1

        with patch("bourbon.agent.definitions") as mock_definitions:
            mock_definitions.return_value = []
            try:
                agent._run_conversation_loop()
            except Exception:
                pass

            found = False
            for call in mock_definitions.call_args_list:
                if call.kwargs.get("discovered") is not None:
                    assert "WebFetch" in call.kwargs["discovered"]
                    found = True
                    break
            assert found, "definitions() was never called with discovered= kwarg"
