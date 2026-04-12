from bourbon.subagent.errors import (
    MaxTurnsExceededError,
    RunCancelledError,
    RunError,
    SubagentErrorCode,
)


def test_error_code_values():
    assert SubagentErrorCode.USER_ABORT.value == "user_abort"
    assert SubagentErrorCode.MAX_TURNS_EXCEEDED.value == "max_turns_exceeded"
    assert SubagentErrorCode.LLM_ERROR.value == "llm_error"


def test_run_error_has_code():
    error = RunError(SubagentErrorCode.LLM_ERROR, "API failed")

    assert error.code == SubagentErrorCode.LLM_ERROR
    assert error.message == "API failed"
    assert str(error) == "API failed"


def test_run_cancelled_error_defaults_to_user_abort():
    error = RunCancelledError("User stopped run")

    assert error.code == SubagentErrorCode.USER_ABORT
    assert str(error) == "User stopped run"


def test_max_turns_exceeded_error_includes_limit():
    error = MaxTurnsExceededError(12)

    assert error.code == SubagentErrorCode.MAX_TURNS_EXCEEDED
    assert error.max_turns == 12
    assert str(error) == "Run exceeded maximum turns (12)"
