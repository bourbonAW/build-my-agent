from datetime import datetime

from bourbon.subagent.result import AgentToolResult, finalize_agent_tool
from bourbon.subagent.types import SubagentRun


def test_agent_tool_result_creation():
    result = AgentToolResult(
        run_id="abc123",
        agent_type="coder",
        content="Run completed successfully",
        total_duration_ms=5000,
        total_tokens=1000,
        total_tool_calls=5,
    )

    assert result.run_id == "abc123"
    assert result.agent_type == "coder"
    assert result.total_tool_calls == 5


def test_agent_tool_result_to_notification():
    result = AgentToolResult(
        run_id="abc123",
        agent_type="coder",
        content="Refactoring complete.\n\nUpdated 3 files.",
        total_duration_ms=12500,
        total_tokens=2450,
        total_tool_calls=8,
        description="Refactor auth module",
    )

    notification = result.to_notification()

    assert "abc123" in notification
    assert "Refactor auth module" in notification
    assert "12.5s" in notification
    assert "2450" in notification
    assert "/run-show abc123" in notification


def test_notification_truncates_long_content():
    result = AgentToolResult(
        run_id="abc123",
        agent_type="coder",
        content="x" * 600,
        total_duration_ms=1000,
        total_tokens=10,
        total_tool_calls=1,
    )

    notification = result.to_notification()

    assert "x" * 500 in notification
    assert "..." in notification


def test_finalize_agent_tool_basic():
    run = SubagentRun(
        run_id="test123",
        description="Test run",
        prompt="Do something",
        agent_type="default",
    )
    run.tool_call_count = 5
    run.total_tokens = 1000
    start_time = datetime.now().timestamp() * 1000 - 5000

    result = finalize_agent_tool(
        run=run,
        messages=[],
        final_content="Run done",
        start_time_ms=start_time,
    )

    assert result.run_id == "test123"
    assert result.description == "Test run"
    assert result.content == "Run done"
    assert result.total_duration_ms >= 5000
    assert result.total_tool_calls == 5
    assert result.total_tokens == 1000
    assert result.usage == {"input_tokens": 500, "output_tokens": 500}
