"""Tests for evaluator subprocess orchestration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evals.validator.artifact import ArtifactBuilder
from evals.validator.evaluator_agent import EvaluatorAgentRunner, EvaluatorConfig, run_evaluator_agent
from evals.validator.report import ValidationReport


def test_evaluator_agent_runner_invokes_subprocess_and_returns_report(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")
    artifact_dir = ArtifactBuilder(case_id="case-001", workdir=workdir).build()

    report_path = artifact_dir.parent / "validation" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('{"dimensions": [], "overall_threshold": 8.0}', encoding="utf-8")

    runner = EvaluatorAgentRunner(artifact_dir=artifact_dir, focus=["correctness"])

    with patch("subprocess.run", return_value=Mock(returncode=0, stderr="")) as run_mock:
        returned_path = runner.run()

    assert returned_path == report_path
    assert run_mock.called


def test_run_evaluator_agent_writes_report_with_dimension_config(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")
    artifact_dir = ArtifactBuilder(case_id="case-002", workdir=workdir).build()

    report = run_evaluator_agent(
        EvaluatorConfig(
            artifact_dir=artifact_dir,
            focus=["correctness"],
            threshold=8.0,
            timeout=30,
            dimensions_config={"correctness": {"weight": 0.6, "threshold": 9.0}},
        )
    )

    saved = ValidationReport.load(artifact_dir.parent / "validation" / "report.json")

    assert report.dimensions[0].name == "correctness"
    assert report.dimensions[0].weight == 0.6
    assert report.dimensions[0].threshold == 9.0
    assert saved.dimensions[0].name == "correctness"


def test_full_evaluator_subprocess_flow(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")
    artifact_dir = ArtifactBuilder(case_id="case-003", workdir=workdir).build()

    report_path = EvaluatorAgentRunner(
        artifact_dir=artifact_dir,
        focus=["correctness"],
        threshold=8.0,
        dimensions_config={"correctness": {"weight": 0.7, "threshold": 9.0}},
    ).run()

    report = ValidationReport.load(report_path)

    assert report.dimensions[0].name == "correctness"
    assert report.dimensions[0].weight == 0.7
    assert report.dimensions[0].threshold == 9.0
