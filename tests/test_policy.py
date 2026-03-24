"""Tests for policy evaluation."""

from pathlib import Path

from bourbon.access_control.capabilities import CapabilityType, InferredContext
from bourbon.access_control.policy import (
    CapabilityDecision,
    PolicyAction,
    PolicyDecision,
    PolicyEngine,
)


def make_engine(
    *,
    default_action: PolicyAction = PolicyAction.ALLOW,
    file_rules: dict | None = None,
    command_rules: dict | None = None,
) -> PolicyEngine:
    return PolicyEngine(
        default_action=default_action,
        file_rules=file_rules or {},
        command_rules=command_rules or {},
        workdir=Path("/workspace"),
    )


def test_file_allow_in_workspace():
    engine = make_engine(
        default_action=PolicyAction.DENY,
        file_rules={"allow": ["{workdir}/**"]},
    )

    decision = engine.evaluate(
        "read_file",
        InferredContext(
            capabilities=[CapabilityType.FILE_READ],
            file_paths=["/workspace/src/main.py"],
        ),
    )

    assert decision.action == PolicyAction.ALLOW
    assert decision.denied_capability is None
    assert decision.decisions[0].matched_rule == "file.allow: {workdir}/**"


def test_relative_file_path_is_resolved_against_workdir():
    engine = make_engine(
        default_action=PolicyAction.DENY,
        file_rules={"allow": ["{workdir}/**"]},
    )

    decision = engine.evaluate(
        "read_file",
        InferredContext(
            capabilities=[CapabilityType.FILE_READ],
            file_paths=["src/main.py"],
        ),
    )

    assert decision.action == PolicyAction.ALLOW
    assert decision.denied_capability is None


def test_traversal_relative_file_path_is_denied():
    engine = make_engine(
        default_action=PolicyAction.DENY,
        file_rules={"allow": ["{workdir}/**"]},
    )

    decision = engine.evaluate(
        "read_file",
        InferredContext(
            capabilities=[CapabilityType.FILE_READ],
            file_paths=["../secret.txt"],
        ),
    )

    assert decision.action == PolicyAction.DENY
    assert decision.denied_capability == CapabilityType.FILE_READ


def test_traversal_absolute_file_path_is_denied():
    engine = make_engine(
        default_action=PolicyAction.DENY,
        file_rules={"allow": ["{workdir}/**"]},
    )

    decision = engine.evaluate(
        "read_file",
        InferredContext(
            capabilities=[CapabilityType.FILE_READ],
            file_paths=["/workspace/../secret.txt"],
        ),
    )

    assert decision.action == PolicyAction.DENY
    assert decision.denied_capability == CapabilityType.FILE_READ


def test_file_deny_outside_workspace():
    engine = make_engine(
        default_action=PolicyAction.DENY,
        file_rules={"allow": ["{workdir}/**"]},
    )

    decision = engine.evaluate(
        "read_file",
        InferredContext(
            capabilities=[CapabilityType.FILE_READ],
            file_paths=["/etc/passwd"],
        ),
    )

    assert decision.action == PolicyAction.DENY
    assert decision.denied_capability == CapabilityType.FILE_READ
    assert decision.reason == "file_read: deny (default)"


def test_mandatory_deny_overrides_allow():
    engine = make_engine(
        file_rules={
            "allow": ["**"],
            "deny": [],
            "mandatory_deny": ["~/.ssh/**"],
        },
    )

    decision = engine.evaluate(
        "read_file",
        InferredContext(
            capabilities=[CapabilityType.FILE_READ],
            file_paths=[str(Path.home() / ".ssh/id_rsa")],
        ),
    )

    assert decision.action == PolicyAction.DENY
    assert decision.reason == "file_read: deny (file.mandatory_deny: ~/.ssh/**)"


