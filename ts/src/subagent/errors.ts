export type SubagentErrorCode =
  | "user_abort"
  | "max_turns_exceeded"
  | "llm_error"
  | "llm_retry_exhausted"
  | "tool_permission_denied"
  | "tool_not_found"
  | "session_error"
  | "unknown_error";

export class RunError extends Error {
  constructor(
    readonly code: SubagentErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "RunError";
  }
}

export class RunCancelledError extends RunError {
  constructor(message = "Run was cancelled") {
    super("user_abort", message);
    this.name = "RunCancelledError";
  }
}

export class MaxTurnsExceededError extends RunError {
  constructor(readonly maxTurns: number) {
    super("max_turns_exceeded", `Run exceeded maximum turns (${maxTurns})`);
    this.name = "MaxTurnsExceededError";
  }
}
