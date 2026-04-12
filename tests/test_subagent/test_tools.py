from bourbon import tools as bourbon_tools
from bourbon.subagent.tools import (
    AGENT_TYPE_CONFIGS,
    ALL_AGENT_DISALLOWED_TOOLS,
    ToolFilter,
)
from bourbon.subagent.types import AgentDefinition


def test_global_disallowed_tools():
    assert "Agent" in ALL_AGENT_DISALLOWED_TOOLS
    assert "TodoWrite" in ALL_AGENT_DISALLOWED_TOOLS


def test_agent_type_configs_exist():
    assert "default" in AGENT_TYPE_CONFIGS
    assert "coder" in AGENT_TYPE_CONFIGS
    assert "explore" in AGENT_TYPE_CONFIGS
    assert "plan" in AGENT_TYPE_CONFIGS
    assert "quick_task" in AGENT_TYPE_CONFIGS


def test_explore_agent_restricted_tools():
    explore_def = AGENT_TYPE_CONFIGS["explore"]

    assert explore_def.allowed_tools == ["Read", "Glob", "Grep", "AstGrep", "WebFetch"]


def test_tool_filter_allows_readonly_tools():
    filter_engine = ToolFilter()
    explore_def = AGENT_TYPE_CONFIGS["explore"]

    assert filter_engine.is_allowed("Read", explore_def) is True
    assert filter_engine.is_allowed("Grep", explore_def) is True


def test_tool_filter_blocks_write_for_explore():
    filter_engine = ToolFilter()
    explore_def = AGENT_TYPE_CONFIGS["explore"]

    assert filter_engine.is_allowed("Write", explore_def) is False
    assert filter_engine.is_allowed("Edit", explore_def) is False


def test_tool_filter_blocks_agent_tool_for_all_profiles():
    filter_engine = ToolFilter()

    for agent_def in AGENT_TYPE_CONFIGS.values():
        assert filter_engine.is_allowed("Agent", agent_def) is False


def test_tool_filter_blocks_todowrite_for_all_profiles():
    filter_engine = ToolFilter()

    for agent_def in AGENT_TYPE_CONFIGS.values():
        assert filter_engine.is_allowed("TodoWrite", agent_def) is False


def test_tool_filter_allows_all_non_global_tools_for_coder():
    filter_engine = ToolFilter()
    coder_def = AGENT_TYPE_CONFIGS["coder"]

    assert filter_engine.is_allowed("Read", coder_def) is True
    assert filter_engine.is_allowed("Write", coder_def) is True
    assert filter_engine.is_allowed("Bash", coder_def) is True


def test_tool_filter_custom_disallowed():
    custom_def = AgentDefinition(
        agent_type="custom",
        description="Test",
        disallowed_tools=["Bash", "WebFetch"],
    )
    filter_engine = ToolFilter()

    assert filter_engine.is_allowed("Read", custom_def) is True
    assert filter_engine.is_allowed("Bash", custom_def) is False
    assert filter_engine.is_allowed("WebFetch", custom_def) is False


def test_filter_tools_uses_tool_definition_names():
    bourbon_tools.definitions()
    tool_defs = [
        {"name": "Read"},
        {"name": "Write"},
        {"name": "TodoWrite"},
        {"name": "WebFetch"},
    ]
    filter_engine = ToolFilter()

    filtered = filter_engine.filter_tools(tool_defs, AGENT_TYPE_CONFIGS["explore"])

    assert [tool["name"] for tool in filtered] == ["Read", "WebFetch"]


def test_tool_filter_exported_from_package():
    from bourbon.subagent import ToolFilter as ExportedToolFilter

    assert ExportedToolFilter is ToolFilter
