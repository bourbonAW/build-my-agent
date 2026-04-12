"""Tests for the TodoWrite tool registration and dispatch path."""

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from bourbon.access_control.policy import PolicyAction
from bourbon.agent import Agent
from bourbon.todos import TodoManager
from bourbon.tools import ToolContext, definitions, get_registry


def test_todowrite_appears_in_tool_definitions():
    names = {tool["name"] for tool in definitions()}
    assert "TodoWrite" in names


def test_todowrite_registry_call_updates_agent_todos_and_returns_render():
    definitions()

    agent = object.__new__(Agent)
    agent.todos = TodoManager()

    ctx = ToolContext(workdir=Path("/tmp"), agent=agent)
    items = [
        {"content": "Inspect registry path", "status": "in_progress", "activeForm": "Inspecting"},
        {"content": "Add TodoWrite tool", "status": "pending"},
    ]

    result = get_registry().call("TodoWrite", {"items": items}, ctx)

    assert result == agent.todos.render()
    assert "[>] Inspect registry path <- Inspecting" in result
    assert "[ ] Add TodoWrite tool" in result
    assert [item["content"] for item in agent.todos.to_list()] == [
        "Inspect registry path",
        "Add TodoWrite tool",
    ]


def test_tool_context_agent_field_is_optional():
    ctx = ToolContext(workdir=Path("/tmp"))
    assert ctx.agent is None


def test_todowrite_registry_call_marks_todo_usage():
    agent = object.__new__(Agent)
    agent.todos = TodoManager()

    ctx = ToolContext(workdir=Path("/tmp"), agent=agent)
    get_registry().call("TodoWrite", {"items": []}, ctx)

    assert "todo" in ctx.execution_markers


def test_execute_tools_has_no_todowrite_special_case():
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
    agent._rounds_without_todo = 0

    monkeypatch.setattr(agent, "_execute_regular_tool", lambda *args, **kwargs: "ok")
    monkeypatch.setattr(agent, "_record_policy_decision", lambda **kwargs: None)

    results = agent._execute_tools(
        [{"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "x"}}],
        source_assistant_uuid=uuid4(),
    )

    assert results == [{"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}]


def test_successful_noop_todowrite_resets_todo_nag_counter():
    definitions()

    agent = object.__new__(Agent)
    agent.workdir = Path("/tmp")
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.todos = SimpleNamespace(
        update=lambda items: "unchanged",
        has_open_items=lambda: True,
    )
    agent.skills = MagicMock()
    agent._discovered_tools = set()
    agent.audit = MagicMock()
    agent.sandbox = MagicMock(enabled=False)
    agent.access_controller = MagicMock()
    agent.access_controller.evaluate.return_value = SimpleNamespace(
        action=PolicyAction.ALLOW,
        reason="allowed",
    )
    agent._record_policy_decision = MagicMock()
    agent._tool_consecutive_failures = {}
    agent._max_tool_consecutive_failures = 3
    agent._rounds_without_todo = 2

    results = agent._execute_tools(
        [{"type": "tool_use", "id": "tool-1", "name": "TodoWrite", "input": {"items": []}}],
        source_assistant_uuid=uuid4(),
    )

    assert agent._rounds_without_todo == 0
    assert results == [{"type": "tool_result", "tool_use_id": "tool-1", "content": "unchanged"}]
