"""Validator package for eval generator/evaluator handoff."""

from .artifact import ArtifactBuilder, OutputArtifact
from .report import ValidationDimension, ValidationReport

__all__ = [
    "ArtifactBuilder",
    "OutputArtifact",
    "ValidationDimension",
    "ValidationReport",
]