def test_mandatory_deny_normalizes_home_pattern_with_symlink_prefix(monkeypatch, tmp_path: Path):
    home_path = str(tmp_path)
    if home_path.startswith("/private/var/"):
        monkeypatch.setenv("HOME", home_path.removeprefix("/private"))
    else:
        monkeypatch.setenv("HOME", home_path)

    engine = make_engine(
        file_rules={
            "allow": ["**"],
            "deny": [],
            "mandatory_deny": ["~/.ssh/**"],
        },
    )

    decision = engine.evaluate(
        "read_file",
        InferredContext(
            capabilities=[CapabilityType.FILE_READ],
            file_paths=[str(tmp_path / ".ssh/id_rsa")],
        ),
    )

    assert decision.action == PolicyAction.DENY


def test_deny_git_hooks():
    engine = make_engine(
        file_rules={"deny": ["**/.git/hooks/**"]},
    )

    decision = engine.evaluate(
        "write_file",
        InferredContext(
            capabilities=[CapabilityType.FILE_WRITE],
            file_paths=["/workspace/.git/hooks/pre-commit"],
        ),
    )

    assert decision.action == PolicyAction.DENY
    assert decision.reason == "file_write: deny (file.deny: **/.git/hooks/**)"


def test_dangerous_command_deny():
    engine = make_engine(
        command_rules={"deny_patterns": ["rm -rf /"]},
    )

    decision = engine.evaluate_command(
        "rm -rf /",
        InferredContext(capabilities=[CapabilityType.EXEC]),
    )

    assert decision.action == PolicyAction.DENY
    assert decision.denied_capability == CapabilityType.EXEC


def test_pip_install_need_approval():
    engine = make_engine(
        command_rules={"need_approval_patterns": ["pip install *"]},
    )

    decision = engine.evaluate_command(
        "pip install flask",
        InferredContext(capabilities=[CapabilityType.EXEC, CapabilityType.NET]),
    )

    assert decision.action == PolicyAction.NEED_APPROVAL
    assert decision.reason == "exec: need_approval (command.need_approval: pip install *)"
    assert [d.capability for d in decision.decisions] == [
        CapabilityType.EXEC,
        CapabilityType.NET,
    ]
    assert decision.decisions[1].matched_rule == "net deferred to sandbox"


def test_safe_command_allow():
    engine = make_engine()

    decision = engine.evaluate_command(
        "echo hello",
        InferredContext(capabilities=[CapabilityType.EXEC]),
    )

    assert decision.action == PolicyAction.ALLOW
    assert decision.reason == "all capabilities allowed"


def test_sudo_wildcard_deny():
    engine = make_engine(
        command_rules={"deny_patterns": ["sudo *"]},
    )

    decision = engine.evaluate_command(
        "sudo rm -rf /",
        InferredContext(capabilities=[CapabilityType.EXEC]),
    )

    assert decision.action == PolicyAction.DENY
    assert decision.reason == "exec: deny (command.deny: sudo *)"


def test_command_substring_match_without_wildcard():
    engine = make_engine(
        command_rules={"deny_patterns": ["git hook"]},
    )

    decision = engine.evaluate_command(
        "git hook install",
        InferredContext(capabilities=[CapabilityType.EXEC]),
    )

    assert decision.action == PolicyAction.DENY
    assert decision.reason == "exec: deny (command.deny: git hook)"


def test_merge_semantics_deny_beats_need_approval_beats_allow():
    merged = PolicyDecision.merge(
        [
            CapabilityDecision(CapabilityType.EXEC, PolicyAction.ALLOW, None),
            CapabilityDecision(CapabilityType.NET, PolicyAction.NEED_APPROVAL, "net rule"),
            CapabilityDecision(CapabilityType.FILE_READ, PolicyAction.DENY, "file rule"),
        ]
    )

    assert merged.action == PolicyAction.DENY
    assert merged.reason == "net: need_approval (net rule); file_read: deny (file rule)"
    assert merged.denied_capability == CapabilityType.FILE_READ


def test_no_decisions_defaults_to_exec():
    engine = make_engine(default_action=PolicyAction.ALLOW)

    decision = engine.evaluate("some_tool", InferredContext())

    assert decision.action == PolicyAction.ALLOW
    assert decision.decisions == [
        CapabilityDecision(CapabilityType.EXEC, PolicyAction.ALLOW, "default")
    ]
