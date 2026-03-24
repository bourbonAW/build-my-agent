"""Tests for audit events and logging."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bourbon.audit import AuditLogger
from bourbon.audit.events import AuditEvent, EventType


def test_policy_decision_event_to_dict_flattens_extra():
    event = AuditEvent.policy_decision(
        tool_name="bash",
        tool_input_summary="rm -rf /",
        decision="deny",
        reason="dangerous command",
    )

    payload = event.to_dict()

    assert event.event_type == EventType.POLICY_DECISION
    assert payload["event_type"] == "POLICY_DECISION"
    assert payload["tool_name"] == "bash"
    assert payload["tool_input_summary"] == "rm -rf /"
    assert payload["decision"] == "deny"
    assert payload["reason"] == "dangerous command"
    assert "extra" not in payload


def test_sandbox_exec_event_classmethod_sets_fields():
    event = AuditEvent.sandbox_exec(
        tool_name="bash",
        tool_input_summary="echo hello",
        command="echo hello",
        exit_code=0,
    )

    payload = event.to_dict()

    assert event.event_type == EventType.SANDBOX_EXEC
    assert payload["event_type"] == "SANDBOX_EXEC"
    assert payload["command"] == "echo hello"
    assert payload["exit_code"] == 0


def test_tool_call_event_classmethod_sets_fields():
    event = AuditEvent.tool_call(
        tool_name="search",
        tool_input_summary="find main.py",
        arguments={"query": "main.py"},
    )

    payload = event.to_dict()

    assert event.event_type == EventType.TOOL_CALL
    assert payload["event_type"] == "TOOL_CALL"
    assert payload["arguments"] == {"query": "main.py"}


def test_sandbox_violation_event_classmethod_sets_fields():
    event = AuditEvent.sandbox_violation(
        tool_name="bash",
        tool_input_summary="cat /etc/passwd",
        violation="path outside workspace",
    )

    payload = event.to_dict()

    assert event.event_type == EventType.SANDBOX_VIOLATION
    assert payload["event_type"] == "SANDBOX_VIOLATION"
    assert payload["violation"] == "path outside workspace"


def test_logger_record_query_and_jsonl(tmp_path: Path):
    logger = AuditLogger(log_dir=tmp_path)
    first = AuditEvent.policy_decision(
        tool_name="bash",
        tool_input_summary="rm -rf /",
        decision="deny",
        reason="dangerous command",
    )
    second = AuditEvent.sandbox_exec(
        tool_name="bash",
        tool_input_summary="echo hello",
        command="echo hello",
        exit_code=0,
    )

    logger.record(first)
    logger.record(second)

    assert logger.query() == [first, second]
    assert logger.query(event_type=EventType.SANDBOX_EXEC) == [second]
    assert logger.summary() == {
        "total_events": 2,
        "policy_denied": 1,
        "policy_need_approval": 0,
        "sandbox_executions": 1,
        "violations": 0,
    }

    log_files = sorted(tmp_path.glob("session-*.jsonl"))
    assert len(log_files) == 1

    lines = log_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    first_payload = json.loads(lines[0])
    second_payload = json.loads(lines[1])

    assert first_payload["event_type"] == "POLICY_DECISION"
    assert first_payload["tool_name"] == "bash"
    assert second_payload["event_type"] == "SANDBOX_EXEC"
    assert second_payload["command"] == "echo hello"


def test_logger_records_timestamp_and_creates_log_dir(tmp_path: Path):
    log_dir = tmp_path / "audit"
    logger = AuditLogger(log_dir=log_dir)
    event = AuditEvent.tool_call(
        tool_name="search",
        tool_input_summary="find main.py",
        arguments={"query": "main.py"},
    )

    before = datetime.now(UTC) - timedelta(seconds=1)
    logger.record(event)
    after = datetime.now(UTC) + timedelta(seconds=1)

    assert log_dir.exists()
    assert len(logger.events) == 1
    assert before <= logger.events[0].timestamp <= after


def test_disabled_logger_does_nothing(tmp_path: Path):
    logger = AuditLogger(log_dir=tmp_path, enabled=False)
    event = AuditEvent.tool_call(
        tool_name="search",
        tool_input_summary="find main.py",
        arguments={"query": "main.py"},
    )

    logger.record(event)

    assert logger.events == []
    assert list(tmp_path.iterdir()) == []
    assert logger.query() == []
    assert logger.summary() == {
        "total_events": 0,
        "policy_denied": 0,
        "policy_need_approval": 0,
        "sandbox_executions": 0,
        "violations": 0,
    }
