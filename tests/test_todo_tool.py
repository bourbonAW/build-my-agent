"""Tests for TodoWrite V1 tool visibility (disabled by default in favour of Task V2)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from bourbon.access_control.policy import PolicyAction
from bourbon.agent import Agent
from bourbon.todos import TodoManager
from bourbon.tools import ToolContext, definitions


def test_todowrite_not_in_tool_definitions():
    """TodoWrite V1 is disabled; LLM should only see Task V2 tools."""
    names = {tool["name"] for tool in definitions()}
    assert "TodoWrite" not in names


def test_tool_context_agent_field_is_optional():
    ctx = ToolContext(workdir=Path("/tmp"))
    assert ctx.agent is None


def test_execute_tools_has_no_todowrite_special_case():
    import inspect

    source = inspect.getsource(Agent._execute_tools)
    assert "TodoWrite" not in source


def test_execute_tools_does_not_require_todo_manager_to_list(monkeypatch):
    agent = object.__new__(Agent)
    agent.workdir = Path("/tmp")
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.todos = SimpleNamespace(has_open_items=lambda: False)
    agent.access_controller = MagicMock()
    agent.access_controller.evaluate.return_value = SimpleNamespace(
        action=PolicyAction.ALLOW,
        reason="allowed",
    )

    monkeypatch.setattr(agent, "_execute_regular_tool", lambda *args, **kwargs: "ok")
    monkeypatch.setattr(agent, "_record_policy_decision", lambda **kwargs: None)

    results = agent._execute_tools(
        [{"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "x"}}],
        source_assistant_uuid=uuid4(),
    )

    assert results == [{"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}]
