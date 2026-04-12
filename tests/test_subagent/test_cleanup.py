from types import SimpleNamespace

from bourbon.subagent.cancel import AbortController
from bourbon.subagent.cleanup import ResourceManager
from bourbon.subagent.types import RunStatus, SubagentRun


def test_resource_manager_marks_running_run_as_killed():
    manager = ResourceManager(register_atexit=False)
    run = SubagentRun(description="Run", prompt="Do it", status=RunStatus.RUNNING)

    manager.register(run)
    manager.cleanup_all()

    assert run.status == RunStatus.KILLED


def test_resource_manager_aborts_running_run_controller():
    manager = ResourceManager(register_atexit=False)
    controller = AbortController()
    run = SubagentRun(
        description="Run",
        prompt="Do it",
        status=RunStatus.RUNNING,
        abort_controller=controller,
    )

    manager.register(run)
    manager.cleanup_all()

    assert controller.is_aborted() is True


def test_resource_manager_skips_completed_run():
    manager = ResourceManager(register_atexit=False)
    run = SubagentRun(description="Run", prompt="Do it", status=RunStatus.COMPLETED)

    manager.register(run)
    manager.cleanup_all()

    assert run.status == RunStatus.COMPLETED


def test_resource_manager_shuts_down_attached_subagent():
    manager = ResourceManager(register_atexit=False)
    shutdown_calls = []
    subagent = SimpleNamespace(shutdown_mcp_sync=lambda: shutdown_calls.append("called"))
    run = SubagentRun(description="Run", prompt="Do it", status=RunStatus.RUNNING)
    run._subagent = subagent

    manager.register(run)
    manager.cleanup_all()

    assert shutdown_calls == ["called"]


def test_resource_manager_exported_from_package():
    from bourbon.subagent import ResourceManager as ExportedResourceManager

    assert ExportedResourceManager is ResourceManager
