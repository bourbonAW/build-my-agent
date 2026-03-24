"""Policy evaluation for Bourbon access control."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path

from bourbon.access_control.capabilities import CapabilityType, InferredContext


class PolicyAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    NEED_APPROVAL = "need_approval"


@dataclass
class CapabilityDecision:
    capability: CapabilityType
    action: PolicyAction
    matched_rule: str | None


@dataclass
class PolicyDecision:
    action: PolicyAction
    reason: str
    decisions: list[CapabilityDecision] = field(default_factory=list)

    @property
    def denied_capability(self) -> CapabilityType | None:
        for decision in self.decisions:
            if decision.action == PolicyAction.DENY:
                return decision.capability
        return None

    @classmethod
    def merge(cls, decisions: list[CapabilityDecision]) -> PolicyDecision:
        if not decisions:
            return cls(action=PolicyAction.ALLOW, reason="no capabilities to check")

        priority = {
            PolicyAction.DENY: 2,
            PolicyAction.NEED_APPROVAL: 1,
            PolicyAction.ALLOW: 0,
        }
        strictest = max(decisions, key=lambda decision: priority[decision.action])

        reason_parts = [
            f"{decision.capability.value}: {decision.action.value} ({decision.matched_rule})"
            for decision in decisions
            if decision.action != PolicyAction.ALLOW
        ]
        reason = "; ".join(reason_parts) if reason_parts else "all capabilities allowed"
        return cls(action=strictest.action, reason=reason, decisions=decisions)


class PolicyEngine:
    def __init__(
        self,
        default_action: PolicyAction,
        file_rules: dict,
        command_rules: dict,
        workdir: Path,
    ) -> None:
        self.default_action = default_action
        self.file_allow = list(file_rules.get("allow", []))
        self.file_deny = list(file_rules.get("deny", []))
        self.file_mandatory_deny = list(file_rules.get("mandatory_deny", []))
        self.command_deny = list(command_rules.get("deny_patterns", []))
        self.command_need_approval = list(command_rules.get("need_approval_patterns", []))
        self.workdir = workdir

    def evaluate(self, tool_name: str, context: InferredContext) -> PolicyDecision:
        decisions: list[CapabilityDecision] = []

        for capability in context.capabilities:
            if capability in (CapabilityType.FILE_READ, CapabilityType.FILE_WRITE):
                if context.file_paths:
                    for path in context.file_paths:
                        decisions.append(self._check_file_path(path, capability))
                else:
                    decisions.append(CapabilityDecision(capability, self.default_action, "default"))
            else:
                decisions.append(CapabilityDecision(capability, self.default_action, "default"))

        if not decisions:
            decisions.append(CapabilityDecision(CapabilityType.EXEC, self.default_action, "default"))

        return PolicyDecision.merge(decisions)

    def evaluate_command(self, command: str, context: InferredContext) -> PolicyDecision:
        decisions: list[CapabilityDecision] = []

        for pattern in self.command_deny:
            if self._command_matches(command, pattern):
                decisions.append(
                    CapabilityDecision(
                        CapabilityType.EXEC,
                        PolicyAction.DENY,
                        f"command.deny: {pattern}",
                    )
                )
                return PolicyDecision.merge(decisions)

        for pattern in self.command_need_approval:
            if self._command_matches(command, pattern):
                decisions.append(
                    CapabilityDecision(
                        CapabilityType.EXEC,
                        PolicyAction.NEED_APPROVAL,
                        f"command.need_approval: {pattern}",
                    )
                )
                break
        else:
            decisions.append(CapabilityDecision(CapabilityType.EXEC, PolicyAction.ALLOW, None))

        for capability in context.capabilities:
            if capability in (CapabilityType.FILE_READ, CapabilityType.FILE_WRITE):
                if context.file_paths:
                    for path in context.file_paths:
                        decisions.append(self._check_file_path(path, capability))
                else:
                    decisions.append(CapabilityDecision(capability, self.default_action, "default"))
            elif capability == CapabilityType.NET:
                decisions.append(
                    CapabilityDecision(capability, PolicyAction.ALLOW, "net deferred to sandbox")
                )
            elif capability != CapabilityType.EXEC:
                decisions.append(CapabilityDecision(capability, self.default_action, "default"))

        return PolicyDecision.merge(decisions)

    def _resolve_pattern(self, pattern: str) -> str:
        return str(Path(pattern.replace("{workdir}", str(self.workdir))).expanduser())

    def _check_file_path(self, path: str, capability: CapabilityType) -> CapabilityDecision:
        resolved_path = str(Path(path).expanduser())

        for pattern in self.file_mandatory_deny:
            if fnmatch(resolved_path, self._resolve_pattern(pattern)):
                return CapabilityDecision(capability, PolicyAction.DENY, f"file.mandatory_deny: {pattern}")

        for pattern in self.file_deny:
            if fnmatch(resolved_path, self._resolve_pattern(pattern)):
                return CapabilityDecision(capability, PolicyAction.DENY, f"file.deny: {pattern}")

        for pattern in self.file_allow:
            if fnmatch(resolved_path, self._resolve_pattern(pattern)):
                return CapabilityDecision(capability, PolicyAction.ALLOW, f"file.allow: {pattern}")

        return CapabilityDecision(capability, self.default_action, "default")

    @staticmethod
    def _command_matches(command: str, pattern: str) -> bool:
        if "*" in pattern:
            return fnmatch(command, pattern)
        return pattern in command
