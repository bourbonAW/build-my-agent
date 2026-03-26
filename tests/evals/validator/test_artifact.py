"""Tests for validator artifact generation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evals.validator.artifact import ArtifactBuilder, OutputArtifact


def test_artifact_builder_creates_expected_structure(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")

    artifact_dir = ArtifactBuilder(case_id="case-001", workdir=workdir).build()

    assert (artifact_dir / "meta.json").exists()
    assert (artifact_dir / "context.json").exists()
    assert (artifact_dir / "output.json").exists()
    assert (artifact_dir / "workspace" / "main.py").exists()


def test_artifact_roundtrip_loads_saved_metadata(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")

    builder = ArtifactBuilder(case_id="case-002", workdir=workdir)
    builder.set_meta(duration_ms=123)
    builder.set_context(prompt="do the thing", success_criteria=["ship it"])
    builder.set_output(final_output="done")

    artifact_dir = builder.build()
    loaded = OutputArtifact.load(artifact_dir)

    assert loaded.case_id == "case-002"
    assert loaded.meta["duration_ms"] == 123
    assert loaded.context["prompt"] == "do the thing"
    assert loaded.output["final_output"] == "done"


def test_artifact_builder_respects_additional_exclude_patterns(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "keep.txt").write_text("keep\n", encoding="utf-8")
    (workdir / "ignore.log").write_text("ignore\n", encoding="utf-8")

    artifact_dir = (
        ArtifactBuilder(case_id="case-003", workdir=workdir)
        .add_exclude_patterns(["*.log"])
        .build()
    )

    assert (artifact_dir / "workspace" / "keep.txt").exists()
    assert not (artifact_dir / "workspace" / "ignore.log").exists()


def test_size_limit_truncates_snapshot_without_mutating_live_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    large_file = workdir / "large.txt"
    large_file.write_text(("line\n" * 1500), encoding="utf-8")
    original_content = large_file.read_text(encoding="utf-8")

    artifact_dir = ArtifactBuilder(
        case_id="case-004",
        workdir=workdir,
        max_size_mb=0.0001,
    ).build()

    assert large_file.read_text(encoding="utf-8") == original_content

    snapshot_content = (artifact_dir / "workspace" / "large.txt").read_text(encoding="utf-8")
    assert "[TRUNCATED:" in snapshot_content
