from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from bourbon.access_control.capabilities import CapabilityType
from bourbon.access_control.policy import CapabilityDecision, PolicyAction, PolicyDecision
from bourbon.agent import Agent
from bourbon.config import Config
from bourbon.permissions import PermissionChoice, SessionPermissionStore


def make_agent_stub() -> Agent:
    agent = object.__new__(Agent)
    agent.config = Config()
    agent.workdir = Path.cwd()
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.todos = SimpleNamespace(
        update=lambda items: "updated",
        has_open_items=lambda: False,
        render=lambda: "",
    )
    agent.skills = SimpleNamespace(
        activate=lambda name: f"skill:{name}",
        get_catalog=lambda: "",
        available_skills=[],
    )
    agent.compressor = None
    agent.llm = MagicMock()
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent._tool_consecutive_failures = {}
    agent._max_tool_consecutive_failures = 3
    agent._discovered_tools = set()
    agent.audit = MagicMock()
    agent.access_controller = MagicMock()
    agent.sandbox = MagicMock(enabled=False)
    agent.session_permissions = SessionPermissionStore()
    agent.active_permission_request = None
    agent.suspended_tool_round = None
    agent.session = MagicMock()
    agent.session.add_message = MagicMock()
    agent.session.save = MagicMock()
    agent._run_conversation_loop = MagicMock(return_value="Mock")
    return agent


def allow_decision() -> PolicyDecision:
    return PolicyDecision(
        action=PolicyAction.ALLOW,
        reason="all capabilities allowed",
        decisions=[
            CapabilityDecision(
                capability=CapabilityType.EXEC,
                action=PolicyAction.ALLOW,
                matched_rule="default",
            )
        ],
    )


def approval_decision() -> PolicyDecision:
    return PolicyDecision(
        action=PolicyAction.NEED_APPROVAL,
        reason="exec: need_approval (command.need_approval: pip install *)",
        decisions=[
            CapabilityDecision(
                capability=CapabilityType.EXEC,
                action=PolicyAction.NEED_APPROVAL,
                matched_rule="command.need_approval: pip install *",
            )
        ],
    )


def test_execute_tools_suspends_round_on_permission_request(monkeypatch) -> None:
    agent = make_agent_stub()
    agent.access_controller.evaluate.side_effect = [allow_decision(), approval_decision()]
    registry = MagicMock()
    registry.call.side_effect = ["read ok", "should not execute"]
    monkeypatch.setattr("bourbon.agent.get_registry", lambda: registry)
    monkeypatch.setattr(
        "bourbon.agent.get_tool_with_metadata",
        lambda name: SimpleNamespace(
            is_destructive=False,
            is_high_risk_operation=lambda tool_input: False,
        ),
    )

    results = agent._execute_tools(
        [
            {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "README.md"}},
            {"type": "tool_use", "id": "tool-2", "name": "Bash", "input": {"command": "pip install flask"}},
        ],
        source_assistant_uuid=uuid4(),
    )

    assert results == [{"type": "tool_result", "tool_use_id": "tool-1", "content": "read ok"}]
    assert agent.active_permission_request is not None
    assert agent.active_permission_request.tool_use_id == "tool-2"
    assert agent.suspended_tool_round is not None
    assert agent.suspended_tool_round.next_tool_index == 1
    assert registry.call.call_count == 1


def test_resume_permission_request_allow_session_stores_rule(monkeypatch) -> None:
    agent = make_agent_stub()
    agent.access_controller.evaluate.return_value = approval_decision()
    registry = MagicMock()
    registry.call.return_value = "installed"
    monkeypatch.setattr("bourbon.agent.get_registry", lambda: registry)
    monkeypatch.setattr(
        "bourbon.agent.get_tool_with_metadata",
        lambda name: SimpleNamespace(
            is_destructive=False,
            is_high_risk_operation=lambda tool_input: False,
        ),
    )

    agent._execute_tools(
        [{"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "pip install flask"}}],
        source_assistant_uuid=uuid4(),
    )

    output = agent.resume_permission_request(PermissionChoice.ALLOW_SESSION)

    assert output == "Mock"
    assert agent.session_permissions._rules
    assert agent.active_permission_request is None
    assert agent.suspended_tool_round is None
    assert registry.call.call_count == 1
    tool_turn_msg = agent.session.add_message.call_args.args[0]
    assert tool_turn_msg.content[0].content == "installed"


def test_resume_permission_request_reject_creates_error_tool_result(monkeypatch) -> None:
    agent = make_agent_stub()
    agent.access_controller.evaluate.return_value = approval_decision()
    registry = MagicMock()
    monkeypatch.setattr("bourbon.agent.get_registry", lambda: registry)
    monkeypatch.setattr(
        "bourbon.agent.get_tool_with_metadata",
        lambda name: SimpleNamespace(
            is_destructive=False,
            is_high_risk_operation=lambda tool_input: False,
        ),
    )

    agent._execute_tools(
        [{"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "pip install flask"}}],
        source_assistant_uuid=uuid4(),
    )

    output = agent.resume_permission_request(PermissionChoice.REJECT)

    assert output == "Mock"
    assert registry.call.call_count == 0
    tool_turn_msg = agent.session.add_message.call_args.args[0]
    assert tool_turn_msg.content[0].is_error is True
    assert "Rejected by user" in tool_turn_msg.content[0].content


def test_suspended_tool_round_has_task_nudge_tool_use_blocks_default() -> None:
    from bourbon.permissions.runtime import SuspendedToolRound

    mock_request = object()
    round_state = SuspendedToolRound(
        source_assistant_uuid=None,
        tool_use_blocks=[{"id": "1"}],
        completed_results=[],
        next_tool_index=0,
        active_request=mock_request,
    )

    assert round_state.task_nudge_tool_use_blocks == []


def test_suspended_tool_round_accepts_task_nudge_blocks() -> None:
    from bourbon.permissions.runtime import SuspendedToolRound

    nudge_blocks = [{"id": "a"}, {"id": "b"}]
    round_state = SuspendedToolRound(
        source_assistant_uuid=None,
        tool_use_blocks=[{"id": "1"}],
        completed_results=[],
        next_tool_index=0,
        active_request=object(),
        task_nudge_tool_use_blocks=nudge_blocks,
    )

    assert round_state.task_nudge_tool_use_blocks == nudge_blocks
