"""Tests for SubagentMode-based tool visibility."""

from bourbon.subagent.tools import AGENT_TYPE_CONFIGS, ToolFilter
from bourbon.subagent.types import SubagentMode
from bourbon.tasks.constants import TASK_V2_TOOLS


def test_teammate_in_agent_type_configs():
    assert "teammate" in AGENT_TYPE_CONFIGS
    teammate_def = AGENT_TYPE_CONFIGS["teammate"]
    assert teammate_def.allowed_tools is None


def test_tool_filter_async_blocks_task_tools():
    """ASYNC subagents should not see task management tools."""
    filter_engine = ToolFilter()
    default_def = AGENT_TYPE_CONFIGS["default"]

    for tool_name in TASK_V2_TOOLS:
        result = filter_engine.is_allowed(
            tool_name,
            default_def,
            subagent_mode=SubagentMode.ASYNC,
        )
        assert result is False, f"{tool_name} should be blocked for ASYNC mode"


def test_tool_filter_teammate_allows_task_tools():
    """TEAMMATE subagents must see task management tools."""
    filter_engine = ToolFilter()
    default_def = AGENT_TYPE_CONFIGS["default"]

    for tool_name in TASK_V2_TOOLS:
        result = filter_engine.is_allowed(
            tool_name,
            default_def,
            subagent_mode=SubagentMode.TEAMMATE,
        )
        assert result is True, f"{tool_name} should be allowed for TEAMMATE mode"


def test_tool_filter_normal_mode_unchanged():
    """NORMAL mode does not change existing allowed_tools logic."""
    filter_engine = ToolFilter()
    explore_def = AGENT_TYPE_CONFIGS["explore"]

    assert (
        filter_engine.is_allowed(
            "TaskList",
            explore_def,
            subagent_mode=SubagentMode.NORMAL,
        )
        is False
    )
    assert (
        filter_engine.is_allowed(
            "Read",
            explore_def,
            subagent_mode=SubagentMode.NORMAL,
        )
        is True
    )


def test_global_disallowed_always_blocked_regardless_of_mode():
    """ALL_AGENT_DISALLOWED_TOOLS must block even in TEAMMATE mode."""
    from bourbon.subagent.tools import ALL_AGENT_DISALLOWED_TOOLS

    filter_engine = ToolFilter()
    default_def = AGENT_TYPE_CONFIGS["default"]

    for tool_name in ALL_AGENT_DISALLOWED_TOOLS:
        result = filter_engine.is_allowed(
            tool_name,
            default_def,
            subagent_mode=SubagentMode.TEAMMATE,
        )
        assert result is False, f"{tool_name} must be blocked even in TEAMMATE mode"


def test_filter_tools_passes_subagent_mode():
    """filter_tools() should respect subagent_mode parameter."""
    filter_engine = ToolFilter()
    default_def = AGENT_TYPE_CONFIGS["default"]
    tool_defs = [{"name": tool_name} for tool_name in TASK_V2_TOOLS] + [{"name": "Read"}]

    async_result = filter_engine.filter_tools(
        tool_defs,
        default_def,
        subagent_mode=SubagentMode.ASYNC,
    )
    async_names = {tool["name"] for tool in async_result}
    assert not (async_names & TASK_V2_TOOLS), "Task tools should be removed for ASYNC"
    assert "Read" in async_names

    normal_result = filter_engine.filter_tools(
        tool_defs,
        default_def,
        subagent_mode=SubagentMode.NORMAL,
    )
    normal_names = {tool["name"] for tool in normal_result}
    assert normal_names >= TASK_V2_TOOLS, "Task tools should be visible in NORMAL mode"
