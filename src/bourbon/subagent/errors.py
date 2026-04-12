"""Error types for subagent runtime jobs."""

from enum import Enum


class SubagentErrorCode(Enum):
    """Standardized error codes for subagent failures."""

    USER_ABORT = "user_abort"
    MAX_TURNS_EXCEEDED = "max_turns_exceeded"
    LLM_ERROR = "llm_error"
    LLM_RETRY_EXHAUSTED = "llm_retry_exhausted"
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    TOOL_NOT_FOUND = "tool_not_found"
    SESSION_ERROR = "session_error"
    UNKNOWN_ERROR = "unknown_error"


class RunError(Exception):
    """Base exception for subagent runtime-job failures."""

    def __init__(self, code: SubagentErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class RunCancelledError(RunError):
    """Run was cancelled by the user or parent runtime."""

    def __init__(self, message: str = "Run was cancelled"):
        super().__init__(SubagentErrorCode.USER_ABORT, message)


class MaxTurnsExceededError(RunError):
    """Run exceeded its configured turn budget."""

    def __init__(self, max_turns: int):
        super().__init__(
            SubagentErrorCode.MAX_TURNS_EXCEEDED,
            f"Run exceeded maximum turns ({max_turns})",
        )
        self.max_turns = max_turns
