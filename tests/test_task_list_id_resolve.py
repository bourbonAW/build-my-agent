"""Tests for _resolve_task_list_id with task_list_id_override support."""

from pathlib import Path
from unittest.mock import MagicMock

from bourbon.tools import ToolContext


def resolve(agent=None, explicit_id=None):
    from bourbon.tools.task_tools import _resolve_task_list_id

    ctx = ToolContext(workdir=Path.cwd(), agent=agent)
    return _resolve_task_list_id(ctx, explicit_id)


def make_agent(*, override=None, session_id=None, default_list_id=None):
    agent = MagicMock()
    agent.task_list_id_override = override
    agent.session.session_id = session_id
    agent.config.tasks.default_list_id = default_list_id
    return agent


def test_explicit_id_wins_over_all():
    agent = make_agent(override="override-id", session_id="session-id")

    assert resolve(agent, explicit_id="explicit") == "explicit"


def test_override_wins_over_session_id():
    agent = make_agent(override="override-id", session_id="session-id")

    assert resolve(agent) == "override-id"


def test_session_id_wins_when_no_override():
    agent = make_agent(override=None, session_id="session-id")

    assert resolve(agent) == "session-id"


def test_config_default_used_when_no_override_or_session():
    agent = make_agent(
        override=None,
        session_id=None,
        default_list_id="config-default",
    )

    assert resolve(agent) == "config-default"


def test_returns_default_when_nothing_set():
    agent = make_agent(override=None, session_id=None)

    assert resolve(agent) == "default"


def test_no_agent_returns_default():
    assert resolve(agent=None) == "default"
