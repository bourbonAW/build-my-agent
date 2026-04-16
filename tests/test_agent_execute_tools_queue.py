"""Tests for _execute_tools queue-based refactor."""

from pathlib import Path
from uuid import uuid4

from bourbon.agent import Agent
from bourbon.config import Config
from bourbon.subagent.types import SubagentMode


def make_agent() -> Agent:
    agent = object.__new__(Agent)
    agent.config = Config()
    agent.workdir = Path.cwd()
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.subagent_mode = SubagentMode.NORMAL
    agent.task_list_id_override = None
    agent._rounds_without_task = 0
    agent.suspended_tool_round = None
    agent.active_permission_request = None
    agent.session_permissions = type(
        "FakePermStore",
        (),
        {"has_match": lambda self, *args, **kwargs: False},
    )()
    agent._subagent_tool_filter = None
    agent._subagent_agent_def = None
    agent._tool_consecutive_failures = {}
    agent._max_tool_consecutive_failures = 3
    return agent


def make_initialized_agent(monkeypatch, tmp_path) -> Agent:
    """Create a real Agent while stubbing external LLM credentials and HOME writes."""

    class MockLLM:
        def chat(self, **kwargs):
            return {"content": [], "stop_reason": "end_turn", "usage": {}}

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("bourbon.agent.create_client", lambda config: MockLLM())
    return Agent(Config(), workdir=tmp_path)


def test_agent_init_has_subagent_mode(monkeypatch, tmp_path):
    agent = make_initialized_agent(monkeypatch, tmp_path)

    assert agent.subagent_mode == SubagentMode.NORMAL


def test_agent_init_has_task_list_id_override(monkeypatch, tmp_path):
    agent = make_initialized_agent(monkeypatch, tmp_path)

    assert agent.task_list_id_override is None


def test_agent_init_has_rounds_without_task(monkeypatch, tmp_path):
    agent = make_initialized_agent(monkeypatch, tmp_path)

    assert agent._rounds_without_task == 0


def test_execute_tools_runs_via_queue(monkeypatch):
    """_execute_tools should use ToolExecutionQueue for regular tools."""
    from bourbon.permissions import PermissionAction, PermissionDecision
    from bourbon.tools import Tool
    from bourbon.tools.execution_queue import ToolExecutionQueue

    agent = make_agent()
    called_execute_all = []

    def patched_execute_all(self):
        called_execute_all.append(True)
        return [
            {"type": "tool_result", "tool_use_id": tool.block["id"], "content": "mock"}
            for tool in self._tools
        ]

    def fake_permission(name, inp):
        return PermissionDecision(action=PermissionAction.ALLOW, reason="test")

    def fake_denial(name):
        return None

    def fake_get_tool(name):
        tool = Tool.__new__(Tool)
        object.__setattr__(tool, "name", name)
        tool._concurrency_fn = None
        tool.is_concurrency_safe = True
        tool.is_destructive = False
        tool.concurrent_safe_for = lambda inp: True
        return tool

    monkeypatch.setattr(ToolExecutionQueue, "execute_all", patched_execute_all)
    monkeypatch.setattr(agent, "_permission_decision_for_tool", fake_permission)
    monkeypatch.setattr(agent, "_subagent_tool_denial", fake_denial)
    monkeypatch.setattr(
        agent,
        "_execute_regular_tool_outcome",
        lambda *args, **kwargs: __import__(
            "bourbon.tools.execution_queue", fromlist=["ToolExecutionOutcome"]
        ).ToolExecutionOutcome(content="mock"),
    )
    monkeypatch.setattr("bourbon.agent.get_tool_with_metadata", fake_get_tool)

    blocks = [
        {"id": "t1", "name": "Read", "input": {"file_path": "/tmp/x"}},
        {"id": "t2", "name": "Grep", "input": {"pattern": "foo"}},
    ]
    results = agent._execute_tools(blocks, source_assistant_uuid=uuid4())

    assert called_execute_all, "_execute_tools should have called queue.execute_all()"
    assert len(results) == 2
