import json
from pathlib import Path

from bourbon.tools import ToolContext, _ensure_imports, get_registry


def test_memory_tools_registered() -> None:
    _ensure_imports()
    registry = get_registry()
    # Primary names (tool.name) must be snake_case to match plan spec and LLM tool definitions
    tool_primary_names = [tool.name for tool in registry.list_tools()]
    assert "memory_search" in tool_primary_names
    assert "memory_write" in tool_primary_names
    assert "memory_status" in tool_primary_names
    # PascalCase aliases still resolve for backward compatibility
    assert registry.get_tool("MemorySearch") is not None
    assert registry.get_tool("MemoryWrite") is not None
    assert registry.get_tool("MemoryStatus") is not None


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
    assert "status" in schema["properties"]


def test_memory_search_passes_status_filter_to_manager() -> None:
    from bourbon.tools.memory import memory_search

    class _FakeMemoryManager:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def search(self, query: str, **kwargs: object) -> list[object]:
            self.calls.append({"query": query, **kwargs})
            return []

    fake_manager = _FakeMemoryManager()
    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=fake_manager)

    memory_search(query="test", ctx=ctx, status=["promoted"])

    assert fake_manager.calls == [
        {
            "query": "test",
            "scope": None,
            "kind": None,
            "status": ["promoted"],
            "limit": None,
        }
    ]


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
