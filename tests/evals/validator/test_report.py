"""Tests for validator report models."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evals.validator.report import ValidationDimension, ValidationReport


def test_validation_dimension_marks_passed_when_score_meets_threshold() -> None:
    dimension = ValidationDimension(
        name="quality",
        score=8.0,
        weight=0.4,
        threshold=7.0,
    )

    assert dimension.passed is True


def test_validation_report_computes_weighted_overall_score() -> None:
    report = ValidationReport(
        dimensions=[
            ValidationDimension(name="correctness", score=9.0, weight=0.6, threshold=8.0),
            ValidationDimension(name="quality", score=7.0, weight=0.4, threshold=7.0),
        ],
        overall_threshold=8.0,
    )

    assert report.overall_score == 8.2
    assert report.passed is True


def test_validation_report_save_and_load_roundtrip(tmp_path: Path) -> None:
    report = ValidationReport(
        dimensions=[
            ValidationDimension(
                name="correctness",
                score=8.5,
                weight=1.0,
                threshold=9.0,
                reasoning="core behavior is mostly correct",
                evidence=["src/main.py:10"],
                suggestions=["cover empty input"],
            ),
        ],
        overall_threshold=8.0,
        summary="close but not fully correct",
        version="1.0",
        timestamp="2026-03-30T00:00:00Z",
        evaluator_focus=["correctness"],
        skills_used=["eval-correctness"],
        telemetry={
            "focus_dimensions": ["correctness"],
            "skills_invoked": ["eval-correctness"],
            "duration_ms": 12,
            "token_usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        },
    )

    report_path = tmp_path / "report.json"
    report.save(report_path)
    loaded = ValidationReport.load(report_path)

    assert loaded.dimensions[0].name == "correctness"
    assert loaded.dimensions[0].evidence == ["src/main.py:10"]
    assert loaded.summary == "close but not fully correct"
    assert loaded.version == "1.0"
    assert loaded.timestamp == "2026-03-30T00:00:00Z"
    assert loaded.evaluator_focus == ["correctness"]
    assert loaded.skills_used == ["eval-correctness"]
    assert loaded.telemetry["duration_ms"] == 12


def test_validation_report_normalizes_weights_and_warns() -> None:
    with pytest.warns(UserWarning, match="normalized"):
        report = ValidationReport(
            dimensions=[
                ValidationDimension(name="correctness", score=9.0, weight=3.0, threshold=8.0),
                ValidationDimension(name="quality", score=6.0, weight=1.0, threshold=7.0),
            ],
            overall_threshold=7.0,
        )

    assert report.dimensions[0].weight == pytest.approx(0.75)
    assert report.dimensions[1].weight == pytest.approx(0.25)
    assert report.overall_score == pytest.approx(8.25)


def test_validation_report_converts_to_assertions() -> None:
    report = ValidationReport(
        dimensions=[
            ValidationDimension(
                name="quality",
                score=7.5,
                weight=1.0,
                threshold=8.0,
                reasoning="needs better naming",
            ),
        ],
        overall_threshold=8.0,
        summary="quality below target",
    )

    assertions = report.to_assertions()

    assert assertions[0]["id"] == "eval_quality"
    assert assertions[0]["passed"] is False
    assert assertions[-1]["id"] == "eval_overall"
