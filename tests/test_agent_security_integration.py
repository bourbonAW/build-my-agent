"""Tests for agent security integration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from bourbon.access_control.capabilities import CapabilityType
from bourbon.access_control.policy import CapabilityDecision, PolicyAction, PolicyDecision
from bourbon.agent import Agent
from bourbon.audit.events import EventType
from bourbon.config import Config
from bourbon.sandbox.runtime import ResourceUsage, SandboxResult


class MockLLM:
    def chat(self, **kwargs):
        return {
            "content": [{"type": "text", "text": "Mock"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    def chat_stream(self, **kwargs):
        """Mock streaming for tests."""
        yield {"type": "text", "text": "Mock response"}
        yield {"type": "usage", "input_tokens": 10, "output_tokens": 5}
        yield {"type": "stop", "stop_reason": "end_turn"}


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
    agent.llm = MockLLM()
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    agent.audit = MagicMock()
    agent.access_controller = MagicMock()
    agent.sandbox = MagicMock(enabled=False)
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


def deny_decision() -> PolicyDecision:
    return PolicyDecision(
        action=PolicyAction.DENY,
        reason="file_read: deny (file.deny: ~/.ssh/**)",
        decisions=[
            CapabilityDecision(
                capability=CapabilityType.FILE_READ,
                action=PolicyAction.DENY,
                matched_rule="file.deny: ~/.ssh/**",
            )
        ],
    )


def test_agent_init_creates_security_components(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("bourbon.agent.create_client", lambda config: MockLLM())

    agent = Agent(config=Config(), workdir=tmp_path)

    assert agent.audit.enabled is True
    assert agent.access_controller is not None
    assert agent.sandbox is not None


def test_execute_tools_denies_when_policy_blocks(monkeypatch) -> None:
    agent = make_agent_stub()
    agent.access_controller.evaluate.return_value = deny_decision()
    registry = MagicMock()
    registry.call.return_value = "should not run"
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
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "read_file",
                "input": {"path": "~/.ssh/id_rsa"},
            }
        ]
    )

    assert results == [
        {
            "type": "tool_result",
            "tool_use_id": "tool-1",
            "content": "Denied: file_read: deny (file.deny: ~/.ssh/**)",
        }
    ]
    registry.call.assert_not_called()
    policy_event = agent.audit.record.call_args_list[0].args[0]
    assert policy_event.event_type == EventType.POLICY_DECISION


def test_need_approval_executes_once_after_user_approves(monkeypatch) -> None:
    agent = make_agent_stub()
    agent.access_controller.evaluate.return_value = approval_decision()
    registry = MagicMock()
    registry.call = MagicMock(return_value="installed")
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
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "bash",
                "input": {"command": "pip install flask"},
            }
        ]
    )

    assert results[0]["content"].startswith("Requires approval:")
    assert agent.pending_confirmation is not None

    output = agent._handle_confirmation_response("Approve and execute")

    assert output == "installed"
    assert registry.call.call_count == 1
    assert agent.access_controller.evaluate.call_count == 1
    assert agent.pending_confirmation is None


def test_bash_uses_sandbox_when_enabled(monkeypatch) -> None:
    agent = make_agent_stub()
    agent.access_controller.evaluate.return_value = allow_decision()
    agent.sandbox = MagicMock(enabled=True)
    agent.sandbox.execute.return_value = SandboxResult(
        stdout="hello\n",
        stderr="warn\n",
        exit_code=0,
        timed_out=False,
        resource_usage=ResourceUsage(cpu_time=0.1, memory_peak="1M"),
    )
    registry = MagicMock()
    registry.call = MagicMock(return_value="unsandboxed")
    monkeypatch.setattr("bourbon.agent.get_registry", lambda: registry)
    monkeypatch.setattr(
        "bourbon.agent.get_tool_with_metadata",
        lambda name: SimpleNamespace(
            is_destructive=True,
            is_high_risk_operation=lambda tool_input: False,
        ),
    )

    results = agent._execute_tools(
        [{"type": "tool_use", "id": "tool-1", "name": "bash", "input": {"command": "ls -la"}}]
    )

    assert results == [{"type": "tool_result", "tool_use_id": "tool-1", "content": "hello\nwarn"}]
    registry.call.assert_not_called()
    assert agent.sandbox.execute.call_count == 1
    event_types = [call.args[0].event_type for call in agent.audit.record.call_args_list]
    assert event_types == [EventType.POLICY_DECISION, EventType.TOOL_CALL]


def test_read_file_tool_uses_agent_workdir(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello from workdir")

    agent = make_agent_stub()
    agent.workdir = tmp_path
    agent.sandbox = MagicMock(enabled=False)
    agent.access_controller.evaluate.return_value = allow_decision()

    output = agent._execute_regular_tool("read_file", {"path": "note.txt"})

    assert output == "hello from workdir"
