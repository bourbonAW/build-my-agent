"""Tests for the submit_evaluation tool."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def test_handle_submit_stores_result():
    """submit_evaluation handler stores result in module state."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    clear_result()
    output = handle_submit(
        score=8.5,
        reasoning="Good implementation",
        evidence=["file.py:10 correct output"],
    )
    result = get_result()
    assert result["score"] == 8.5
    assert result["reasoning"] == "Good implementation"
    assert result["evidence"] == ["file.py:10 correct output"]
    assert "已提交" in output or "submitted" in output.lower()


def test_clear_result_resets_state():
    """clear_result empties the stored evaluation."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    handle_submit(score=5.0, reasoning="test", evidence=[])
    clear_result()
    assert get_result() == {}


def test_handle_submit_with_optional_fields():
    """submit_evaluation accepts optional suggestions and breakdown."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    clear_result()
    handle_submit(
        score=7.0,
        reasoning="Decent",
        evidence=["passes tests"],
        suggestions=["add docstrings"],
        breakdown={"naming": 8, "structure": 6},
    )
    result = get_result()
    assert result["suggestions"] == ["add docstrings"]
    assert result["breakdown"] == {"naming": 8, "structure": 6}


def test_get_result_returns_deep_copy():
    """get_result returns a deep copy, not a reference to internal state."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    clear_result()
    handle_submit(score=9.0, reasoning="great", evidence=["a", "b"])
    r1 = get_result()
    r1["score"] = 0.0
    r1["evidence"].append("injected")
    r2 = get_result()
    assert r2["score"] == 9.0
    assert r2["evidence"] == ["a", "b"]


def test_handle_submit_rejects_invalid_score():
    """submit_evaluation rejects scores outside 0-10 range."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    clear_result()
    output = handle_submit(score=15.0, reasoning="too high", evidence=[])
    assert "Error" in output
    assert get_result() == {}

    output = handle_submit(score=-1.0, reasoning="negative", evidence=[])
    assert "Error" in output
    assert get_result() == {}


def test_tool_registered_in_registry():
    """submit_evaluation tool is registered in the global ToolRegistry."""
    import evals.validator.submit_tool  # noqa: F401 — triggers registration
    from bourbon.tools import get_registry

    tool = get_registry().get("submit_evaluation")
    assert tool is not None
    assert tool.name == "submit_evaluation"
