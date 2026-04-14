"""Tests for REPL task and todo commands."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from bourbon.config import Config
from bourbon.repl import REPL
from bourbon.tasks.service import TaskService
from bourbon.tasks.store import TaskStore


def _make_repl(tmp_path, *, session_id: str = "session-123", todos_output: str = "No todos."):
    repl = object.__new__(REPL)
    repl.console = MagicMock()

    config = Config()
    config.tasks.storage_dir = str(tmp_path)

    repl.agent = SimpleNamespace(
        config=config,
        session=SimpleNamespace(session_id=session_id),
        get_todos=MagicMock(return_value=todos_output),
        subagent_manager=SimpleNamespace(
            render_run_list=MagicMock(return_value="run-1 [running] Explore code"),
            get_run_output=MagicMock(return_value="run output"),
            stop_run=MagicMock(return_value="Stopped run: run-1"),
        ),
    )
    return repl


def _printed_text(repl: REPL) -> str:
    return "\n".join(str(call.args[0]) for call in repl.console.print.call_args_list if call.args)


def _rendered_console_text(repl: REPL) -> str:
    return repl.console.export_text()


def test_repl_commands_include_todos_and_tasks():
    assert "/todos" in REPL.COMMANDS
    assert "/tasks" in REPL.COMMANDS
    assert "/runs" in REPL.COMMANDS
    assert "/run-show <id>" in REPL.COMMANDS
    assert "/run-stop <id>" in REPL.COMMANDS


def test_todos_command_prints_legacy_todo_output(tmp_path):
    repl = _make_repl(tmp_path, todos_output="[>] Keep legacy Todo V1")

    repl._handle_command("/todos")

    repl.agent.get_todos.assert_called_once_with()
    assert "[>] Keep legacy Todo V1" in _printed_text(repl)


def test_runs_command_prints_runtime_jobs(tmp_path):
    repl = _make_repl(tmp_path)

    repl._handle_command("/runs")

    repl.agent.subagent_manager.render_run_list.assert_called_once_with()
    assert "run-1 [running] Explore code" in _printed_text(repl)


def test_run_show_command_prints_runtime_output(tmp_path):
    repl = _make_repl(tmp_path)

    repl._handle_command("/run-show run-1")

    repl.agent.subagent_manager.get_run_output.assert_called_once_with("run-1")
    assert "run output" in _printed_text(repl)


def test_run_stop_command_stops_runtime_job(tmp_path):
    repl = _make_repl(tmp_path)

    repl._handle_command("/run-stop run-1")

    repl.agent.subagent_manager.stop_run.assert_called_once_with("run-1")
    assert "Stopped run: run-1" in _printed_text(repl)


def test_tasks_command_prints_workflow_tasks_from_current_session_list(tmp_path):
    repl = _make_repl(tmp_path)
    service = TaskService(TaskStore(tmp_path))
    service.create_task(
        "session-123",
        "Draft REPL task output",
        "Render workflow Task V2 items in /tasks",
        active_form="Drafting REPL task output",
    )
    service.create_task(
        "other-session",
        "Wrong list",
        "Should not appear in this REPL session",
    )

    repl._handle_command("/tasks")

    printed = _printed_text(repl)
    assert "Draft REPL task output" in printed
    assert "other-session" not in printed
    assert "Wrong list" not in printed


def test_tasks_command_renders_status_tokens_literally(tmp_path):
    repl = _make_repl(tmp_path)
    repl.console = Console(record=True, width=120, force_terminal=False, color_system=None)
    service = TaskService(TaskStore(tmp_path))
    service.create_task("session-123", "Pending task", "Show pending status")
    active = service.create_task("session-123", "Active task", "Show in_progress status")
    service.update_task("session-123", active.id, status="in_progress", owner="agent-5")

    repl._handle_command("/tasks")

    printed = _rendered_console_text(repl)
    assert "pending" in printed
    assert "in_progress" in printed
    assert "Pending task" in printed
    assert "Active task" in printed


def test_task_show_commands_print_workflow_task_details(tmp_path):
    repl = _make_repl(tmp_path)
    service = TaskService(TaskStore(tmp_path))
    task = service.create_task(
        "session-123",
        "Inspect workflow task",
        "Show detailed output for a single task",
        active_form="Inspecting workflow task",
    )
    service.update_task("session-123", task.id, status="in_progress", owner="agent-5")

    for command in (f"/task {task.id}", f"/task-show {task.id}"):
        repl.console.reset_mock()

        repl._handle_command(command)

        printed = _printed_text(repl)
        assert f"ID: {task.id}" in printed
        assert "Subject: Inspect workflow task" in printed
        assert "Description: Show detailed output for a single task" in printed
        assert "Status: in_progress" in printed
        assert "Owner: agent-5" in printed


def test_workflow_task_output_escapes_bracketed_user_text(tmp_path):
    repl = _make_repl(tmp_path)
    service = TaskService(TaskStore(tmp_path))
    task = service.create_task(
        "session-123",
        "[owner] subject",
        "Description with [bold]markup[/bold]",
        active_form="Working [fast]",
    )
    service.update_task("session-123", task.id, owner="[agent]")

    repl._handle_command("/tasks")
    tasks_output = _printed_text(repl)
    assert r"\[owner] subject" in tasks_output
    assert r"Working \[fast]" in tasks_output
    assert "1. [pending] [owner] subject" not in tasks_output
    assert "(owner: [agent])" not in tasks_output

    repl.console.reset_mock()
    repl._handle_command(f"/task {task.id}")
    task_output = _printed_text(repl)
    assert r"Subject: \[owner] subject" in task_output
    assert r"Description: Description with \[bold]markup\[/bold]" in task_output
    assert r"Active: Working \[fast]" in task_output
    assert r"Owner: \[agent]" in task_output


@pytest.mark.parametrize(
    ("command", "expected_error"),
    [
        ("/exit extra", "Usage: /exit"),
        ("/clear extra", "Usage: /clear"),
        ("/compact foo", "Usage: /compact"),
        ("/skills extra", "Usage: /skills"),
        ("/tasks extra", "Usage: /tasks"),
        ("/runs extra", "Usage: /runs"),
    ],
)
def test_commands_without_arguments_reject_trailing_args(tmp_path, command, expected_error):
    repl = _make_repl(tmp_path)
    repl.agent.clear_history = MagicMock()
    repl.agent.session.maybe_compact = MagicMock()
    repl.agent.skills = MagicMock()

    should_exit = repl._handle_command(command)

    assert should_exit is False
    assert expected_error in _printed_text(repl)
    repl.agent.get_todos.assert_not_called()
    repl.agent.clear_history.assert_not_called()
    repl.agent.session.maybe_compact.assert_not_called()


def test_tasks_command_handles_task_read_failure_without_crashing(tmp_path):
    repl = _make_repl(tmp_path)
    repl._task_service = MagicMock(
        return_value=SimpleNamespace(list_tasks=MagicMock(side_effect=RuntimeError("disk failed")))
    )

    should_exit = repl._handle_command("/tasks")

    assert should_exit is False
    assert "Error reading workflow tasks: disk failed" in _printed_text(repl)


def test_task_command_handles_task_read_failure_without_crashing(tmp_path):
    repl = _make_repl(tmp_path)
    repl._task_service = MagicMock(
        return_value=SimpleNamespace(get_task=MagicMock(side_effect=RuntimeError("disk failed")))
    )

    should_exit = repl._handle_command("/task 1")

    assert should_exit is False
    assert "Error reading workflow task 1: disk failed" in _printed_text(repl)


def test_task_read_failure_renders_bracketed_exception_text_literally(tmp_path):
    repl = _make_repl(tmp_path)
    repl.console = Console(record=True, width=120, force_terminal=False, color_system=None)
    repl._task_service = MagicMock(
        return_value=SimpleNamespace(
            get_task=MagicMock(side_effect=RuntimeError("[boom] disk failed"))
        )
    )

    should_exit = repl._handle_command("/task 1")

    assert should_exit is False
    printed = _rendered_console_text(repl)
    assert "Error reading workflow task 1: [boom] disk failed" in printed


@pytest.mark.parametrize(
    ("command", "service", "expected_text", "unsafe_text"),
    [
        (
            "/task [bold]1",
            SimpleNamespace(get_task=MagicMock(return_value=None)),
            r"Task not found: \[bold]1",
            "Task not found: [bold]1",
        ),
        (
            "/task-show [bold]1",
            SimpleNamespace(get_task=MagicMock(side_effect=RuntimeError("disk failed"))),
            r"Error reading workflow task \[bold]1: disk failed",
            "Error reading workflow task [bold]1: disk failed",
        ),
    ],
)
def test_task_failure_paths_escape_bracketed_task_ids(
    tmp_path, command, service, expected_text, unsafe_text
):
    repl = _make_repl(tmp_path)
    repl._task_service = MagicMock(return_value=service)

    should_exit = repl._handle_command(command)

    assert should_exit is False
    printed = _printed_text(repl)
    assert expected_text in printed
    assert unsafe_text not in printed


@pytest.mark.parametrize("command", ["/task 1 extra", "/task-show 1 extra"])
def test_task_commands_require_exactly_one_argument(tmp_path, command):
    repl = _make_repl(tmp_path)
    repl._render_workflow_task = MagicMock()

    should_exit = repl._handle_command(command)

    assert should_exit is False
    assert "Usage:" in _printed_text(repl)
    repl._render_workflow_task.assert_not_called()


@pytest.mark.parametrize(
    "command",
    ["/run-show", "/run-show 1 extra", "/run-stop", "/run-stop 1 extra"],
)
def test_run_commands_require_exactly_one_argument(tmp_path, command):
    repl = _make_repl(tmp_path)

    should_exit = repl._handle_command(command)

    assert should_exit is False
    assert "Usage:" in _printed_text(repl)
    repl.agent.subagent_manager.get_run_output.assert_not_called()
    repl.agent.subagent_manager.stop_run.assert_not_called()
