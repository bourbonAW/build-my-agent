# Task V2 Usage Guide

Task tracking in Bourbon now has three separate layers:

- `TodoWrite` is the legacy in-memory checklist for the current agent only.
- `TaskCreate`, `TaskUpdate`, `TaskList`, and `TaskGet` are the persistent workflow task tools.
- The subagent registry tracks runtime jobs, not workflow tasks.

## When to Use Todos vs Tasks

Use `TodoWrite` when the agent needs a short-lived checklist to manage the current conversation or execution loop. It is best for single-agent scratch planning, temporary progress tracking, and fast updates that do not need to survive a restart.

Use `TaskCreate` and the rest of the Task V2 tool family when the work itself matters outside the current in-memory session. Workflow tasks are the right layer for durable planning, task ownership, dependency tracking, and any work that should still exist when a fresh agent instance comes back later.

## How Persistence Works

`TodoWrite` state lives only in the active agent's `TodoManager`. It is not written to disk, and a new agent starts with an empty todo list. If every todo item is completed, the list clears back to `No todos.`

Task V2 is file-backed. `TaskCreate` writes a task record to the configured task storage directory, and `TaskList` / `TaskGet` read the same persistent records back. A fresh agent using the same task storage and the same workflow task list can still see the previously created workflow tasks. By default that list is scoped from the session ID, but callers can also set an explicit `taskListId`.

## Ownership and Dependencies

Workflow tasks have explicit ownership and dependency fields because they model durable work, not transient runtime state.

- `owner` identifies who currently owns the workflow task.
- `blocks` lists workflow tasks that this task prevents from advancing.
- `blockedBy` lists workflow tasks that must finish first.

These fields belong on persistent workflow tasks because they survive process boundaries and let multiple sessions reason about the same work backlog.

## Why Runtime Jobs Are Not Workflow Tasks

Runtime jobs are execution records for background or subagent work. They answer questions like whether a run is pending, running, completed, failed, or stopped, and where to inspect output. They do not replace workflow planning state.

In other words, runtime jobs are not workflow tasks. Completing a workflow task must not clear runtime checklist state, and finishing a runtime job does not mean the workflow backlog is complete.

Because of that boundary:

- `/todos` is for the legacy in-memory checklist.
- `/tasks` and `/task` are for persistent workflow task management.
- Runtime-job commands should use the reserved set `/runs`, `/run-show`, and `/run-stop` instead of `/task-*`.
