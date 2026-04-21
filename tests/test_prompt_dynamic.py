import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from bourbon.prompt.types import PromptContext


def run(coro):
    return asyncio.run(coro)


def test_skills_section_returns_empty_when_no_manager():
    from bourbon.prompt.dynamic import skills_section

    ctx = PromptContext(workdir=Path("/tmp"), skill_manager=None)
    result = run(skills_section(ctx))
    assert result == ""


def test_skills_section_returns_empty_when_catalog_empty():
    from bourbon.prompt.dynamic import skills_section

    mock_skills = MagicMock()
    mock_skills.get_catalog.return_value = ""
    ctx = PromptContext(workdir=Path("/tmp"), skill_manager=mock_skills)
    result = run(skills_section(ctx))
    assert result == ""


def test_skills_section_returns_catalog_content():
    from bourbon.prompt.dynamic import skills_section

    mock_skills = MagicMock()
    mock_skills.get_catalog.return_value = "my-skill: Does something"
    ctx = PromptContext(workdir=Path("/tmp"), skill_manager=mock_skills)
    result = run(skills_section(ctx))
    assert "SKILLS" in result
    assert "my-skill: Does something" in result
    assert "Skill" in result


def test_mcp_tools_section_returns_empty_when_no_manager():
    from bourbon.prompt.dynamic import mcp_tools_section

    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=None)
    result = run(mcp_tools_section(ctx))
    assert result == ""


def test_mcp_tools_section_returns_empty_when_disabled():
    from bourbon.prompt.dynamic import mcp_tools_section

    mock_mcp = MagicMock()
    mock_mcp.get_connection_summary.return_value = {"enabled": False, "total_tools": 0}
    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=mock_mcp)
    result = run(mcp_tools_section(ctx))
    assert result == ""


def test_mcp_tools_section_returns_empty_when_no_tools():
    from bourbon.prompt.dynamic import mcp_tools_section

    mock_mcp = MagicMock()
    mock_mcp.get_connection_summary.return_value = {"enabled": True, "total_tools": 0}
    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=mock_mcp)
    result = run(mcp_tools_section(ctx))
    assert result == ""


def test_mcp_tools_section_groups_tools_by_server():
    from bourbon.prompt.dynamic import mcp_tools_section

    mock_mcp = MagicMock()
    mock_mcp.get_connection_summary.return_value = {"enabled": True, "total_tools": 2}
    mock_mcp.list_mcp_tools.return_value = ["myserver-tool1", "myserver-tool2"]
    mock_mcp.config.servers = [SimpleNamespace(name="myserver")]
    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=mock_mcp)
    result = run(mcp_tools_section(ctx))
    assert "MCP TOOLS" in result
    assert "myserver:" in result
    assert "myserver-tool1" in result
    assert "myserver-tool2" in result


def test_mcp_tools_section_longest_prefix_match():
    from bourbon.prompt.dynamic import mcp_tools_section

    mock_mcp = MagicMock()
    mock_mcp.get_connection_summary.return_value = {"enabled": True, "total_tools": 2}
    mock_mcp.list_mcp_tools.return_value = ["foo-bar-baz", "foo-qux"]
    mock_mcp.config.servers = [
        SimpleNamespace(name="foo"),
        SimpleNamespace(name="foo-bar"),
    ]
    ctx = PromptContext(workdir=Path("/tmp"), mcp_manager=mock_mcp)
    result = run(mcp_tools_section(ctx))
    assert "foo-bar:" in result
    assert "foo:" in result
    assert "foo-bar-baz" in result
    assert "foo-qux" in result


def test_dynamic_sections_include_memory_anchors():
    from bourbon.prompt.dynamic import DYNAMIC_SECTIONS

    assert len(DYNAMIC_SECTIONS) == 3
    names = [section.name for section in DYNAMIC_SECTIONS]
    assert "memory_anchors" in names
    assert "skills" in names
    assert "mcp_tools" in names


def test_dynamic_sections_orders_match_spec():
    from bourbon.prompt.dynamic import DYNAMIC_SECTIONS

    orders = {section.name: section.order for section in DYNAMIC_SECTIONS}
    assert orders["memory_anchors"] == 15
    assert orders["skills"] == 60
    assert orders["mcp_tools"] == 70
