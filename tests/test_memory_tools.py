import json
from pathlib import Path

from bourbon.tools import ToolContext, _ensure_imports, get_registry


def test_memory_tools_registered() -> None:
    _ensure_imports()
    registry = get_registry()
    tool_names = [tool.name for tool in registry._tools.values()]
    assert "MemorySearch" in tool_names
    assert "MemoryWrite" in tool_names
    assert "MemoryStatus" in tool_names


def test_memory_write_tool_schema() -> None:
    _ensure_imports()
    registry = get_registry()
    tool = registry.get_tool("MemoryWrite")
    assert tool is not None
    schema = tool.input_schema
    assert "content" in schema["properties"]
    assert "kind" in schema["properties"]


def test_memory_search_tool_schema() -> None:
    _ensure_imports()
    registry = get_registry()
    tool = registry.get_tool("MemorySearch")
    assert tool is not None
    schema = tool.input_schema
    assert "query" in schema["properties"]


def test_memory_tools_return_error_when_disabled() -> None:
    from bourbon.tools.memory import memory_search, memory_status, memory_write

    ctx = ToolContext(workdir=Path("/tmp"))

    result = json.loads(memory_search(query="test", ctx=ctx))
    assert "error" in result

    result = json.loads(
        memory_write(
            content="test",
            kind="project",
            scope="project",
            source="user",
            ctx=ctx,
        )
    )
    assert "error" in result

    result = json.loads(memory_status(ctx=ctx))
    assert "error" in result
