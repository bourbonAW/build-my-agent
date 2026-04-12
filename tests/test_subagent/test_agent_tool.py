from pathlib import Path
from types import SimpleNamespace

from bourbon.subagent.result import AgentToolResult
from bourbon.tools import ToolContext, definitions, get_registry


class FakeSubagentManager:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def test_agent_tool_appears_in_definitions():
    names = {tool["name"] for tool in definitions()}

    assert "Agent" in names


def test_agent_tool_sync_returns_formatted_result():
    manager = FakeSubagentManager(
        AgentToolResult(
            run_id="run123",
            agent_type="coder",
            content="Finished focused work",
            total_duration_ms=2500,
            total_tokens=1200,
            total_tool_calls=4,
        )
    )
    agent = SimpleNamespace(subagent_manager=manager)
    ctx = ToolContext(workdir=Path("/tmp"), agent=agent)

    output = get_registry().call(
        "Agent",
        {
            "description": "Do work",
            "prompt": "Complete this task",
            "subagent_type": "coder",
        },
        ctx,
    )

    assert "Subagent completed in 2.5s" in output
    assert "Tokens: 1200, Tool calls: 4" in output
    assert "Finished focused work" in output
    assert manager.calls == [
        {
            "description": "Do work",
            "prompt": "Complete this task",
            "agent_type": "coder",
            "model": None,
            "max_turns": 50,
            "run_in_background": False,
        }
    ]


def test_agent_tool_background_returns_run_message():
    manager = FakeSubagentManager("run-bg")
    agent = SimpleNamespace(subagent_manager=manager)
    ctx = ToolContext(workdir=Path("/tmp"), agent=agent)

    output = get_registry().call(
        "Agent",
        {
            "description": "Do work",
            "prompt": "Complete this task",
            "run_in_background": True,
        },
        ctx,
    )

    assert output == "Started background run: run-bg\nUse `/run-show run-bg` to check status."
    assert manager.calls[0]["run_in_background"] is True


def test_agent_tool_returns_error_without_manager():
    ctx = ToolContext(workdir=Path("/tmp"))

    output = get_registry().call(
        "Agent",
        {
            "description": "Do work",
            "prompt": "Complete this task",
        },
        ctx,
    )

    assert output.startswith("Error: Agent tool unavailable")
