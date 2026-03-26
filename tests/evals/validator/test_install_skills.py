"""Tests for hermetic evaluator skill installation."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evals.runner import EvalRunner
from evals.validator.install_skills import install_skills


def test_install_skills_copies_and_overwrites_eval_skill_directories(tmp_path: Path) -> None:
    builtin_dir = tmp_path / "builtin"
    user_dir = tmp_path / "user"
    (builtin_dir / "eval-correctness").mkdir(parents=True)
    (builtin_dir / "eval-correctness" / "SKILL.md").write_text("new\n", encoding="utf-8")
    (builtin_dir / "eval-quality").mkdir(parents=True)
    (builtin_dir / "eval-quality" / "SKILL.md").write_text("quality\n", encoding="utf-8")

    (user_dir / "eval-correctness").mkdir(parents=True)
    (user_dir / "eval-correctness" / "SKILL.md").write_text("old\n", encoding="utf-8")

    installed = install_skills(builtin_dir=builtin_dir, user_dir=user_dir, force=True)

    assert set(installed) == {"eval-correctness", "eval-quality"}
    assert (user_dir / "eval-correctness" / "SKILL.md").read_text(encoding="utf-8") == "new\n"


def test_eval_runner_ensure_evaluator_skills_forces_project_install() -> None:
    runner = EvalRunner.__new__(EvalRunner)

    with patch("evals.validator.install_skills.install_skills") as install_mock:
        runner._ensure_evaluator_skills()

    install_mock.assert_called_once_with(force=True)


def test_eval_runner_init_calls_skill_install_helper(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    with patch.object(EvalRunner, "_load_config", return_value={}), patch.object(
        EvalRunner,
        "_ensure_evaluator_skills",
    ) as ensure_mock:
        EvalRunner(config_path=config_path)

    ensure_mock.assert_called_once()
