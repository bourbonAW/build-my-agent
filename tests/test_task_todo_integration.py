"""Integration coverage for TodoWrite, Task V2, and boundary docs."""

import json
from pathlib import Path
from types import SimpleNamespace

from bourbon.config import Config
from bourbon.todos import TodoManager
from bourbon.tools import ToolContext, definitions, get_registry

ROOT = Path(__file__).resolve().parents[1]
SUBAGENT_DESIGN = (
    ROOT / "docs" / "superpowers" / "specs" / "2026-04-09-bourbon-subagent-design.md"
)
SUBAGENT_PLAN = (
    ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-04-09-bourbon-subagent-implementation.md"
)
TASK_V2_GUIDE = ROOT / "docs" / "superpowers" / "guides" / "task-v2-usage.md"
SUBAGENT_GUIDE = ROOT / "docs" / "superpowers" / "guides" / "subagent-usage.md"


class RunManagerTripwire:
    """Runtime-manager-like surface that fails if workflow tools touch it."""

    def __init__(self):
        self._runs = {
            "run-1": {
                "status": "running",
                "description": "Background runtime job",
            }
        }
        self.access_log: list[tuple[str, str | None]] = []

    @property
    def runs(self) -> dict[str, dict[str, str]]:
        self.access_log.append(("runs", None))
        return self._runs

    def list_runs(self) -> list[dict[str, str]]:
        self.access_log.append(("list_runs", None))
        raise AssertionError("Workflow task tools must not query runtime runs")

    def get_run_output(self, run_id: str) -> str:
        self.access_log.append(("get_run_output", run_id))
        raise AssertionError("Workflow task tools must not read runtime output")

    def stop_run(self, run_id: str) -> str:
        self.access_log.append(("stop_run", run_id))
        raise AssertionError("Workflow task tools must not stop runtime runs")

    def snapshot(self) -> dict[str, dict[str, str]]:
        return {
            run_id: dict(run_state) for run_id, run_state in self._runs.items()
        }


def _make_agent(storage_dir: Path, *, session_id: str = "session-123") -> SimpleNamespace:
    config = Config()
    config.tasks.storage_dir = str(storage_dir)
    return SimpleNamespace(
        config=config,
        session=SimpleNamespace(session_id=session_id),
        todos=TodoManager(),
        subagent_manager=RunManagerTripwire(),
    )


def test_todo_write_is_ephemeral_while_task_create_persists_across_agents(tmp_path):
    definitions()
    registry = get_registry()
    task_list_id = "workflow-alpha"

    agent_a = _make_agent(tmp_path, session_id="session-a")
    ctx_a = ToolContext(workdir=tmp_path, agent=agent_a)

    agent_a.todos.update([{"content": "Ephemeral checklist", "status": "pending"}])
    created = json.loads(
        registry.call(
            "TaskCreate",
            {
                "taskListId": task_list_id,
                "subject": "Persistent workflow task",
                "description": "Survives a fresh agent instance",
            },
            ctx_a,
        )
    )

    agent_b = _make_agent(tmp_path, session_id="session-b")
    ctx_b = ToolContext(workdir=tmp_path, agent=agent_b)
    listed = json.loads(registry.call("TaskList", {"taskListId": task_list_id}, ctx_b))
    agent_c = _make_agent(tmp_path, session_id="session-other")
    ctx_c = ToolContext(workdir=tmp_path, agent=agent_c)
    other_list = json.loads(
        registry.call("TaskList", {"taskListId": "workflow-beta"}, ctx_c)
    )

    assert listed == [created]
    assert other_list == []
    assert agent_a.todos.to_list() == [
        {"content": "Ephemeral checklist", "status": "pending", "activeForm": ""}
    ]
    assert agent_b.todos.to_list() == []


def test_completed_workflow_tasks_do_not_clear_open_todos_or_runtime_jobs(tmp_path):
    definitions()
    registry = get_registry()
    agent = _make_agent(tmp_path, session_id="session-separation")
    ctx = ToolContext(workdir=tmp_path, agent=agent)

    agent.todos.update([
        {
            "content": "Keep runtime checklist state",
            "status": "in_progress",
            "activeForm": "Keeping runtime checklist state",
        }
    ])
    before = agent.todos.to_list()
    before_runtime_runs = agent.subagent_manager.snapshot()
    created = json.loads(
        registry.call(
            "TaskCreate",
            {
                "subject": "Workflow task",
                "description": "Can finish without touching todos",
            },
            ctx,
        )
    )

    updated = json.loads(
        registry.call(
            "TaskUpdate",
            {
                "taskId": created["id"],
                "status": "completed",
            },
            ctx,
        )
    )

    assert updated["status"] == "completed"
    assert agent.todos.to_list() == before
    assert agent.subagent_manager.snapshot() == before_runtime_runs
    assert agent.subagent_manager.access_log == []
    assert agent.todos.has_open_items() is True


def test_task_boundary_docs_use_one_reserved_runtime_command_set():
    texts = {
        "subagent design": SUBAGENT_DESIGN.read_text(encoding="utf-8"),
        "subagent plan": SUBAGENT_PLAN.read_text(encoding="utf-8"),
        "task usage guide": TASK_V2_GUIDE.read_text(encoding="utf-8"),
        "subagent usage guide": SUBAGENT_GUIDE.read_text(encoding="utf-8"),
    }

    for name, text in texts.items():
        assert "/runs" in text, name
        assert "/run-show" in text, name
        assert "/run-stop" in text, name
        assert "/run-status" not in text, name
        assert "equivalent names" not in text, name

    guide_text = texts["task usage guide"]
    assert "TodoWrite" in guide_text
    assert "legacy in-memory checklist" in guide_text
    assert "TaskCreate" in guide_text
    assert "persistent workflow" in guide_text
    assert "runtime jobs are not workflow tasks" in guide_text


def test_subagent_usage_guide_covers_runtime_tool_surface():
    guide_text = SUBAGENT_GUIDE.read_text(encoding="utf-8")

    assert "# Subagent Usage Guide" in guide_text
    assert "`Agent`" in guide_text
    assert "`description`" in guide_text
    assert "`prompt`" in guide_text
    assert "`subagent_type`" in guide_text
    assert "`run_in_background`" in guide_text
    assert "`/runs`" in guide_text
    assert "`/run-show <run_id>`" in guide_text
    assert "`/run-stop <run_id>`" in guide_text
    assert "runtime jobs are not workflow tasks" in guide_text
    assert "`/tasks`" in guide_text
    assert "/task-" not in guide_text
    assert "TaskStatus" not in guide_text
    assert "TaskRegistry" not in guide_text
