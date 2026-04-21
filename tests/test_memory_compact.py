from datetime import UTC, datetime
from pathlib import Path

from bourbon.memory.compact import extract_flush_candidates, write_daily_log


def test_extract_remember_keywords() -> None:
    messages = [
        {"role": "user", "content": "Please remember to always use WAL mode.", "uuid": "msg_1"},
        {"role": "assistant", "content": "Sure, I'll remember that.", "uuid": "msg_2"},
        {"role": "user", "content": "What's the weather?", "uuid": "msg_3"},
    ]

    candidates = extract_flush_candidates(messages, session_id="ses_1")
    assert len(candidates) >= 1
    assert any("WAL mode" in candidate.content for candidate in candidates)


def test_extract_error_tool_results() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "Running command...",
            "uuid": "msg_1",
            "tool_results": [
                {"tool_name": "bash", "output": "Permission denied: /etc/passwd", "is_error": True}
            ],
        },
    ]

    candidates = extract_flush_candidates(messages, session_id="ses_1")
    assert len(candidates) >= 1
    assert any("Permission denied" in candidate.content for candidate in candidates)


def test_extract_no_candidates_from_normal_chat() -> None:
    messages = [
        {"role": "user", "content": "Hello, how are you?", "uuid": "msg_1"},
        {"role": "assistant", "content": "I'm doing well!", "uuid": "msg_2"},
    ]

    candidates = extract_flush_candidates(messages, session_id="ses_1")
    assert len(candidates) == 0


def test_write_daily_log_creates_file(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    write_daily_log(
        log_dir=log_dir,
        session_start=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
        session_id="ses_test123",
        entries=["Discussed WAL mode decision", "Fixed bug in sandbox"],
    )

    expected_file = log_dir / "2026" / "04" / "2026-04-20.md"
    assert expected_file.exists()
    content = expected_file.read_text()
    assert "WAL mode" in content
    assert "ses_test123" in content


def test_write_daily_log_appends_to_existing(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    dt = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)

    write_daily_log(log_dir=log_dir, session_start=dt, session_id="ses_1", entries=["First entry"])
    write_daily_log(log_dir=log_dir, session_start=dt, session_id="ses_2", entries=["Second entry"])

    content = (log_dir / "2026" / "04" / "2026-04-20.md").read_text()
    assert "First entry" in content
    assert "Second entry" in content


def test_write_daily_log_uses_session_start_date(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    session_start = datetime(2026, 4, 20, 23, 50, tzinfo=UTC)

    write_daily_log(
        log_dir=log_dir,
        session_start=session_start,
        session_id="ses_cross",
        entries=["Late night work"],
    )

    assert (log_dir / "2026" / "04" / "2026-04-20.md").exists()
    assert not (log_dir / "2026" / "04" / "2026-04-21.md").exists()
