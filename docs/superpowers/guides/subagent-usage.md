# Subagent Usage Guide

Subagents let a Bourbon agent delegate focused work to a child agent without mixing that child execution state into the parent conversation checklist or workflow task backlog.

## When to Use a Subagent

Use the `Agent` tool when work is bounded enough to hand off with a clear prompt and you want an isolated result back.

Good fits:

- Code exploration where the parent only needs a summary.
- Focused implementation or refactoring in a limited area.
- Background investigation while the parent continues other work.
- Planning or architecture review that should not inherit parent chat history.

Do not use a subagent as a durable project backlog because runtime jobs are not workflow tasks. Use `TaskCreate`, `TaskUpdate`, `TaskList`, and `TaskGet` for persistent workflow planning, and use `/tasks` to inspect that workflow task list.

## Agent Tool Parameters

The `Agent` tool accepts these primary fields:

- `description`: short label for the runtime job.
- `prompt`: complete instruction sent to the child agent.
- `subagent_type`: profile to use. Defaults to `default`.
- `run_in_background`: when `true`, return a `run_id` immediately instead of waiting for completion.
- `model`: optional model override for the child agent.
- `max_turns`: optional cap on child agent tool rounds.

Example foreground call:

```json
{
  "description": "Inspect parser tests",
  "prompt": "Read the parser tests and summarize missing edge cases.",
  "subagent_type": "explore"
}
```

Foreground execution blocks until the child agent finishes and returns the final result in the tool output.

Example background call:

```json
{
  "description": "Refactor auth helpers",
  "prompt": "Refactor the auth helper module and report changed files.",
  "subagent_type": "coder",
  "run_in_background": true
}
```

Background execution returns a `run_id` immediately. Use the runtime commands below to inspect or stop the job.

## Subagent Types

`default` is the general-purpose profile for most bounded tasks.

`coder` is intended for implementation and refactoring. It allows normal non-recursive tools and uses a higher turn cap.

`explore` is read-only codebase exploration. It is restricted to read/search/web-style tools when those tools are registered.

`plan` is read-only planning and architecture analysis. It has the same read-focused tool surface as `explore` with planning-oriented instructions.

`quick_task` is for short, simple jobs with a lower turn cap.

All subagent profiles block recursive subagents and parent checklist mutation. The hidden tools include `Agent`, `TodoWrite`, and `compress`, and the same deny check is enforced again if a hidden tool is somehow requested at execution time.

## Runtime Commands

Use these REPL commands for subagent runtime jobs:

- `/runs`: list known runtime jobs in the current process.
- `/run-show <run_id>`: show the current output, error, or status for one runtime job.
- `/run-stop <run_id>`: request cancellation for a running runtime job.

The runtime command surface is intentionally separate from workflow task commands. `/todos` is for the current agent's short-lived checklist, `/tasks` is for persistent workflow tasks, and `/runs` is for subagent runtime jobs.

## Practical Guidance

Write prompts as if the child agent has no parent conversation history. Include file paths, success criteria, and output expectations directly in `prompt`.

Prefer `explore` for read-only discovery before asking a `coder` subagent to edit. This keeps tool permissions aligned with intent and reduces accidental file changes.

Use background mode only when the parent can do useful independent work. If the parent needs the result before proceeding, use foreground mode.
