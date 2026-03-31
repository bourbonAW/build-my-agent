"""Tests for calibration case runner support."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_run_single_routes_to_calibration(tmp_path: Path):
    """run_single dispatches to _run_calibration_case when pre_built_artifact is True."""
    from unittest.mock import MagicMock, patch

    from evals.runner import EvalRunner

    runner = EvalRunner.__new__(EvalRunner)
    runner.config = {}

    case = {
        "id": "test-calibration",
        "pre_built_artifact": True,
        "evaluator": {"enabled": True},
    }

    mock_result = MagicMock()
    with patch.object(runner, "_run_calibration_case", return_value=mock_result) as mock_method:
        result = runner.run_single(case, run_number=1)

    mock_method.assert_called_once_with(case, 1)
    assert result is mock_result


def test_run_calibration_case_missing_artifact_dir(tmp_path: Path, monkeypatch):
    """_run_calibration_case fails gracefully when artifact/ subdirectory is missing."""
    from evals.runner import EvalRunner

    runner = EvalRunner.__new__(EvalRunner)
    runner.config = {}

    # Fixture without artifact/ subdirectory
    fixture_dir = tmp_path / "fixtures" / "bad-fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "context.json").write_text("{}", encoding="utf-8")

    case = {
        "id": "test-missing-artifact",
        "pre_built_artifact": True,
        "context": {"workdir": "fixtures/bad-fixture"},
        "evaluator": {"enabled": True, "focus": ["correctness"]},
    }

    # Patch _setup_workspace to return our fixture
    def fake_setup(c):
        dest = tmp_path / "workdir"
        shutil.copytree(fixture_dir, dest, dirs_exist_ok=True)
        return dest

    monkeypatch.setattr(runner, "_setup_workspace", fake_setup)

    result = runner._run_calibration_case(case, run_number=1)

    assert result.success is False
    assert "artifact" in result.error.lower()


def test_calibration_success_only_uses_calibration_assertions():
    """Success is determined by calibration_* assertions, not eval_* threshold assertions.

    This is critical: Buggy variants will have failing eval_* assertions (score < threshold)
    but should still pass if calibration_* assertions (score in expected range) pass.
    """
    from evals.validator.report import ValidationDimension, ValidationReport

    # Simulate a Buggy variant: low score that is BELOW threshold but IN expected range
    dim = ValidationDimension(
        name="correctness",
        score=3.0,
        weight=0.7,
        threshold=8.0,  # score 3.0 < threshold 8.0 → eval_correctness fails
        skill="eval-correctness",
        reasoning="Bad implementation",
        evidence=["has bugs"],
    )
    report = ValidationReport(dimensions=[dim], overall_threshold=8.0)

    assertion_results = report.to_assertions()
    # eval_correctness should be failing (score < threshold)
    eval_assertion = next(a for a in assertion_results if a["id"] == "eval_correctness")
    assert eval_assertion["passed"] is False

    # Add calibration assertion — score 3.0 IS in expected range [1, 4]
    expected_scores = {"correctness": {"min": 1, "max": 4}}
    for dim_name, expected in expected_scores.items():
        actual = next((d for d in report.dimensions if d.name == dim_name), None)
        if actual is None:
            assertion_results.append(
                {"id": f"calibration_{dim_name}", "passed": False, "evidence": ""}
            )
        else:
            in_range = expected["min"] <= actual.score <= expected["max"]
            assertion_results.append(
                {"id": f"calibration_{dim_name}", "passed": in_range, "evidence": ""}
            )

    # Success should be True because calibration_* assertions pass
    calibration_assertions = [a for a in assertion_results if a["id"].startswith("calibration_")]
    success = bool(calibration_assertions) and all(a["passed"] for a in calibration_assertions)
    assert success is True


def test_calibration_expected_scores_out_of_range():
    """Calibration assertions fail when actual scores are outside expected range."""
    from evals.validator.report import ValidationDimension, ValidationReport

    dim = ValidationDimension(
        name="correctness",
        score=5.0,
        weight=0.7,
        threshold=8.0,
        skill="eval-correctness",
        reasoning="Mediocre",
        evidence=["partial"],
    )
    report = ValidationReport(dimensions=[dim], overall_threshold=8.0)

    expected_scores = {"correctness": {"min": 9, "max": 10}}
    assertions = []

    for dim_name, expected in expected_scores.items():
        actual = next((d for d in report.dimensions if d.name == dim_name), None)
        if actual is None:
            assertions.append({"id": f"calibration_{dim_name}", "passed": False, "evidence": ""})
        else:
            in_range = expected["min"] <= actual.score <= expected["max"]
            assertions.append({"id": f"calibration_{dim_name}", "passed": in_range, "evidence": ""})

    calibration_assertion = next(a for a in assertions if a["id"] == "calibration_correctness")
    assert calibration_assertion["passed"] is False


def test_calibration_missing_dimension():
    """Calibration assertions fail when expected dimension is missing from report."""
    from evals.validator.report import ValidationDimension, ValidationReport

    dim = ValidationDimension(
        name="quality",
        score=8.0,
        weight=0.3,
        threshold=6.0,
        skill="eval-quality",
        reasoning="Good quality",
        evidence=["clean"],
    )
    report = ValidationReport(dimensions=[dim], overall_threshold=8.0)

    expected_scores = {"correctness": {"min": 9, "max": 10}}
    assertions = []

    for dim_name, expected in expected_scores.items():
        actual = next((d for d in report.dimensions if d.name == dim_name), None)
        if actual is None:
            assertions.append({
                "id": f"calibration_{dim_name}",
                "passed": False,
                "evidence": f"dimension '{dim_name}' not found",
            })
        else:
            in_range = expected["min"] <= actual.score <= expected["max"]
            assertions.append({"id": f"calibration_{dim_name}", "passed": in_range, "evidence": ""})

    assert len(assertions) == 1
    assert assertions[0]["passed"] is False
    assert "not found" in assertions[0]["evidence"]
