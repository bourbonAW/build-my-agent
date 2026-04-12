import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bourbon.agent import Agent
from bourbon.config import Config
from bourbon.repl import REPL
from bourbon.tools import ToolContext, definitions, get_registry


class FakeSubagent:
    def __init__(self, response: str = "integration result", *, release=None):
        self.response = response
        self.release = release
        self.token_usage = {
            "input_tokens": 100,
            "output_tokens": 200,
            "total_tokens": 300,
        }

    def step(self, prompt: str) -> str:
        if self.release is not None:
            self.release.wait(timeout=1)
        return self.response

    def get_token_usage(self) -> dict:
        return self.token_usage


def _make_agent(tmp_path: Path) -> Agent:
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        return Agent(config=Config(), workdir=tmp_path)


def test_agent_tool_sync_integration_uses_parent_subagent_manager(tmp_path):
    definitions()
    agent = _make_agent(tmp_path)
    agent.subagent_manager.agent_factory = lambda run, agent_def: FakeSubagent()
    ctx = ToolContext(workdir=tmp_path, agent=agent)

    output = get_registry().call(
        "Agent",
        {
            "description": "Integration sync",
            "prompt": "Do focused work",
            "subagent_type": "coder",
        },
        ctx,
    )

    assert "Subagent completed" in output
    assert "integration result" in output
    runs = agent.subagent_manager.list_runs()
    assert len(runs) == 1
    assert runs[0].description == "Integration sync"
    assert runs[0].result == "integration result"


def test_agent_tool_background_integration_can_read_output(tmp_path):
    definitions()
    release = threading.Event()
    agent = _make_agent(tmp_path)
    agent.subagent_manager.agent_factory = lambda run, agent_def: FakeSubagent(
        response="background integration result",
        release=release,
    )
    ctx = ToolContext(workdir=tmp_path, agent=agent)

    output = get_registry().call(
        "Agent",
        {
            "description": "Integration background",
            "prompt": "Do focused work",
            "run_in_background": True,
        },
        ctx,
    )
    run_id = output.splitlines()[0].removeprefix("Started background run: ")

    assert f"/run-show {run_id}" in output
    assert agent.subagent_manager.get_run(run_id).is_async is True

    release.set()
    future = agent.subagent_manager.executor.get_future(run_id)
    if future is not None:
        future.result(timeout=1)

    assert agent.subagent_manager.get_run_output(run_id) == "background integration result"
    agent.subagent_manager.shutdown()


def test_repl_runtime_commands_use_agent_subagent_manager(tmp_path):
    repl = object.__new__(REPL)
    repl.console = MagicMock()
    repl.agent = SimpleNamespace(
        subagent_manager=SimpleNamespace(
            render_run_list=MagicMock(return_value="run-1 [completed] Done"),
            get_run_output=MagicMock(return_value="output"),
            stop_run=MagicMock(return_value="Stopped run: run-1"),
        )
    )

    repl._handle_command("/runs")
    repl._handle_command("/run-show run-1")
    repl._handle_command("/run-stop run-1")

    repl.agent.subagent_manager.render_run_list.assert_called_once_with()
    repl.agent.subagent_manager.get_run_output.assert_called_once_with("run-1")
    repl.agent.subagent_manager.stop_run.assert_called_once_with("run-1")
