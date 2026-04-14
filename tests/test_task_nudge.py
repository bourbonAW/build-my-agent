"""Tests for Task Nudge mechanism (_append_task_nudge_if_due)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from bourbon.agent import Agent
from bourbon.session.types import MessageRole, TextBlock, TranscriptMessage
from bourbon.tasks.constants import TASK_V2_TOOLS


def make_agent_for_nudge():
    """Create a minimal Agent instance for nudge testing."""
    agent = object.__new__(Agent)
    agent.config = MagicMock()
    agent.config.tasks.storage_dir = "/tmp/bourbon_nudge_test"
    agent.workdir = Path.cwd()
    agent.task_list_id_override = None
    agent._rounds_without_task = 0
    agent.session = MagicMock()
    agent.session.session_id = "test-session-123"
    return agent


def make_tool_result_msg():
    return TranscriptMessage(
        role=MessageRole.USER,
        content=[TextBlock(text="some tool result")],
    )


def make_blocks(*names):
    return [{"id": f"id{i}", "name": name, "input": {}} for i, name in enumerate(names)]


def task_reminder_texts(msg):
    return [
        block.text
        for block in msg.content
        if isinstance(block, TextBlock) and "<task_reminder>" in block.text
    ]


def test_nudge_not_triggered_below_threshold():
    agent = make_agent_for_nudge()
    msg = make_tool_result_msg()

    for _ in range(9):
        agent._append_task_nudge_if_due(msg, make_blocks("Read"))

    assert agent._rounds_without_task == 9
    assert task_reminder_texts(msg) == []


def test_nudge_triggered_at_threshold_when_pending_tasks():
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 9
    msg = make_tool_result_msg()
    initial_len = len(msg.content)

    fake_task = MagicMock()
    fake_task.status = "pending"
    fake_task.subject = "Fix the bug"
    fake_task.blocked_by = []

    with (
        patch("bourbon.tasks.service.TaskService") as mock_service_cls,
        patch("bourbon.tasks.store.TaskStore"),
    ):
        mock_service_instance = MagicMock()
        mock_service_instance.list_tasks.return_value = [fake_task]
        mock_service_cls.return_value = mock_service_instance

        agent._append_task_nudge_if_due(msg, make_blocks("Read"))

    assert agent._rounds_without_task == 0
    assert len(msg.content) == initial_len + 1
    nudge_text = msg.content[-1].text
    assert "<task_reminder>" in nudge_text
    assert "Fix the bug" in nudge_text


def test_nudge_not_appended_when_no_pending_tasks():
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 9
    msg = make_tool_result_msg()
    initial_len = len(msg.content)

    with (
        patch("bourbon.tasks.service.TaskService") as mock_service_cls,
        patch("bourbon.tasks.store.TaskStore"),
    ):
        mock_service_instance = MagicMock()
        mock_service_instance.list_tasks.return_value = []
        mock_service_cls.return_value = mock_service_instance

        agent._append_task_nudge_if_due(msg, make_blocks("Read"))

    assert agent._rounds_without_task == 0
    assert len(msg.content) == initial_len


def test_counter_resets_when_task_tool_used():
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 5
    msg = make_tool_result_msg()

    agent._append_task_nudge_if_due(msg, make_blocks("TaskCreate", "Read"))

    assert agent._rounds_without_task == 0


def test_counter_increments_without_task_tool_below_threshold():
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 3
    msg = make_tool_result_msg()

    agent._append_task_nudge_if_due(msg, make_blocks("Read", "Grep"))

    assert agent._rounds_without_task == 4


def test_defensive_getattr_when_rounds_not_initialized():
    """object.__new__(Agent) bypasses __init__; _rounds_without_task may not exist."""
    agent = make_agent_for_nudge()
    del agent._rounds_without_task
    msg = make_tool_result_msg()

    agent._append_task_nudge_if_due(msg, make_blocks("Read"))

    assert hasattr(agent, "_rounds_without_task")


def test_empty_blocks_returns_early():
    """No tool use blocks means no counting or nudge."""
    agent = make_agent_for_nudge()
    agent._rounds_without_task = 5
    msg = make_tool_result_msg()
    initial_len = len(msg.content)

    agent._append_task_nudge_if_due(msg, [])

    assert agent._rounds_without_task == 5
    assert len(msg.content) == initial_len


def test_task_v2_tools_are_reset_triggers():
    agent = make_agent_for_nudge()
    msg = make_tool_result_msg()

    for tool_name in TASK_V2_TOOLS:
        agent._rounds_without_task = 5
        agent._append_task_nudge_if_due(msg, make_blocks(tool_name))
        assert agent._rounds_without_task == 0


def test_resume_permission_request_injects_nudge(tmp_path):
    """resume_permission_request must call _append_task_nudge_if_due on tool_turn_msg."""
    from uuid import uuid4

    from bourbon.agent import TASK_NUDGE_THRESHOLD
    from bourbon.permissions import PermissionChoice
    from bourbon.permissions.runtime import SuspendedToolRound

    agent = object.__new__(Agent)
    agent.config = MagicMock()
    agent.config.tasks.storage_dir = str(tmp_path)
    agent.workdir = tmp_path
    agent.session = MagicMock()
    agent.session.session_id = "resume-test-session"
    agent.session_permissions = MagicMock()
    agent.session_permissions.add = MagicMock()
    agent.active_permission_request = None
    agent.suspended_tool_round = None
    agent._subagent_tool_filter = None
    agent._subagent_agent_def = None
    agent._tool_consecutive_failures = {}
    agent._max_tool_consecutive_failures = 3
    agent.task_list_id_override = None
    agent._rounds_without_task = TASK_NUDGE_THRESHOLD - 1

    src_uuid = uuid4()
    nudge_blocks = [{"id": "n1", "name": "Read", "input": {}}]
    request = MagicMock()
    request.tool_use_id = "ask1"
    request.tool_name = "Bash"
    request.tool_input = {"command": "ls"}
    request.match_candidate = None

    suspended = SuspendedToolRound(
        source_assistant_uuid=src_uuid,
        tool_use_blocks=nudge_blocks,
        completed_results=[],
        next_tool_index=0,
        active_request=request,
        task_nudge_tool_use_blocks=nudge_blocks,
    )
    agent.suspended_tool_round = suspended

    captured_tool_turn_msg = []

    def fake_add_message(msg):
        captured_tool_turn_msg.append(msg)

    agent.session.add_message = fake_add_message
    agent.session.save = MagicMock()
    agent._execute_regular_tool = MagicMock(return_value="bash output")
    agent._subagent_tool_denial = MagicMock(return_value=None)

    def fake_build_transcript(results, uuid):
        return TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="tool results")],
        )

    agent._build_tool_results_transcript_message = fake_build_transcript
    agent._run_conversation_loop = MagicMock(return_value="final response")

    fake_task = MagicMock()
    fake_task.status = "pending"
    fake_task.subject = "Important pending task"
    fake_task.blocked_by = []

    with (
        patch("bourbon.tasks.service.TaskService") as mock_service_cls,
        patch("bourbon.tasks.store.TaskStore"),
    ):
        mock_service_cls.return_value.list_tasks.return_value = [fake_task]
        agent.resume_permission_request(PermissionChoice.ALLOW_ONCE)

    assert len(captured_tool_turn_msg) == 1
    reminder_texts = task_reminder_texts(captured_tool_turn_msg[0])
    assert len(reminder_texts) == 1
    assert "Important pending task" in reminder_texts[0]
