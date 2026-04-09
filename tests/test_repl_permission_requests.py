from unittest.mock import MagicMock

from bourbon.permissions.runtime import PermissionChoice, PermissionRequest
from bourbon.repl import REPL


def test_handle_permission_request_calls_resume_api_not_process_input():
    repl = object.__new__(REPL)
    repl.console = MagicMock()
    repl.style = None
    repl.agent = MagicMock()
    repl.session = MagicMock()
    repl._process_input = MagicMock()
    repl._print_response = MagicMock()

    repl.agent.active_permission_request = PermissionRequest(
        request_id="req-1",
        tool_use_id="tool-1",
        tool_name="Bash",
        tool_input={"command": "pip install flask"},
        title="Bash command",
        description="pip install flask",
        reason="exec: need_approval (command.need_approval: pip install *)",
        match_candidate={"kind": "command_prefix", "value": "pip install"},
    )
    repl.session.prompt.return_value = "2"
    repl.agent.resume_permission_request.return_value = "done"

    repl._handle_permission_request()

    repl.agent.resume_permission_request.assert_called_once_with(PermissionChoice.ALLOW_SESSION)
    repl._process_input.assert_not_called()
    repl._print_response.assert_called_once_with("done")


def test_handle_permission_request_retries_on_invalid_choice():
    repl = object.__new__(REPL)
    repl.console = MagicMock()
    repl.style = None
    repl.agent = MagicMock()
    repl.session = MagicMock()
    repl._print_response = MagicMock()
    repl.agent.active_permission_request = PermissionRequest(
        request_id="req-1",
        tool_use_id="tool-1",
        tool_name="Write",
        tool_input={"path": "notes/today.md", "content": "hello"},
        title="Write file",
        description="notes/today.md",
        reason="file_write: need_approval (default)",
        match_candidate={"kind": "parent_dir", "value": "notes"},
    )
    repl.session.prompt.side_effect = ["x", "1"]
    repl.agent.resume_permission_request.return_value = "done"

    repl._handle_permission_request()

    assert repl.agent.resume_permission_request.call_count == 1
    repl.console.print.assert_any_call("[red]Invalid choice. Please try again.[/red]")
