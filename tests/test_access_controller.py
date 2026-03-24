"""Tests for AccessController integration."""

from pathlib import Path

from bourbon.access_control import AccessController
from bourbon.access_control.policy import PolicyAction


def make_controller() -> AccessController:
    return AccessController(
        config={
            "default_action": "allow",
            "file": {
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


def test_deny_read_ssh_key() -> None:
    decision = make_controller().evaluate("read_file", {"path": "~/.ssh/id_rsa"})

    assert decision.action == PolicyAction.DENY


def test_unknown_tool_uses_default_action() -> None:
    decision = make_controller().evaluate("some_mcp_tool", {"query": "hello"})

    assert decision.action == PolicyAction.ALLOW
