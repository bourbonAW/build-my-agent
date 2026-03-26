"""Validation report models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    def from_dict(cls, data: dict) -> "ValidationDimension":
        return cls(**data)


@dataclass
class ValidationReport:
    """Aggregated validator report."""

    dimensions: list[ValidationDimension] = field(default_factory=list)
    overall_threshold: float = 8.0
    summary: str = ""

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
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "overall_score": self.overall_score,
            "overall_threshold": self.overall_threshold,
            "passed": self.passed,
            "summary": self.summary,
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ValidationReport":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            dimensions=[ValidationDimension.from_dict(item) for item in data["dimensions"]],
            overall_threshold=data["overall_threshold"],
            summary=data.get("summary", ""),
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
