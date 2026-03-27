"""submit_evaluation tool — captures structured evaluation results from the evaluator LLM."""

from __future__ import annotations

import copy

from bourbon.tools import RiskLevel, Tool, get_registry

# Module-level result storage (per-process, safe in subprocess isolation)
_evaluation_result: dict = {}


def handle_submit(
    score: float,
    reasoning: str,
    evidence: list[str],
    suggestions: list[str] | None = None,
    breakdown: dict | None = None,
) -> str:
    """Handle submit_evaluation tool call from the evaluator LLM."""
    if not isinstance(score, (int, float)):
        return f"Error: score must be a number, got {type(score).__name__}. Please retry."
    if score < 0 or score > 10:
        return f"Error: score must be between 0 and 10, got {score}. Please retry."

    _evaluation_result.clear()
    _evaluation_result.update(
        {
            "score": float(score),
            "reasoning": reasoning,
            "evidence": evidence,
            "suggestions": suggestions or [],
            "breakdown": breakdown or {},
        }
    )
    return "评估已提交。无需进一步操作。"


def get_result() -> dict:
    """Return a deep copy of the current evaluation result."""
    return copy.deepcopy(_evaluation_result)


def clear_result() -> None:
    """Clear the stored evaluation result."""
    _evaluation_result.clear()


def _tool_handler(**kwargs) -> str:
    """Wrapper that unpacks tool_input kwargs for handle_submit."""
    return handle_submit(
        score=kwargs.get("score", 0.0),
        reasoning=kwargs.get("reasoning", ""),
        evidence=kwargs.get("evidence", []),
        suggestions=kwargs.get("suggestions"),
        breakdown=kwargs.get("breakdown"),
    )


# Register the tool at import time
_submit_tool = Tool(
    name="submit_evaluation",
    description=(
        "Submit your structured evaluation result. "
        "Call this after analyzing the artifact workspace."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "description": "Score from 0 to 10",
                "minimum": 0,
                "maximum": 10,
            },
            "reasoning": {
                "type": "string",
                "description": "Explanation of why this score was given",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Specific evidence supporting the score "
                    "(file paths, code snippets, observations)"
                ),
            },
            "suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Improvement suggestions",
            },
            "breakdown": {
                "type": "object",
                "description": "Optional sub-dimension scores",
            },
        },
        "required": ["score", "reasoning", "evidence"],
    },
    handler=_tool_handler,
    risk_level=RiskLevel.LOW,
    required_capabilities=[],
)
get_registry().register(_submit_tool)
