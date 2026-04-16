import threading
import time
from unittest.mock import MagicMock

import pytest

from bourbon.config import Config
from bourbon.subagent.manager import SubagentManager
from bourbon.subagent.result import AgentToolResult
from bourbon.subagent.types import RunStatus, SubagentMode


class FakeSubagent:
    def __init__(self, response: str = "subagent result", *, delay: float = 0.0):
        self.response = response
        self.delay = delay
        self.prompts: list[str] = []
        self.token_usage = {
            "input_tokens": 400,
            "output_tokens": 600,
            "total_tokens": 1000,
        }

    def step(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.delay:
            time.sleep(self.delay)
        return self.response

    def get_token_usage(self) -> dict:
        return self.token_usage


def test_spawn_sync_returns_agent_tool_result(tmp_path):
    created_agents = []

    def agent_factory(run, agent_def):
        agent = FakeSubagent()
        created_agents.append((run, agent_def, agent))
        return agent

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=agent_factory,
    )

    result = manager.spawn(
        description="Do focused work",
        prompt="Do the thing",
        agent_type="coder",
    )

    assert isinstance(result, AgentToolResult)
    assert result.content == "subagent result"
    assert result.total_tokens == 1000
    assert result.total_tool_calls == 0
    run = manager.get_run(result.run_id)
    assert run.status == RunStatus.COMPLETED
    assert run.result == "subagent result"
    assert created_agents[0][2].prompts == ["Do the thing"]


def test_spawn_rejects_unknown_agent_type(tmp_path):
    manager = SubagentManager(config=Config(), workdir=tmp_path)

    with pytest.raises(ValueError, match="Unknown subagent type"):
        manager.spawn(
            description="Unknown",
            prompt="Do it",
            agent_type="missing",
        )


def test_spawn_background_returns_run_id_and_completes(tmp_path):
    release = threading.Event()

    def agent_factory(run, agent_def):
        class BlockingFakeSubagent(FakeSubagent):
            def step(self, prompt: str) -> str:
                release.wait(timeout=1)
                return super().step(prompt)

        return BlockingFakeSubagent(response="background result")

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=agent_factory,
    )

    run_id = manager.spawn(
        description="Background work",
        prompt="Run in background",
        run_in_background=True,
    )

    run = manager.get_run(run_id)
    assert run is not None
    assert run.is_async is True
    assert run.status in {RunStatus.PENDING, RunStatus.RUNNING}

    release.set()
    future = manager.executor.get_future(run_id)
    if future is not None:
        future.result(timeout=1)

    assert manager.get_run(run_id).status == RunStatus.COMPLETED
    assert manager.get_run_output(run_id) == "background result"
    manager.shutdown()


def test_wait_for_runs_blocks_until_background_run_completes(tmp_path):
    release = threading.Event()

    def agent_factory(run, agent_def):
        class BlockingFakeSubagent(FakeSubagent):
            def step(self, prompt: str) -> str:
                release.wait(timeout=1)
                return super().step(prompt)

        return BlockingFakeSubagent(response="joined background result")

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=agent_factory,
    )
    run_id = manager.spawn(
        description="Background join",
        prompt="Run in background",
        run_in_background=True,
    )

    def release_later():
        time.sleep(0.05)
        release.set()

    thread = threading.Thread(target=release_later)
    thread.start()
    output = manager.wait_for_runs([run_id], timeout=1)
    thread.join(timeout=1)

    assert f"Run {run_id} [completed] Background join" in output
    assert "joined background result" in output
    manager.shutdown()


def test_wait_for_runs_reports_timeout_for_running_background_run(tmp_path):
    release = threading.Event()

    def agent_factory(run, agent_def):
        class BlockingFakeSubagent(FakeSubagent):
            def step(self, prompt: str) -> str:
                release.wait(timeout=1)
                return super().step(prompt)

        return BlockingFakeSubagent(response="late background result")

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=agent_factory,
    )
    run_id = manager.spawn(
        description="Slow background",
        prompt="Run in background",
        run_in_background=True,
    )

    output = manager.wait_for_runs([run_id], timeout=0.01)

    assert f"Run {run_id} [running] Slow background" in output
    assert "Timed out waiting after 0.01s." in output

    release.set()
    manager.shutdown()


def test_failed_run_records_error(tmp_path):
    def agent_factory(run, agent_def):
        class FailingSubagent:
            def get_token_usage(self) -> dict:
                return {"total_tokens": 0}

            def step(self, prompt: str) -> str:
                raise RuntimeError("boom")

        return FailingSubagent()

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=agent_factory,
    )

    with pytest.raises(RuntimeError, match="boom"):
        manager.spawn(description="Fail", prompt="Explode")

    run = manager.list_runs()[0]
    assert run.status == RunStatus.FAILED
    assert run.error == "boom"
    assert manager.get_run_output(run.run_id) == "Error: boom"


