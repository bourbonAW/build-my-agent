from bourbon.session.storage import TranscriptStore
from bourbon.subagent.session_adapter import SubagentSessionAdapter


def test_session_adapter_creates_isolated_subagent_session(tmp_path):
    store = TranscriptStore(base_dir=tmp_path)
    adapter = SubagentSessionAdapter(
        parent_store=store,
        project_name="project",
        project_dir="/workspace/project",
        run_id="run123",
    )

    session = adapter.create_session()

    assert session.project_name == "project/subagents"
    assert session.metadata.project_dir == "/workspace/project"
    assert session.metadata.description == "Subagent run run123"
    assert session.chain.message_count == 0


def test_session_adapter_persists_metadata_via_session_manager(tmp_path):
    store = TranscriptStore(base_dir=tmp_path)
    adapter = SubagentSessionAdapter(
        parent_store=store,
        project_name="project",
        project_dir="/workspace/project",
        run_id="run123",
    )

    session = adapter.create_session()
    sessions = store.list_sessions("project/subagents")

    assert len(sessions) == 1
    assert sessions[0].uuid == session.session_id
    assert sessions[0].description == "Subagent run run123"


def test_session_adapter_exported_from_package():
    from bourbon.subagent import SubagentSessionAdapter as ExportedAdapter

    assert ExportedAdapter is SubagentSessionAdapter
