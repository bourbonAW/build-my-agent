"""Permission runtime primitives used by the confirmation flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PermissionAction(StrEnum):
    """Normalized permission decision."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionChoice(StrEnum):
    """Choices exposed to the user for a pending permission request."""

    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    REJECT = "reject"


@dataclass(frozen=True)
class PermissionDecision:
    """Result of permission evaluation before user confirmation."""

    action: PermissionAction
    reason: str
    title: str = ""
    description: str = ""
    match_candidate: dict[str, Any] | None = None


def _default_permission_choices() -> tuple[PermissionChoice, PermissionChoice, PermissionChoice]:
    return (
        PermissionChoice.ALLOW_ONCE,
        PermissionChoice.ALLOW_SESSION,
        PermissionChoice.REJECT,
    )


@dataclass(frozen=True)
class PermissionRequest:
    """A single pending permission request waiting for user input."""

    request_id: str
    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any]
    title: str
    description: str
    reason: str
    match_candidate: dict[str, Any] | None = None
    options: tuple[PermissionChoice, PermissionChoice, PermissionChoice] = field(
        default_factory=_default_permission_choices
    )


@dataclass
class SuspendedToolRound:
    """A paused tool round that can resume after a permission decision."""

    source_assistant_uuid: Any
    tool_use_blocks: list[dict[str, Any]]
    completed_results: list[dict[str, Any]]
    next_tool_index: int
    active_request: PermissionRequest


class SessionPermissionStore:
    """In-memory permission rule store scoped to the running process."""

    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = []

    def add(self, candidate: dict[str, Any]) -> None:
        self._rules.append(candidate.copy())

    def has_match(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        _ = tool_input
        return any(rule.get("tool_name") == tool_name for rule in self._rules)
