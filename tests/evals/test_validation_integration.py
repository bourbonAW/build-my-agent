"""Integration tests for eval validator runner hooks."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.runner import EvalRunner


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

    with patch("evals.runner.Agent", _FakeAgent):
        result = runner.run_single(case)

    assert result.success is False
    assert {assertion["id"] for assertion in result.assertions} == {
        "eval_correctness",
        "eval_overall",
    }
