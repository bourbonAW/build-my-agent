from bourbon.subagent.registry import RunRegistry
from bourbon.subagent.types import RunStatus, SubagentRun


def test_registry_empty():
    registry = RunRegistry()

    assert registry.list_all() == []
    assert registry.get("nonexistent") is None


def test_registry_register_run():
    registry = RunRegistry()
    run = SubagentRun(description="Test", prompt="Do it")

    registry.register(run)

    assert registry.get(run.run_id) == run
    assert registry.get_run(run.run_id) == run


def test_registry_list_all():
    registry = RunRegistry()
    run1 = SubagentRun(description="Run 1", prompt="Do 1")
    run2 = SubagentRun(description="Run 2", prompt="Do 2")

    registry.register(run1)
    registry.register(run2)

    runs = registry.list_all()
    assert len(runs) == 2
    assert run1 in runs
    assert run2 in runs
    assert registry.list_runs() == runs


def test_registry_list_by_status():
    registry = RunRegistry()
    run1 = SubagentRun(description="Running", prompt="Run")
    run1.status = RunStatus.RUNNING
    run2 = SubagentRun(description="Pending", prompt="Wait")
    run2.status = RunStatus.PENDING

    registry.register(run1)
    registry.register(run2)

    running = registry.list_all(status=RunStatus.RUNNING)

    assert len(running) == 1
    assert running[0].description == "Running"


def test_registry_list_by_agent_type():
    registry = RunRegistry()
    coder = SubagentRun(description="Coder", prompt="Code", agent_type="coder")
    explorer = SubagentRun(description="Explore", prompt="Read", agent_type="explore")

    registry.register(coder)
    registry.register(explorer)

    assert registry.list_all(agent_type="explore") == [explorer]


def test_registry_update_status_sets_started_at_once():
    registry = RunRegistry()
    run = SubagentRun(description="Test", prompt="Do it")
    registry.register(run)

    assert registry.update_status(run.run_id, RunStatus.RUNNING) is True
    first_started_at = registry.get(run.run_id).started_at
    assert first_started_at is not None

    assert registry.update_status(run.run_id, RunStatus.RUNNING) is True
    assert registry.get(run.run_id).started_at == first_started_at


def test_registry_update_status_returns_false_for_missing_run():
    registry = RunRegistry()

    assert registry.update_status("missing", RunStatus.RUNNING) is False


def test_registry_complete():
    registry = RunRegistry()
    run = SubagentRun(description="Test", prompt="Do it")
    registry.register(run)

    assert registry.complete(run.run_id, "Result content") is True

    updated = registry.get(run.run_id)
    assert updated.status == RunStatus.COMPLETED
    assert updated.result == "Result content"
    assert updated.completed_at is not None


def test_registry_fail():
    registry = RunRegistry()
    run = SubagentRun(description="Test", prompt="Do it")
    registry.register(run)

    assert registry.fail(run.run_id, "Something went wrong") is True

    updated = registry.get(run.run_id)
    assert updated.status == RunStatus.FAILED
    assert updated.error == "Something went wrong"
    assert updated.completed_at is not None


def test_run_registry_exported_from_package():
    from bourbon.subagent import RunRegistry as ExportedRunRegistry

    assert ExportedRunRegistry is RunRegistry
