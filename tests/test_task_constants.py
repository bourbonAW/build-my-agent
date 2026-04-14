# tests/test_task_constants.py
from bourbon.tasks.constants import TASK_V2_TOOLS


def test_task_v2_tools_contains_expected_names():
    assert TASK_V2_TOOLS == {"TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}


def test_task_v2_tools_is_a_set():
    assert isinstance(TASK_V2_TOOLS, set)
