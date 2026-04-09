from pathlib import Path

from bourbon.permissions.matching import build_match_candidate
from bourbon.permissions.runtime import (
    PermissionChoice,
    PermissionRequest,
    SessionPermissionStore,
    SuspendedToolRound,
)


def test_permission_request_defaults_to_three_claude_style_choices():
    request = PermissionRequest(
        request_id="req-1",
        tool_use_id="tool-1",
        tool_name="Bash",
        tool_input={"command": "pip install flask"},
        title="Bash command",
        description="Install a package",
        reason="exec: need_approval (command.need_approval: pip install *)",
        match_candidate={"kind": "command_prefix", "value": "pip install"},
    )

    assert request.options == (
        PermissionChoice.ALLOW_ONCE,
        PermissionChoice.ALLOW_SESSION,
        PermissionChoice.REJECT,
    )


def test_session_permission_store_is_process_local_and_empty_by_default():
    store = SessionPermissionStore()

    assert store.has_match("Bash", {"command": "pip install flask"}) is False


def test_suspended_tool_round_tracks_progress_and_active_request():
    request = PermissionRequest(
        request_id="req-1",
        tool_use_id="tool-2",
        tool_name="Write",
        tool_input={"path": "notes/todo.md", "content": "hello"},
        title="Write file",
        description="Create notes/todo.md",
        reason="file_write: need_approval (default)",
        match_candidate={"kind": "parent_dir", "value": "notes"},
    )
    round_state = SuspendedToolRound(
        source_assistant_uuid=None,
        tool_use_blocks=[{"id": "tool-1"}, {"id": "tool-2"}],
        completed_results=[{"tool_use_id": "tool-1", "content": "ok"}],
        next_tool_index=1,
        active_request=request,
    )

    assert round_state.next_tool_index == 1
    assert round_state.active_request.tool_use_id == "tool-2"


def test_session_permission_store_uses_tool_aware_matching(tmp_path: Path):
    store = SessionPermissionStore()
    candidate = build_match_candidate("Bash", {"command": "pip install flask"}, tmp_path)

    store.add(candidate)

    assert store.has_match("Bash", {"command": "pip install requests"}, tmp_path) is True
    assert store.has_match("Bash", {"command": "uv run pytest"}, tmp_path) is False
