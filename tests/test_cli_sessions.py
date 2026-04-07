"""Tests for CLI and REPL session resume plumbing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4


def test_repl_passes_session_options_to_agent(monkeypatch, tmp_path: Path):
    """REPL should forward session resume options to Agent."""
    from bourbon.config import Config
    from bourbon.repl import REPL

    mock_agent_cls = MagicMock()
    mock_agent_cls.return_value = MagicMock()

    monkeypatch.setattr("bourbon.repl.Agent", mock_agent_cls)
    monkeypatch.setattr("bourbon.repl.PromptSession", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr("bourbon.repl.FileHistory", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr("bourbon.repl.Style.from_dict", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr("bourbon.repl.REPL._init_mcp", lambda self: None)

    session_id = uuid4()
    repl = REPL(Config(), workdir=tmp_path, session_id=session_id)

    assert repl is not None
    mock_agent_cls.assert_called_once()
    _, kwargs = mock_agent_cls.call_args
    assert kwargs["workdir"] == tmp_path
    assert kwargs["session_id"] == session_id
    assert kwargs["resume_last"] is False


def test_main_passes_resume_last_to_repl(monkeypatch):
    """CLI should expose resume-last for session recovery."""
    from bourbon.cli import main

    fake_config = MagicMock()
    repl_instance = MagicMock()
    repl_cls = MagicMock(return_value=repl_instance)
    manager_instance = MagicMock()
    manager_instance.load_config.return_value = fake_config

    monkeypatch.setattr("bourbon.cli.ConfigManager", MagicMock(return_value=manager_instance))
    monkeypatch.setattr("bourbon.cli.REPL", repl_cls)
    monkeypatch.setattr("sys.argv", ["bourbon", "--resume-last"])

    result = main()

    assert result == 0
    repl_cls.assert_called_once_with(
        fake_config,
        workdir=None,
        session_id=None,
        resume_last=True,
    )
    repl_instance.run.assert_called_once_with()


def test_main_passes_session_id_to_repl(monkeypatch):
    """CLI should expose explicit session-id resume."""
    from bourbon.cli import main

    fake_config = MagicMock()
    repl_instance = MagicMock()
    repl_cls = MagicMock(return_value=repl_instance)
    manager_instance = MagicMock()
    manager_instance.load_config.return_value = fake_config
    session_id = uuid4()

    monkeypatch.setattr("bourbon.cli.ConfigManager", MagicMock(return_value=manager_instance))
    monkeypatch.setattr("bourbon.cli.REPL", repl_cls)
    monkeypatch.setattr("sys.argv", ["bourbon", "--session-id", str(session_id)])

    result = main()

    assert result == 0
    repl_cls.assert_called_once_with(
        fake_config,
        workdir=None,
        session_id=session_id,
        resume_last=False,
    )
    repl_instance.run.assert_called_once_with()
