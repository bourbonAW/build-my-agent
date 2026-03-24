"""Audit logging for sandbox and policy activity."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from bourbon.audit.events import AuditEvent, EventType

__all__ = ["AuditEvent", "AuditLogger", "EventType"]


class AuditLogger:
    """Minimal JSONL audit logger."""

    def __init__(self, *, log_dir: Path, enabled: bool = True) -> None:
        self.enabled = enabled
        self.log_dir = log_dir
        self.events: list[AuditEvent] = []
        self.log_file: Path | None = None
        if not self.enabled:
            return

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"session-{uuid4().hex}.jsonl"
        self.log_file.touch(exist_ok=False)

    def record(self, event: AuditEvent) -> None:
        if not self.enabled:
            return

        payload = json.dumps(event.to_dict(), sort_keys=True)
        assert self.log_file is not None
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        self.events.append(event)

    def query(self, **filters: object) -> list[AuditEvent]:
        if not self.enabled:
            return []

        results = list(self.events)
        for key, value in filters.items():
            results = [event for event in results if self._matches(event, key, value)]
        return results

    def summary(self) -> dict[str, int]:
        if not self.enabled:
            return {
                "total_events": 0,
                "policy_denied": 0,
                "policy_need_approval": 0,
                "sandbox_executions": 0,
                "violations": 0,
            }

        policy_denied = 0
        policy_need_approval = 0
        sandbox_executions = 0
        violations = 0
        for event in self.events:
            if event.event_type == EventType.POLICY_DECISION:
                decision = event.extra.get("decision")
                if decision == "deny":
                    policy_denied += 1
                elif decision == "need_approval":
                    policy_need_approval += 1
            elif event.event_type == EventType.SANDBOX_EXEC:
                sandbox_executions += 1
            elif event.event_type == EventType.SANDBOX_VIOLATION:
                violations += 1

        return {
            "total_events": len(self.events),
            "policy_denied": policy_denied,
            "policy_need_approval": policy_need_approval,
            "sandbox_executions": sandbox_executions,
            "violations": violations,
        }

    @staticmethod
    def _matches(event: AuditEvent, key: str, value: object) -> bool:
        if key == "event_type":
            if isinstance(value, EventType):
                return event.event_type == value
            return event.event_type.value == value
        if key == "timestamp":
            if isinstance(value, datetime):
                return event.timestamp == value
            return event.timestamp.isoformat() == value
        if key == "extra":
            return event.extra == value
        if hasattr(event, key):
            return getattr(event, key) == value
        return event.extra.get(key) == value
