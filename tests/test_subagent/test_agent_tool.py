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
    assert "AgentWait" in names


def test_agent_tool_schema_warns_explore_cannot_run_bash():
    agent_def = next(tool for tool in definitions() if tool["name"] == "Agent")

    description = agent_def["input_schema"]["properties"]["subagent_type"]["description"]

    assert "explore" in description
    assert "read-only tools" in description
    assert "system information" in description


def test_agent_tool_schema_explains_foreground_parallel_waiting():
    agent_def = next(tool for tool in definitions() if tool["name"] == "Agent")

    tool_description = agent_def["description"]
    background_description = agent_def["input_schema"]["properties"]["run_in_background"][
        "description"
    ]

    assert "multiple foreground Agent tool calls" in tool_description
    assert "same tool round" in tool_description
    assert "waits for all results" in tool_description
    assert "only when the parent can proceed without the result" in background_description


def test_agent_tool_background_points_to_agent_wait_not_repl_command():
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

    assert "AgentWait" in output
    assert "/run-show" not in output


def test_agent_wait_tool_calls_manager_wait_for_runs():
    manager = SimpleNamespace(
        wait_for_runs=lambda run_ids, timeout=None: (
            f"waited for {','.join(run_ids)} with timeout {timeout}"
        )
    )
    agent = SimpleNamespace(subagent_manager=manager)
    ctx = ToolContext(workdir=Path("/tmp"), agent=agent)

    output = get_registry().call(
        "AgentWait",
        {
            "run_ids": ["run-1", "run-2"],
            "timeout_seconds": 3,
        },
        ctx,
    )

    assert output == "waited for run-1,run-2 with timeout 3"


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
            "max_turns": None,
            "run_in_background": False,
        }
    ]


def test_agent_tool_explicit_max_turns_passes_through():
    manager = FakeSubagentManager(
        AgentToolResult(
            run_id="run123",
            agent_type="explore",
            content="Finished focused work",
            total_duration_ms=100,
            total_tokens=10,
            total_tool_calls=1,
        )
    )
    agent = SimpleNamespace(subagent_manager=manager)
    ctx = ToolContext(workdir=Path("/tmp"), agent=agent)

    get_registry().call(
        "Agent",
        {
            "description": "Do work",
            "prompt": "Complete this task",
            "subagent_type": "explore",
            "max_turns": 3,
        },
        ctx,
    )

    assert manager.calls[0]["max_turns"] == 3


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

    assert output == (
        "Started background run: run-bg\n"
        'Use AgentWait with run_ids ["run-bg"] if you need the result before continuing.'
    )
    assert manager.calls[0]["run_in_background"] is True


def test_agent_tool_emits_debug_events(monkeypatch):
    events = []

    def fake_debug_log(event, **fields):
        events.append((event, fields))

    monkeypatch.setattr("bourbon.tools.agent_tool.debug_log", fake_debug_log)
    manager = FakeSubagentManager(
        AgentToolResult(
            run_id="run-debug",
            agent_type="quick_task",
            content="Finished focused work",
            total_duration_ms=100,
            total_tokens=10,
            total_tool_calls=1,
        )
    )
    agent = SimpleNamespace(subagent_manager=manager)
    ctx = ToolContext(workdir=Path("/tmp"), agent=agent)

    get_registry().call(
        "Agent",
        {
            "description": "Debug run",
            "prompt": "Complete this task",
            "subagent_type": "quick_task",
        },
        ctx,
    )

    event_names = [event for event, _fields in events]
    assert event_names == ["agent_tool.spawn.start", "agent_tool.spawn.complete"]
    assert events[0][1]["subagent_type"] == "quick_task"
    assert events[0][1]["max_turns"] is None
    assert events[1][1]["run_id"] == "run-debug"


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
