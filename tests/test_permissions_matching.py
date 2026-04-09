from pathlib import Path

from bourbon.permissions.matching import build_match_candidate, session_rule_matches
from bourbon.permissions.presentation import build_permission_request
from bourbon.permissions.runtime import PermissionAction, PermissionDecision


def test_bash_session_rule_matches_normalized_command_prefix(tmp_path: Path):
    candidate = build_match_candidate("Bash", {"command": "pip install flask"}, tmp_path)

    assert candidate["kind"] == "command_prefix"
    assert session_rule_matches(candidate, "Bash", {"command": "pip install requests"}, tmp_path)
    assert not session_rule_matches(candidate, "Bash", {"command": "uv run pytest"}, tmp_path)


def test_write_new_file_matches_parent_directory(tmp_path: Path):
    candidate = build_match_candidate(
        "Write",
        {"path": "notes/today.md", "content": "hello"},
        tmp_path,
    )

    assert candidate["kind"] == "parent_dir"
    assert session_rule_matches(
        candidate,
        "Write",
        {"path": "notes/tomorrow.md", "content": "world"},
        tmp_path,
    )


def test_edit_matches_exact_file_path(tmp_path: Path):
    candidate = build_match_candidate(
        "Edit",
        {"path": "src/app.py", "old_text": "a", "new_text": "b"},
        tmp_path,
    )

    assert candidate["kind"] == "exact_file"
    assert session_rule_matches(
        candidate,
        "Edit",
        {"path": "src/app.py", "old_text": "x", "new_text": "y"},
        tmp_path,
    )
    assert not session_rule_matches(
        candidate,
        "Edit",
        {"path": "src/other.py", "old_text": "x", "new_text": "y"},
        tmp_path,
    )


def test_build_permission_request_uses_tool_specific_summary(tmp_path: Path):
    decision = PermissionDecision(
        action=PermissionAction.ASK,
        reason="exec: need_approval (command.need_approval: pip install *)",
    )

    request = build_permission_request(
        tool_name="Bash",
        tool_input={"command": "pip install flask"},
        tool_use_id="tool-1",
        decision=decision,
        workdir=tmp_path,
    )

    assert request.title == "Bash command"
    assert "pip install flask" in request.description
    assert request.match_candidate["kind"] == "command_prefix"