def test_interrupted_sync_run_marks_run_killed_and_aborts_controller(tmp_path):
    def agent_factory(run, agent_def):
        class InterruptingSubagent:
            def step(self, prompt: str) -> str:
                raise KeyboardInterrupt

        return InterruptingSubagent()

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=agent_factory,
    )

    with pytest.raises(KeyboardInterrupt):
        manager.spawn(description="Interrupt", prompt="Stop")

    run = manager.list_runs()[0]
    assert run.status == RunStatus.KILLED
    assert run.abort_controller.is_aborted() is True
    assert manager.get_run_output(run.run_id) == f"Run {run.run_id} is killed."


def test_spawn_emits_debug_events(tmp_path, monkeypatch):
    events = []

    def fake_debug_log(event, **fields):
        events.append((event, fields))

    monkeypatch.setattr("bourbon.subagent.manager.debug_log", fake_debug_log)
    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=lambda run, agent_def: FakeSubagent(),
    )

    result = manager.spawn(
        description="Debug lifecycle",
        prompt="Do it",
        agent_type="explore",
    )

    event_names = [event for event, _fields in events]
    assert event_names == [
        "subagent.spawn.registered",
        "subagent.lifecycle.start",
        "subagent.lifecycle.agent_created",
        "subagent.lifecycle.step.complete",
        "subagent.lifecycle.complete",
    ]
    assert events[0][1]["run_id"] == result.run_id
    assert events[0][1]["agent_type"] == "explore"
    assert events[0][1]["max_turns"] == 30


def test_kill_run_marks_run_killed_and_aborts_controller(tmp_path):
    manager = SubagentManager(config=Config(), workdir=tmp_path)
    run_id = manager.spawn(
        description="Background",
        prompt="Wait",
        run_in_background=True,
        agent_factory=lambda run, agent_def: FakeSubagent(delay=0.2),
    )

    message = manager.kill_run(run_id)

    assert message == f"Stopped run: {run_id}"
    run = manager.get_run(run_id)
    assert run.status == RunStatus.KILLED
    assert run.abort_controller.is_aborted() is True
    manager.shutdown(wait=True)


def test_render_run_list(tmp_path):
    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=lambda run, agent_def: FakeSubagent(),
    )
    result = manager.spawn(description="List me", prompt="Do it")

    rendered = manager.render_run_list()

    assert result.run_id in rendered
    assert "[completed]" in rendered
    assert "List me" in rendered


def test_spawn_sets_subagent_mode_normal_for_sync(tmp_path):
    """Regular sync spawn should produce NORMAL mode."""
    received_modes = []

    def agent_factory(run, agent_def):
        received_modes.append(run.subagent_mode)
        return FakeSubagent()

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=agent_factory,
    )

    manager.spawn(description="test", prompt="do it", agent_type="default")

    assert received_modes == [SubagentMode.NORMAL]


def test_spawn_sets_subagent_mode_async_for_background(tmp_path):
    """Background spawn should produce ASYNC mode."""
    received_modes = []
    done = threading.Event()

    def agent_factory(run, agent_def):
        received_modes.append(run.subagent_mode)
        done.set()
        return FakeSubagent()

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        agent_factory=agent_factory,
    )

    manager.spawn(
        description="bg",
        prompt="do",
        agent_type="default",
        run_in_background=True,
    )
    done.wait(timeout=2)
    manager.shutdown()

    assert received_modes == [SubagentMode.ASYNC]


def test_spawn_teammate_sets_mode_and_task_list_id(tmp_path):
    """Teammate spawn should set TEAMMATE mode and parent task list id."""
    received = []

    def agent_factory(run, agent_def):
        received.append((run.subagent_mode, run.parent_task_list_id))
        return FakeSubagent()

    parent = MagicMock()
    parent.session.session_id = "parent-session-123"

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        parent_agent=parent,
        agent_factory=agent_factory,
    )

    manager.spawn(description="teammate", prompt="do", agent_type="teammate")

    assert received[0][0] == SubagentMode.TEAMMATE
    assert received[0][1] == "parent-session-123"


def test_configure_subagent_runtime_applies_to_factory_agent(tmp_path):
    """agent_factory branch must also receive subagent_mode and task_list_id_override."""
    created_agents = []

    class FakeAgentWithAttrs(FakeSubagent):
        def __init__(self):
            super().__init__()
            self.subagent_mode = None
            self.task_list_id_override = None

    def agent_factory(run, agent_def):
        agent = FakeAgentWithAttrs()
        created_agents.append(agent)
        return agent

    parent = MagicMock()
    parent.session.session_id = "parent-xyz"

    manager = SubagentManager(
        config=Config(),
        workdir=tmp_path,
        parent_agent=parent,
        agent_factory=agent_factory,
    )

    manager.spawn(description="tm", prompt="do", agent_type="teammate")
    agent = created_agents[0]

    assert agent.subagent_mode == SubagentMode.TEAMMATE
    assert agent.task_list_id_override == "parent-xyz"
