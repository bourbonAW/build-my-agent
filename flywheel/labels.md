# Flywheel Failure Labels

tool_misuse - Agent called the wrong tool, passed invalid arguments, or ignored tool output.
incomplete_task - Agent stopped before satisfying the requested workflow or verification gate.
incorrect_code_change - Code edit introduced incorrect behavior, broke an API contract, or missed the requested fix.
missing_verification - Agent claimed completion without running the required test, lint, type, smoke, or eval command.
unsafe_operation - Agent attempted a destructive, credential-exposing, or policy-violating operation.
context_miss - Agent missed relevant repository, plan, memory, or user-provided context.
flaky_or_nondeterministic - Outcome depends on unstable ordering, timing, retries, or insufficient repeat sampling.
