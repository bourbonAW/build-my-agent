"""Integration tests for eval validator runner hooks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bourbon import __version__
from evals.runner import EvalRunner
from evals.validator.report import ValidationDimension, ValidationReport


class _FakeAgent:
    def __init__(self, *_args, **_kwargs) -> None:
        self.audit = type("Audit", (), {"enabled": False})()
        self.skills = type(
            "_Skills",
            (),
            {
                "_skills": {},
                "_discover": lambda self: None,
                "activate": lambda self, _name: "",
            },
        )()
        self.system_prompt = ""

    def reset_token_usage(self) -> None:
        return None

    def step(self, _prompt: str) -> str:
        return "done"

    def get_token_usage(self) -> dict:
        return {"total_tokens": 1}

    def _build_system_prompt(self) -> str:
        return "prompt"


def _fake_evaluator_run(runner_self) -> Path:
    """Simulate EvaluatorAgentRunner.run() without subprocess or real LLM.

    Returns a report with score 8.5 for each dimension (same as old Phase 1).
    """
    dimensions = []
    for dim_name in runner_self.focus:
        dim_config = runner_self.dimensions_config.get(dim_name, {})
        threshold = dim_config.get("threshold", runner_self.threshold)
        weight = dim_config.get("weight", 1.0 / len(runner_self.focus))
        dimensions.append(
            ValidationDimension(
                name=dim_name,
                score=8.5,
                weight=weight,
                threshold=threshold,
                skill=runner_self.dimension_to_skill.get(dim_name, ""),
                reasoning="mocked evaluation",
                evidence=["mocked"],
            )
        )
    report = ValidationReport(
        dimensions=dimensions,
        overall_threshold=runner_self.threshold,
        summary="mocked validation",
    )
    report_path = runner_self.artifact_dir.parent / "validation" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.save(report_path)
    return report_path


def test_run_validation_executes_evaluator_and_returns_assertions(tmp_path: Path) -> None:
    runner = EvalRunner.__new__(EvalRunner)
    runner.config = {
        "evaluator": {
            "default_threshold": 8.0,
            "default_timeout": 30,
            "default_dimensions": {
                "correctness": {"weight": 1.0, "threshold": 9.0},
            },
        }
    }

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")

    with patch(
        "evals.validator.evaluator_agent.EvaluatorAgentRunner.run",
        _fake_evaluator_run,
    ):
        result = runner._run_validation(
            case={
                "id": "validation-case",
                "prompt": "write code",
                "assertions": [{"id": "file_exists", "check": "file_exists:main.py"}],
                "evaluator": {
                    "enabled": True,
                    "focus": ["correctness"],
                    "threshold": 9.0,
                },
            },
            output="done",
            workdir=workdir,
            duration_ms=10,
            token_usage={"total_tokens": 1},
        )

    assert result["passed"] is False
    assert {assertion["id"] for assertion in result["assertions"]} == {
        "eval_correctness",
        "eval_overall",
    }


def test_run_single_merges_validation_failure_into_result(tmp_path: Path) -> None:
    runner = EvalRunner.__new__(EvalRunner)
    runner.config = {
        "evaluator": {
            "default_threshold": 8.0,
            "default_timeout": 30,
            "default_dimensions": {
                "correctness": {"weight": 1.0, "threshold": 9.0},
            },
        }
    }
    runner.fast_mode = True
    runner.num_runs = 1
    runner.timeout = 60
    runner.bourbon_config = None
    runner.case_results = []
    runner._setup_workspace = lambda _case: tmp_path / "workdir"
    runner._cleanup_workspace = lambda _workdir: None
    runner._load_bourbon_config = lambda: {}

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")

    case = {
        "id": "validation-case",
        "prompt": "write code",
        "assertions": [],
        "evaluator": {
            "enabled": True,
            "focus": ["correctness"],
            "threshold": 9.0,
        },
    }

    with patch("evals.runner.Agent", _FakeAgent), patch(
        "evals.validator.evaluator_agent.EvaluatorAgentRunner.run",
        _fake_evaluator_run,
    ):
        result = runner.run_single(case)

    assert result.success is False
    assert {assertion["id"] for assertion in result.assertions} == {
        "eval_correctness",
        "eval_overall",
    }


def test_run_validation_writes_artifact_contract_and_applies_excludes(tmp_path: Path) -> None:
    runner = EvalRunner.__new__(EvalRunner)
    runner.config = {
        "evaluator": {
            "default_threshold": 8.0,
            "default_timeout": 30,
            "exclude_patterns": {
                "patterns": ["*.log"],
            },
            "default_dimensions": {
                "correctness": {"weight": 1.0, "threshold": 8.0},
            },
        }
    }

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (workdir / "ignore.log").write_text("ignore me\n", encoding="utf-8")

    def _asserting_run(runner_self) -> Path:
        meta = json.loads((runner_self.artifact_dir / "meta.json").read_text(encoding="utf-8"))
        output = json.loads((runner_self.artifact_dir / "output.json").read_text(encoding="utf-8"))

        assert meta["generator_version"] == f"bourbon-{__version__}"
        assert output["tool_calls"] == [
            {"tool": "read_file", "args": {"path": "main.py"}, "result": "print('hello')"}
        ]
        assert output["errors"] == ["Denied: missing permission"]
        assert not (runner_self.artifact_dir / "workspace" / "ignore.log").exists()

        report = ValidationReport(
            dimensions=[
                ValidationDimension(
                    name="correctness",
                    score=9.0,
                    weight=1.0,
                    threshold=8.0,
                    reasoning="artifact contract present",
                    evidence=["meta.json and output.json verified"],
                )
            ],
            overall_threshold=8.0,
            summary="ok",
        )
        report_path = runner_self.artifact_dir.parent / "validation" / "report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report.save(report_path)
        return report_path

    with patch("evals.validator.evaluator_agent.EvaluatorAgentRunner.run", _asserting_run):
        result = runner._run_validation(
            case={
                "id": "validation-case",
                "prompt": "write code",
                "assertions": [],
                "evaluator": {
                    "enabled": True,
                    "focus": ["correctness"],
                },
            },
            output="done",
            workdir=workdir,
            duration_ms=10,
            token_usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            tool_calls=[
                {"tool": "read_file", "args": {"path": "main.py"}, "result": "print('hello')"}
            ],
            errors=["Denied: missing permission"],
        )

    assert result["passed"] is True


def test_run_single_skips_cleanup_when_keep_artifacts_is_set(tmp_path: Path) -> None:
    runner = EvalRunner.__new__(EvalRunner)
    runner.config = {"evaluator": {}}
    runner.fast_mode = True
    runner.num_runs = 1
    runner.timeout = 60
    runner.bourbon_config = None
    runner.case_results = []
    runner._load_bourbon_config = lambda: {}

    workdir = tmp_path / "workdir"
    workdir.mkdir()

    runner._setup_workspace = lambda _case: workdir
    runner._cleanup_workspace = MagicMock()

    case = {
        "id": "keep-artifacts",
        "prompt": "write code",
        "assertions": [],
    }

    with patch("evals.runner.Agent", _FakeAgent), patch.dict(
        os.environ,
        {"EVAL_KEEP_ARTIFACTS": "1"},
        clear=False,
    ):
        result = runner.run_single(case)

    assert result.success is True
    runner._cleanup_workspace.assert_not_called()
