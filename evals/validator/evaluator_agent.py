"""Evaluator subprocess entrypoints."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from evals.validator.artifact import OutputArtifact
from evals.validator.report import ValidationDimension, ValidationReport


@dataclass
class EvaluatorConfig:
    """Configuration for the evaluator subprocess."""

    artifact_dir: Path
    focus: list[str]
    threshold: float
    timeout: int
    dimensions_config: dict = field(default_factory=dict)
    dimension_to_skill: dict[str, str] = field(default_factory=dict)


class EvaluatorAgentRunner:
    """Launch the evaluator subprocess."""

    def __init__(
        self,
        artifact_dir: Path,
        focus: list[str],
        threshold: float = 8.0,
        timeout: int = 60,
        dimensions_config: dict | None = None,
        dimension_to_skill: dict | None = None,
    ):
        self.artifact_dir = artifact_dir
        self.focus = focus
        self.threshold = threshold
        self.timeout = timeout
        self.dimensions_config = dimensions_config or {}
        self.dimension_to_skill = dimension_to_skill or {}

    def run(self) -> Path:
        repo_root = Path(__file__).resolve().parents[2]
        config_path = self.artifact_dir.parent / "evaluator_config.json"
        config_path.write_text(
            json.dumps(
                {
                    "dimensions": self.dimensions_config,
                    "dimension_to_skill": self.dimension_to_skill,
                }
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "evals.validator.evaluator_agent",
                "--artifact-dir",
                str(self.artifact_dir),
                "--focus",
                json.dumps(self.focus),
                "--threshold",
                str(self.threshold),
                "--config",
                str(config_path),
            ],
            timeout=self.timeout,
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "evaluator subprocess failed")

        report_path = self.artifact_dir.parent / "validation" / "report.json"
        if not report_path.exists():
            raise RuntimeError(f"validation report not found: {report_path}")
        return report_path


# ---------------------------------------------------------------------------
# Phase 2: Real LLM-based evaluation
# ---------------------------------------------------------------------------

EVALUATOR_SYSTEM_PROMPT = """\
You are a code review agent. Your task is to evaluate the output of another AI agent.

## How To Work

1. You will receive an evaluation task specifying a dimension and a corresponding skill.
2. Call the specified skill to load evaluation criteria and guidelines.
3. Use Read, Glob, and Grep tools to analyze files in the workspace/ directory.
4. Read context.json for the original task prompt and success criteria.
5. Read output.json for the agent's final response.
6. After analysis, call submit_evaluation to submit your structured result.

## Rules

- You are a reviewer, not a developer. Do NOT modify any files.
- Score range is 0-10, based on criteria defined in the skill.
- Evidence must reference specific file paths, line numbers, or behavioral observations.
- Evaluate one dimension at a time.
- You MUST call submit_evaluation after completing your analysis.

## Artifact Layout

Your working directory contains:
- context.json — task prompt and success criteria
- output.json — the agent's final output
- meta.json — execution metadata (duration, tokens)
- workspace/ — file snapshot after agent execution
"""


def build_evaluation_prompt(dimension_name: str, skill_name: str) -> str:
    """Build the user message for a single dimension evaluation."""
    return f"""\
Evaluate dimension: {dimension_name}

Steps:
1. Call skill("{skill_name}") to load the evaluation criteria
2. Read these files for task context:
   - context.json
   - output.json
   - meta.json
3. Use Read, Glob, Grep to analyze code in workspace/
4. Call submit_evaluation to submit your assessment
"""


def create_evaluator_agent(artifact_dir: Path, system_prompt: str):
    """Create a Bourbon Agent configured for evaluation."""
    from bourbon.agent import Agent
    from bourbon.config import ConfigManager

    config = ConfigManager().load_config()
    config.ui.max_tool_rounds = 15

    return Agent(
        config=config,
        workdir=artifact_dir,
        system_prompt=system_prompt,
    )


def run_evaluator_agent(config: EvaluatorConfig) -> ValidationReport:
    """Run LLM-based evaluation for each dimension."""
    # Import triggers submit_evaluation tool registration in this subprocess
    from evals.validator.submit_tool import clear_result, get_result

    started_at = time.time()
    OutputArtifact.load(config.artifact_dir)

    agent = create_evaluator_agent(
        artifact_dir=config.artifact_dir,
        system_prompt=EVALUATOR_SYSTEM_PROMPT,
    )

    dimensions: list[ValidationDimension] = []
    for dimension_name in config.focus:
        dim_config = config.dimensions_config.get(dimension_name, {})
        threshold = dim_config.get("threshold", config.threshold)
        weight = dim_config.get("weight", 1.0 / len(config.focus))
        skill_name = config.dimension_to_skill.get(dimension_name, "")

        prompt = build_evaluation_prompt(dimension_name, skill_name)

        # Reset state between dimensions
        clear_result()
        agent.messages.clear()

        try:
            agent.step(prompt)
        except Exception as e:
            dimensions.append(
                ValidationDimension(
                    name=dimension_name,
                    score=0.0,
                    weight=weight,
                    threshold=threshold,
                    skill=skill_name,
                    reasoning=f"evaluation error: {e}",
                    evidence=[],
                    suggestions=[],
                )
            )
            continue

        result = get_result()
        dimensions.append(
            ValidationDimension(
                name=dimension_name,
                score=result.get("score", 0.0),
                weight=weight,
                threshold=threshold,
                skill=skill_name,
                reasoning=result.get("reasoning", "no evaluation submitted"),
                evidence=result.get("evidence", []),
                suggestions=result.get("suggestions", []),
                breakdown=result.get("breakdown", {}),
            )
        )

    report = ValidationReport(
        dimensions=dimensions,
        overall_threshold=config.threshold,
        summary="phase 2 LLM-based validation",
        evaluator_focus=list(config.focus),
        skills_used=[dimension.skill for dimension in dimensions if dimension.skill],
        telemetry={
            "focus_dimensions": list(config.focus),
            "skills_invoked": [dimension.skill for dimension in dimensions if dimension.skill],
            "duration_ms": int((time.time() - started_at) * 1000),
            "token_usage": agent.get_token_usage(),
        },
    )
    report_path = config.artifact_dir.parent / "validation" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.save(report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evaluator agent")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--focus", required=True)
    parser.add_argument("--threshold", type=float, default=8.0)
    parser.add_argument("--config")
    args = parser.parse_args()

    dimensions_config = {}
    dimension_to_skill = {}
    if args.config:
        config_data = json.loads(Path(args.config).read_text(encoding="utf-8"))
        dimensions_config = config_data.get("dimensions", {})
        dimension_to_skill = config_data.get("dimension_to_skill", {})

    run_evaluator_agent(
        EvaluatorConfig(
            artifact_dir=Path(args.artifact_dir),
            focus=json.loads(args.focus),
            threshold=args.threshold,
            timeout=300,
            dimensions_config=dimensions_config,
            dimension_to_skill=dimension_to_skill,
        )
    )


if __name__ == "__main__":
    main()
