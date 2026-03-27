"""Validator package for eval generator/evaluator handoff."""

from .artifact import ArtifactBuilder, OutputArtifact
from .evaluator_agent import (
    EVALUATOR_SYSTEM_PROMPT,
    EvaluatorAgentRunner,
    EvaluatorConfig,
    build_evaluation_prompt,
    create_evaluator_agent,
    run_evaluator_agent,
)
from .report import ValidationDimension, ValidationReport

# NOTE: submit_tool is intentionally NOT imported here.
# It registers submit_evaluation in the global ToolRegistry at import time,
# which must only happen inside the evaluator subprocess, not the main process.
# It is imported inside run_evaluator_agent() instead.

__all__ = [
    "ArtifactBuilder",
    "EVALUATOR_SYSTEM_PROMPT",
    "EvaluatorAgentRunner",
    "EvaluatorConfig",
    "OutputArtifact",
    "ValidationDimension",
    "ValidationReport",
    "build_evaluation_prompt",
    "create_evaluator_agent",
    "run_evaluator_agent",
]
