"""Validation report models."""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class ValidationDimension:
    """One evaluated validation dimension."""

    name: str
    score: float
    weight: float
    threshold: float
    passed: bool | None = None
    skill: str | None = None
    breakdown: dict = field(default_factory=dict)
    reasoning: str = ""
    evidence: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.passed is None:
            self.passed = self.score >= self.threshold

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "weight": self.weight,
            "threshold": self.threshold,
            "passed": self.passed,
            "skill": self.skill,
            "breakdown": self.breakdown,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "suggestions": self.suggestions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ValidationDimension:
        return cls(**data)


@dataclass
class ValidationReport:
    """Aggregated validator report."""

    dimensions: list[ValidationDimension] = field(default_factory=list)
    overall_threshold: float = 8.0
    summary: str = ""
    version: str = "1.0"
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    evaluator_focus: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    telemetry: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evaluator_focus:
            self.evaluator_focus = [dimension.name for dimension in self.dimensions]
        if not self.skills_used:
            self.skills_used = [
                dimension.skill for dimension in self.dimensions if dimension.skill
            ]
        self._normalize_weights_if_needed()
        if not self.telemetry:
            self.telemetry = {
                "focus_dimensions": list(self.evaluator_focus),
                "skills_invoked": list(self.skills_used),
            }

    @property
    def overall_score(self) -> float:
        total_weight = sum(d.weight for d in self.dimensions)
        if not total_weight:
            return 0.0
        return round(sum(d.score * d.weight for d in self.dimensions) / total_weight, 2)

    @property
    def passed(self) -> bool:
        return self.overall_score >= self.overall_threshold

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "evaluator_focus": self.evaluator_focus,
            "skills_used": self.skills_used,
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "overall_score": self.overall_score,
            "overall_threshold": self.overall_threshold,
            "passed": self.passed,
            "summary": self.summary,
            "telemetry": self.telemetry,
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ValidationReport:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            dimensions=[ValidationDimension.from_dict(item) for item in data["dimensions"]],
            overall_threshold=data["overall_threshold"],
            summary=data.get("summary", ""),
            version=data.get("version", "1.0"),
            timestamp=data.get(
                "timestamp",
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
            evaluator_focus=data.get("evaluator_focus", []),
            skills_used=data.get("skills_used", []),
            telemetry=data.get("telemetry", {}),
        )

    def to_assertions(self) -> list[dict]:
        assertions = [
            {
                "id": f"eval_{dimension.name}",
                "text": f"{dimension.name} validation",
                "passed": dimension.passed,
                "evidence": dimension.reasoning,
            }
            for dimension in self.dimensions
        ]
        assertions.append(
            {
                "id": "eval_overall",
                "text": "overall validation",
                "passed": self.passed,
                "evidence": self.summary,
            }
        )
        return assertions

    def _normalize_weights_if_needed(self) -> None:
        total_weight = sum(dimension.weight for dimension in self.dimensions)
        if not self.dimensions or total_weight <= 0:
            return
        if abs(total_weight - 1.0) <= 1e-9:
            return

        warnings.warn(
            (
                f"Validation dimension weights summed to {total_weight:.3f}; "
                "normalized to 1.0."
            ),
            UserWarning,
            stacklevel=2,
        )
        for dimension in self.dimensions:
            dimension.weight = dimension.weight / total_weight
