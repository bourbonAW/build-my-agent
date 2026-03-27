"""Tests for Phase 2 evaluator agent with real Agent calls."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evals.validator.artifact import ArtifactBuilder
from evals.validator.evaluator_agent import (
    EVALUATOR_SYSTEM_PROMPT,
    EvaluatorConfig,
    build_evaluation_prompt,
    run_evaluator_agent,
)


def _make_artifact(tmp_path: Path) -> Path:
    """Helper: create a minimal artifact for testing."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")
    builder = ArtifactBuilder(case_id="test-001", workdir=workdir)
    builder.set_context(prompt="Write hello world", success_criteria=["prints hello"])
    builder.set_output(final_output="Done")
    return builder.build()


def test_evaluator_system_prompt_exists():
    """EVALUATOR_SYSTEM_PROMPT is defined and contains evaluator role."""
    lower = EVALUATOR_SYSTEM_PROMPT.lower()
    assert "评审" in EVALUATOR_SYSTEM_PROMPT or "evaluator" in lower or "review" in lower
    assert "submit_evaluation" in EVALUATOR_SYSTEM_PROMPT


def test_build_evaluation_prompt_contains_skill_and_steps():
    """build_evaluation_prompt includes dimension name and skill name."""
    prompt = build_evaluation_prompt("correctness", "eval-correctness")
    assert "correctness" in prompt
    assert "eval-correctness" in prompt
    assert "context.json" in prompt
    assert "submit_evaluation" in prompt


def test_run_evaluator_agent_calls_agent_step(tmp_path: Path):
    """run_evaluator_agent creates Agent and calls step() per dimension."""
    artifact_dir = _make_artifact(tmp_path)

    mock_agent = MagicMock()
    mock_agent.messages = []
    def fake_step(prompt):
        from evals.validator.submit_tool import handle_submit
        handle_submit(score=8.0, reasoning="Good", evidence=["file.py works"])
        return "Evaluation complete"

    mock_agent.step.side_effect = fake_step

    with patch(
        "evals.validator.evaluator_agent.create_evaluator_agent",
        return_value=mock_agent,
    ):
        report = run_evaluator_agent(
            EvaluatorConfig(
                artifact_dir=artifact_dir,
                focus=["correctness"],
                threshold=8.0,
                timeout=60,
                dimension_to_skill={"correctness": "eval-correctness"},
            )
        )

    assert mock_agent.step.call_count == 1
    assert report.dimensions[0].score == 8.0
    assert report.dimensions[0].reasoning == "Good"


def test_run_evaluator_agent_handles_missing_submission(tmp_path: Path):
    """When LLM never calls submit_evaluation, dimension gets score=0."""
    artifact_dir = _make_artifact(tmp_path)

    mock_agent = MagicMock()
    mock_agent.messages = []
    mock_agent.step.return_value = "I analyzed the code but forgot to submit."

    with patch(
        "evals.validator.evaluator_agent.create_evaluator_agent",
        return_value=mock_agent,
    ):
        report = run_evaluator_agent(
            EvaluatorConfig(
                artifact_dir=artifact_dir,
                focus=["correctness"],
                threshold=8.0,
                timeout=60,
                dimension_to_skill={"correctness": "eval-correctness"},
            )
        )

    assert report.dimensions[0].score == 0.0
    assert "no evaluation submitted" in report.dimensions[0].reasoning


def test_run_evaluator_agent_handles_step_exception(tmp_path: Path):
    """When agent.step() raises, dimension gets score=0 with error message."""
    artifact_dir = _make_artifact(tmp_path)

    mock_agent = MagicMock()
    mock_agent.messages = []
    mock_agent.step.side_effect = RuntimeError("LLM connection failed")

    with patch(
        "evals.validator.evaluator_agent.create_evaluator_agent",
        return_value=mock_agent,
    ):
        report = run_evaluator_agent(
            EvaluatorConfig(
                artifact_dir=artifact_dir,
                focus=["correctness"],
                threshold=8.0,
                timeout=60,
                dimension_to_skill={"correctness": "eval-correctness"},
            )
        )

    assert report.dimensions[0].score == 0.0
    assert "LLM connection failed" in report.dimensions[0].reasoning


def test_run_evaluator_agent_multiple_dimensions(tmp_path: Path):
    """Each dimension gets an independent step() call."""
    artifact_dir = _make_artifact(tmp_path)

    mock_agent = MagicMock()
    mock_agent.messages = []
    call_count = 0

    def fake_step(prompt):
        nonlocal call_count
        from evals.validator.submit_tool import handle_submit
        call_count += 1
        if "correctness" in prompt:
            handle_submit(score=9.0, reasoning="Correct", evidence=["all criteria met"])
        else:
            handle_submit(score=7.5, reasoning="Decent", evidence=["clean code"])
        return "Done"

    mock_agent.step.side_effect = fake_step

    with patch(
        "evals.validator.evaluator_agent.create_evaluator_agent",
        return_value=mock_agent,
    ):
        report = run_evaluator_agent(
            EvaluatorConfig(
                artifact_dir=artifact_dir,
                focus=["correctness", "quality"],
                threshold=8.0,
                timeout=60,
                dimension_to_skill={
                    "correctness": "eval-correctness",
                    "quality": "eval-quality",
                },
            )
        )

    assert call_count == 2
    assert report.dimensions[0].name == "correctness"
    assert report.dimensions[0].score == 9.0
    assert report.dimensions[1].name == "quality"
    assert report.dimensions[1].score == 7.5
