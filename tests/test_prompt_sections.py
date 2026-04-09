import asyncio
from pathlib import Path

from bourbon.prompt.types import PromptContext


CTX = PromptContext(workdir=Path("/home/user/myproject"))


def run(coro):
    return asyncio.run(coro)


def test_default_sections_has_four_entries():
    from bourbon.prompt.sections import DEFAULT_SECTIONS

    assert len(DEFAULT_SECTIONS) == 4


def test_identity_is_dynamic():
    from bourbon.prompt.sections import IDENTITY

    assert not IDENTITY.is_static


def test_task_guidelines_is_static():
    from bourbon.prompt.sections import TASK_GUIDELINES

    assert TASK_GUIDELINES.is_static


def test_error_handling_is_static():
    from bourbon.prompt.sections import ERROR_HANDLING

    assert ERROR_HANDLING.is_static


def test_task_adaptability_is_static():
    from bourbon.prompt.sections import TASK_ADAPTABILITY

    assert TASK_ADAPTABILITY.is_static


def test_identity_contains_workdir():
    from bourbon.prompt.sections import IDENTITY

    result = run(IDENTITY.content(CTX))
    assert str(CTX.workdir) in result
    assert "Bourbon" in result


def test_task_guidelines_contains_todo():
    from bourbon.prompt.sections import TASK_GUIDELINES

    assert "TodoWrite" in TASK_GUIDELINES.content


def test_error_handling_contains_risk_levels():
    from bourbon.prompt.sections import ERROR_HANDLING

    assert "HIGH RISK" in ERROR_HANDLING.content
    assert "LOW RISK" in ERROR_HANDLING.content
    assert "MEDIUM RISK" in ERROR_HANDLING.content
    assert "CRITICAL ERROR HANDLING RULES" in ERROR_HANDLING.content


def test_sections_ordered_correctly():
    from bourbon.prompt.sections import (
        DEFAULT_SECTIONS,
        ERROR_HANDLING,
        IDENTITY,
        TASK_ADAPTABILITY,
        TASK_GUIDELINES,
    )

    orders = [section.order for section in DEFAULT_SECTIONS]
    assert orders == sorted(orders)
    assert IDENTITY.order == 10
    assert TASK_GUIDELINES.order == 20
    assert ERROR_HANDLING.order == 30
    assert TASK_ADAPTABILITY.order == 40
