from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from bourbon.config import Config
from bourbon.subagent.manager import SubagentManager
from bourbon.subagent.tools import AGENT_TYPE_CONFIGS, ToolFilter
from bourbon.subagent.types import SubagentRun
from bourbon.tools import definitions


def _make_agent(tmp_path):
    from bourbon.agent import Agent

    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        return Agent(config=Config(), workdir=tmp_path)


def test_subagent_tool_definitions_hide_disallowed_tools(tmp_path):
    agent = _make_agent(tmp_path)
    agent._subagent_agent_def = AGENT_TYPE_CONFIGS["explore"]
    agent._subagent_tool_filter = ToolFilter()

    all_names = {tool["name"] for tool in definitions()}
    names = {tool["name"] for tool in agent._tool_definitions()}

    assert "Read" in names
    if "WebFetch" in all_names:
        assert "WebFetch" in names
    assert "Write" not in names
    assert "Agent" not in names
    assert "TodoWrite" not in names


def test_subagent_execution_denies_hidden_special_tool(tmp_path):
    agent = _make_agent(tmp_path)
    agent._subagent_agent_def = AGENT_TYPE_CONFIGS["default"]
    agent._subagent_tool_filter = ToolFilter()
    agent._manual_compact = MagicMock()

    results = agent._execute_tools(
        [{"id": "toolu_1", "name": "compress", "input": {}}],
        source_assistant_uuid=uuid4(),
    )

    assert results == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "Denied: Tool 'compress' is not available to default subagents.",
            "is_error": True,
        }
    ]
    agent._manual_compact.assert_not_called()


def test_manager_installs_runtime_tool_filter_on_created_subagent(tmp_path):
    parent = SimpleNamespace(system_prompt="parent prompt", _session_manager=None)
    manager = SubagentManager(config=Config(), workdir=tmp_path, parent_agent=parent)
    run = SubagentRun(
        description="Explore",
        prompt="Inspect only",
        agent_type="explore",
    )

    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        subagent = manager._create_subagent(run, AGENT_TYPE_CONFIGS["explore"])

    assert subagent._subagent_agent_def is AGENT_TYPE_CONFIGS["explore"]
    assert isinstance(subagent._subagent_tool_filter, ToolFilter)
