import threading
import time

import pytest

from bourbon.config import Config
from bourbon.subagent.manager import SubagentManager
from bourbon.subagent.result import AgentToolResult
from bourbon.subagent.types import RunStatus


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
