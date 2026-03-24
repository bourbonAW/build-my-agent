"""Tests for AccessController integration."""

from pathlib import Path

from bourbon.access_control import AccessController
from bourbon.access_control.policy import PolicyAction


def make_controller(
    *,
    default_action: str = "allow",
    file_rules: dict | None = None,
) -> AccessController:
    return AccessController(
        config={
            "default_action": default_action,
            "file": file_rules
            or {
                "allow": ["{workdir}/**"],
                "deny": ["~/.ssh/**"],
                "mandatory_deny": ["~/.ssh/**"],
            },
            "command": {
                "deny_patterns": ["rm -rf /", "sudo *"],
                "need_approval_patterns": ["pip install *"],
            },
        },
        workdir=Path("/workspace"),
    )


def test_allow_safe_bash() -> None:
    decision = make_controller().evaluate("bash", {"command": "ls -la"})

    assert decision.action == PolicyAction.ALLOW


def test_deny_dangerous_bash() -> None:
    decision = make_controller().evaluate("bash", {"command": "rm -rf /"})

    assert decision.action == PolicyAction.DENY


def test_need_approval_pip_install() -> None:
    decision = make_controller().evaluate("bash", {"command": "pip install flask"})

    assert decision.action == PolicyAction.NEED_APPROVAL


def test_allow_read_file_in_workspace() -> None:
    decision = make_controller().evaluate("read_file", {"path": "/workspace/src/main.py"})

    assert decision.action == PolicyAction.ALLOW


def test_allow_rg_search_in_workspace_with_default_deny() -> None:
    decision = make_controller(default_action="deny").evaluate(
        "rg_search",
        {"pattern": "x", "path": "/workspace/src"},
    )

    assert decision.action == PolicyAction.ALLOW


def test_allow_ast_grep_search_in_workspace_with_default_deny() -> None:
    decision = make_controller(default_action="deny").evaluate(
        "ast_grep_search",
        {"pattern": "x", "path": "/workspace/src"},
    )

    assert decision.action == PolicyAction.ALLOW


def test_allow_rg_search_without_path_uses_workspace_default() -> None:
    decision = make_controller(default_action="deny").evaluate(
        "rg_search",
        {"pattern": "x"},
    )

    assert decision.action == PolicyAction.ALLOW


def test_deny_rg_search_in_restricted_path() -> None:
    decision = make_controller(
        file_rules={
            "allow": ["{workdir}/**"],
            "deny": ["{workdir}/private/**"],
            "mandatory_deny": [],
        }
    ).evaluate(
        "rg_search",
        {"pattern": "x", "path": "/workspace/private/secret.txt"},
    )

    assert decision.action == PolicyAction.DENY
    assert decision.reason == "file_read: deny (file.deny: {workdir}/private/**)"


def test_deny_ast_grep_search_in_restricted_path() -> None:
    decision = make_controller(
        file_rules={
            "allow": ["{workdir}/**"],
            "deny": ["{workdir}/private/**"],
            "mandatory_deny": [],
        }
    ).evaluate(
        "ast_grep_search",
        {"pattern": "x", "path": "/workspace/private/secret.py"},
    )

    assert decision.action == PolicyAction.DENY
    assert decision.reason == "file_read: deny (file.deny: {workdir}/private/**)"


def test_deny_rg_search_directory_root_in_restricted_path() -> None:
    decision = make_controller(
        file_rules={
            "allow": ["{workdir}/**"],
            "deny": ["{workdir}/private/**"],
            "mandatory_deny": [],
        }
    ).evaluate(
        "rg_search",
        {"pattern": "x", "path": "/workspace/private"},
    )

    assert decision.action == PolicyAction.DENY


def test_deny_rg_search_traversal_path() -> None:
    decision = make_controller(default_action="deny").evaluate(
        "rg_search",
        {"pattern": "x", "path": "../secret.txt"},
    )

    assert decision.action == PolicyAction.DENY


def test_allow_ast_grep_search_without_path_uses_workspace_default() -> None:
    decision = make_controller(default_action="deny").evaluate(
        "ast_grep_search",
        {"query": "x"},
    )

    assert decision.action == PolicyAction.ALLOW


def test_deny_read_ssh_key() -> None:
    decision = make_controller().evaluate("read_file", {"path": "~/.ssh/id_rsa"})

    assert decision.action == PolicyAction.DENY


def test_unknown_tool_uses_default_action() -> None:
    decision = make_controller().evaluate("some_mcp_tool", {"query": "hello"})

    assert decision.action == PolicyAction.ALLOW
