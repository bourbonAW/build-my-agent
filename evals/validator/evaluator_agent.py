"""Evaluator subprocess entrypoints."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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


def run_evaluator_agent(config: EvaluatorConfig) -> ValidationReport:
    """Generate a Phase 1 simulated validation report."""

    OutputArtifact.load(config.artifact_dir)
    dimensions = []
    for dimension_name in config.focus:
        dim_config = config.dimensions_config.get(dimension_name, {})
        threshold = dim_config.get("threshold", config.threshold)
        weight = dim_config.get("weight", 1.0 / len(config.focus))
        dimensions.append(
            ValidationDimension(
                name=dimension_name,
                score=8.5,
                weight=weight,
                threshold=threshold,
                skill=config.dimension_to_skill.get(dimension_name),
                reasoning="Phase 1 simulation",
                evidence=["artifact loaded"],
                suggestions=["replace simulation with real skill invocation"],
            )
        )

    report = ValidationReport(
        dimensions=dimensions,
        overall_threshold=config.threshold,
        summary="phase 1 simulated validation",
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
