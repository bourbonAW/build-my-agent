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
