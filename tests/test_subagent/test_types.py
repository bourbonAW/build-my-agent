from datetime import datetime

from bourbon.subagent.types import AgentDefinition, RunStatus, SubagentRun


def test_run_status_enum_values():
    assert RunStatus.PENDING.value == "pending"
    assert RunStatus.RUNNING.value == "running"
    assert RunStatus.COMPLETED.value == "completed"
    assert RunStatus.FAILED.value == "failed"
    assert RunStatus.KILLED.value == "killed"


def test_agent_definition_defaults_to_all_tools_except_disallowed():
    agent_def = AgentDefinition(
        agent_type="coder",
        description="Code specialist",
        max_turns=100,
    )

    assert agent_def.agent_type == "coder"
    assert agent_def.max_turns == 100
    assert agent_def.allowed_tools is None
    assert agent_def.disallowed_tools == []


def test_agent_definition_with_allowed_tools():
    agent_def = AgentDefinition(
        agent_type="explore",
        description="Read-only explorer",
        allowed_tools=["Read", "Grep"],
    )

    assert agent_def.allowed_tools == ["Read", "Grep"]


def test_subagent_run_creation_defaults():
    run = SubagentRun(
        description="Test run",
        prompt="Do something",
        agent_type="default",
    )

    assert len(run.run_id) == 8
    assert run.description == "Test run"
    assert run.status == RunStatus.PENDING
    assert run.is_async is False
    assert run.tool_call_count == 0
    assert isinstance(run.created_at, datetime)


def test_subagent_run_to_dict_truncates_description():
    run = SubagentRun(
        description="A very long description that should be truncated for table display",
        prompt="Do something",
        agent_type="coder",
        status=RunStatus.RUNNING,
    )

    payload = run.to_dict()

    assert payload["run_id"] == run.run_id
    assert payload["agent_type"] == "coder"
    assert payload["status"] == "running"
    assert payload["description"].endswith("...")
    assert payload["tool_calls"] == 0


def test_subagent_run_exported_from_package():
    from bourbon.subagent import SubagentRun as ExportedSubagentRun

    assert ExportedSubagentRun is SubagentRun


from bourbon.subagent.types import SubagentMode


def test_subagent_mode_values():
    assert SubagentMode.NORMAL.value == "normal"
    assert SubagentMode.TEAMMATE.value == "teammate"
    assert SubagentMode.ASYNC.value == "async"


def test_subagent_run_has_subagent_mode_field():
    from bourbon.subagent.types import SubagentRun
    run = SubagentRun()
    assert run.subagent_mode == SubagentMode.NORMAL


def test_subagent_run_has_parent_task_list_id_field():
    from bourbon.subagent.types import SubagentRun
    run = SubagentRun()
    assert run.parent_task_list_id is None
