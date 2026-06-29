"""Local eval metrics: precision/recall/F1 and Wilson-score pass-rate CIs."""

from __future__ import annotations

import math
from dataclasses import dataclass


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


@dataclass(frozen=True)
class ConfidenceInterval:
    point: float
    low: float
    high: float


def wilson_interval(successes: int, n: int, z: float = 1.96) -> ConfidenceInterval:
    if n == 0:
        return ConfidenceInterval(0.0, 0.0, 1.0)
    phat = successes / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return ConfidenceInterval(phat, max(0.0, center - margin), min(1.0, center + margin))


def pass_rate(labels: list[str]) -> ConfidenceInterval:
    successes = sum(1 for label in labels if label == "pass")
    return wilson_interval(successes=successes, n=len(labels))
