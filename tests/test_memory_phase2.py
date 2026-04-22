import json
from pathlib import Path

import pytest

from bourbon.config import MemoryConfig
from bourbon.memory.manager import MemoryManager
from bourbon.tools import ToolContext
from bourbon.tools.memory import memory_archive, memory_promote, memory_search, memory_write


@pytest.fixture
def phase2_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ToolContext:
    monkeypatch.setenv("HOME", str(tmp_path))
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    manager = MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path / "store")),
        project_key="phase2-project",
        workdir=workdir,
        audit=None,
    )
    return ToolContext(workdir=workdir, memory_manager=manager)


def test_memory_phase2_full_lifecycle(phase2_context: ToolContext, tmp_path: Path) -> None:
    write_result = json.loads(
        memory_write(
            content="Always answer with concise bullets.",
            kind="feedback",
            scope="user",
            source="user",
            name="concise bullets",
            description="Stable response formatting preference",
            ctx=phase2_context,
        )
    )
    memory_id = write_result["id"]

    promote_result = json.loads(
        memory_promote(
            memory_id=memory_id,
            note="Observed across multiple turns",
            ctx=phase2_context,
        )
    )
    assert promote_result["id"] == memory_id
    assert promote_result["status"] == "promoted"

    promoted_search = json.loads(
        memory_search(query="concise", status=["promoted"], ctx=phase2_context)
    )
    assert [item["id"] for item in promoted_search["results"]] == [memory_id]

    archive_result = json.loads(
        memory_archive(
            memory_id=memory_id,
            status="rejected",
            reason="No longer correct",
            ctx=phase2_context,
        )
    )
    assert archive_result["id"] == memory_id
    assert archive_result["status"] == "rejected"

    rejected_search = json.loads(
        memory_search(query="concise", status=["rejected"], ctx=phase2_context)
    )
    assert [item["id"] for item in rejected_search["results"]] == [memory_id]

    user_md = tmp_path / ".bourbon" / "USER.md"
    text = user_md.read_text(encoding="utf-8")
    assert f'<!-- bourbon-memory:start id="{memory_id}" -->' in text
    assert "- status: rejected" in text


def test_memory_phase2_repromote_after_stale_does_not_duplicate_managed_block(
    phase2_context: ToolContext,
    tmp_path: Path,
) -> None:
    write_result = json.loads(
        memory_write(
            content="Always use uv for Python package operations.",
            kind="user",
            scope="user",
            source="user",
            name="uv preference",
            description="Use uv instead of pip",
            ctx=phase2_context,
        )
    )
    memory_id = write_result["id"]

    first_promote = json.loads(memory_promote(memory_id=memory_id, ctx=phase2_context))
    assert first_promote["status"] == "promoted"

    archived = json.loads(
        memory_archive(
            memory_id=memory_id,
            status="stale",
            reason="Temporary exception",
            ctx=phase2_context,
        )
    )
    assert archived["status"] == "stale"

    second_promote = json.loads(
        memory_promote(
            memory_id=memory_id,
            note="Preference resumed",
            ctx=phase2_context,
        )
    )
    assert second_promote["status"] == "promoted"

    promoted_search = json.loads(memory_search(query="uv", status=["promoted"], ctx=phase2_context))
    assert [item["id"] for item in promoted_search["results"]] == [memory_id]

    user_md = tmp_path / ".bourbon" / "USER.md"
    text = user_md.read_text(encoding="utf-8")
    assert text.count(f'<!-- bourbon-memory:start id="{memory_id}" -->') == 1
    assert "- note: Preference resumed" in text
