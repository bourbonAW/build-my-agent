from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bourbon.config import Config


def _make_config(tmp_path: Path, *, enabled: bool) -> Config:
    return Config.from_dict(
        {
            "memory": {
                "enabled": enabled,
                "storage_dir": str(tmp_path / "memory_store"),
            },
            "llm": {
                "default_provider": "anthropic",
                "anthropic": {"api_key": "test-key"},
            },
        }
    )


def test_agent_initializes_memory_manager(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=True)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    assert agent._memory_manager is not None


def test_agent_no_memory_when_disabled(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=False)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    assert agent._memory_manager is None


def test_agent_prompt_context_has_memory_manager(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=True)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    assert agent._prompt_ctx.memory_manager is not None


def test_make_tool_context_includes_memory_fields(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=True)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    ctx = agent._make_tool_context()
    assert ctx.memory_manager is agent._memory_manager
    assert ctx.memory_actor is not None
    assert ctx.memory_actor.kind == "agent"


def test_step_impl_flushes_before_compact(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=True)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    agent._memory_manager = MagicMock()
    agent._prompt_ctx.memory_manager = agent._memory_manager

    with (
        patch.object(agent._prompt_builder, "build", new=AsyncMock(return_value="system")),
        patch.object(
            agent._context_injector,
            "inject",
            new=AsyncMock(return_value="remember this"),
        ),
        patch.object(agent.session.context_manager, "microcompact"),
        patch.object(agent.session.context_manager, "should_compact", return_value=True),
        patch.object(agent, "_compactable_messages_for_flush", return_value=[{"role": "user"}]),
        patch.object(agent.session, "maybe_compact", return_value=None),
        patch.object(agent, "_run_conversation_loop", return_value="ok"),
    ):
        result = agent._step_impl("remember this")

    assert result == "ok"
    agent._memory_manager.flush_before_compact.assert_called_once_with(
        [{"role": "user"}],
        session_id=str(agent.session.session_id),
    )


def test_step_stream_impl_flushes_before_compact(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=True)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    agent._memory_manager = MagicMock()
    agent._prompt_ctx.memory_manager = agent._memory_manager

    with (
        patch.object(agent._prompt_builder, "build", new=AsyncMock(return_value="system")),
        patch.object(
            agent._context_injector,
            "inject",
            new=AsyncMock(return_value="remember this"),
        ),
        patch.object(agent.session.context_manager, "microcompact"),
        patch.object(agent.session.context_manager, "should_compact", return_value=True),
        patch.object(agent, "_compactable_messages_for_flush", return_value=[{"role": "user"}]),
        patch.object(agent.session, "maybe_compact", return_value=None),
        patch.object(agent, "_run_conversation_loop_stream", return_value="ok"),
    ):
        result = agent._step_stream_impl("remember this", lambda _chunk: None)

    assert result == "ok"
    agent._memory_manager.flush_before_compact.assert_called_once_with(
        [{"role": "user"}],
        session_id=str(agent.session.session_id),
    )
