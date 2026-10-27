# AGENTS.md

Development guide for AI agents working on Bourbon.

## Project Vision

Bourbon is a general-purpose agent platform with a code-first evolution:
- **Stage A (Completed)**: Code search, refactoring, analysis.
- **Stage B (Current)**: General knowledge work, skills, sandboxing, subagents, persistent tasks, observability.
- **Stage C**: Autonomous workflows across domains.

The primary implementation is TypeScript in `ts/`, running on Bun. The legacy Python implementation was removed; `flywheel/` and `evals/` remain separate Python tooling that still needs migration.

## Commands

```bash
cd ts
bun install
bun run start                       # interactive REPL
bun run start -- -w /path/to/work   # explicit workspace
bun run src/index.ts -p "prompt" -w /path/to/work
bun run src/index.ts --init         # create ~/.bourbon/config.toml
bun run src/index.ts --resume-last
bun run typecheck
bun test
```

Use Bun 1.4+. Node/npm are not required at runtime.

## Structure

```
ts/
├── src/
│   ├── index.ts                 # CLI entry (--init/--print/--session-id/--resume-last)
│   ├── cli.ts                   # REPL, slash commands, permissions, history
│   ├── markdown.ts              # ANSI Markdown renderer + live-redraw stream
│   ├── status.ts                # fixed bottom status footer (context/model/activity)
│   ├── render.ts                # spinner, tool lines, usage/context lines
│   ├── config.ts                # ~/.bourbon/config.toml loader + defaults
│   ├── llm.ts                   # Anthropic + OpenAI-compatible streaming clients
│   ├── agent/agent.ts           # conversation loop, tool execution, permissions, subagents
│   ├── session/                 # chain, JSONL transcript, context/compact, resume
│   ├── prompt/                  # ordered sections, env injection, skills/MCP catalogs
│   ├── tools/                   # tool registry and built-in tools
│   ├── skills.ts                # Agent Skills discovery/activation
│   ├── tasks/                   # persistent task store/service/locking
│   ├── todos.ts                 # in-memory todo list
│   ├── memory/                  # immutable records, cues, SQLite FTS + optional vectors
│   ├── permissions/             # matching, runtime requests, presentation
│   ├── access_control/          # capability inference + policy engine
│   ├── sandbox/                 # manager, credentials, local/seatbelt/bwrap/docker
│   ├── audit/                   # JSONL audit events
│   ├── mcp/                     # stdio + streamable HTTP MCP client
│   ├── subagent/                # foreground/background/teammate runtime
│   └── observability/           # OpenTelemetry tracer/manager
└── tests/                       # bun:test unit + end-to-end tests
```

## Configuration

Config lives at `~/.bourbon/config.toml`, outside the repo. Keys:
`[llm]`, `[llm.anthropic]`, `[llm.openai]`, `[tools.*]`, `[ui]`, `[tasks]`, `[memory]`, `[observability]`, `[mcp]`, `[access_control]`, `[sandbox]`, `[audit]`.
`default_provider` accepts `anthropic`, `openai`, or `kimi` (kimi uses the OpenAI-compatible section).

## Agent Loop

- `Agent.run(userInput)` enriches input with a `<system-reminder>` environment block, persists it, microcompacts, auto-compacts if needed, then loops.
- Each round streams the LLM response, persists assistant content, and executes tool calls.
- Consecutive concurrency-safe tools run in parallel with `Promise.all`; serial tools run in order.
- Tool results are appended as one user message; results are capped at 50k chars.
- A tool failing 3 consecutive times is temporarily blocked.
- After `ui.max_tool_rounds`, one final text-only LLM call produces a summary.
- Pending tasks trigger a `<task_reminder>` after 10 rounds without Task V2 tools.
- Permission requests suspend the current tool round and resume via `Agent.resumePermission(choice)`.

## Terminal Rendering

Assistant text is rendered as Markdown while streaming. `markdown.ts` handles headings, emphasis, inline code, lists/task boxes, tables, blockquotes, links, horizontal rules, and fenced code with lightweight syntax highlighting, wrapping everything to the terminal width. The live stream redraws only the unfinished tail so completed blocks stay committed and long answers do not flicker.

The REPL reserves the bottom two rows for a fixed status footer (`status.ts`): cwd and git branch with the current activity on the first line, cumulative input/output tokens and context usage on the left of the second line, and the model name on the right. Context turns yellow at 50% and red at 80% of `ui.token_threshold`. A terminal scroll region keeps the transcript scrolling above while the footer stays put; footer updates use saved-cursor redraws, and are restored after readline refreshes. While a non-empty line is being edited, a terminal resize detaches the footer and reattaches it at the next prompt, since readline owns that line.

`BOURBON_PLAIN=1` restores raw streaming and disables the footer; non-TTY output and piped `--print` stay plain.

## Tools

Every tool implements `Tool` in `ts/src/tools/types.ts`: name, description, JSON schema, risk level, optional aliases/deferred loading/capabilities, and `run(input, ctx)`.

Built-in tools: Bash, Read, Write, Edit, Grep, Glob, AstGrep, WebFetch, CsvAnalyze, JsonQuery, PdfRead, DocxRead, TodoWrite, TaskCreate/TaskUpdate/TaskList/TaskGet, Skill, SkillResource, memory_search/write/delete/status, ToolSearch, Agent/AgentWait.

To add a tool:
1. Implement it in the appropriate `ts/src/tools/*.ts` module.
2. Give it metadata (`riskLevel`, `requiredCapabilities`, `isReadOnly`, `isConcurrencySafe`, `alwaysLoad`/`shouldDefer`).
3. Register it in `createToolRegistry()` in `ts/src/tools/index.ts`.
4. Add a test under `ts/tests/`.

## Sessions and Compaction

- Transcripts are append-only JSONL under `~/.bourbon/sessions/{project}/{session}.jsonl`.
- Metadata: `{session}.meta.json`; compact overrides: `{session}.compact.json`.
- `MessageChain` rebuilds the active chain from `parent_uuid` only.
- `ContextManager` tracks actual provider input tokens, microcompacts old tool results, and triggers full compact over `ui.token_threshold`.
- Resume with `--session-id` or `--resume-last`.

## Prompt and Anchors

Ordered sections: identity, memory anchors, task guidelines, subagent guidelines, error handling, tool-result trust, task adaptability, skills catalog, MCP catalog.

Anchors are only injected when memory is enabled:
- `AGENTS.md` from the workdir (8000-token cap)
- merged global `~/.bourbon/USER.md` + project `USER.md` (600-token cap)
- `MEMORY.md` from the project memory directory (1200-token cap)

## Memory

Immutable Markdown records with YAML frontmatter: `id`, `target` (`user`|`project`), `created_at`, `cues`.

- `MEMORY.md` is a rebuildable index (max 200 lines).
- `search_index.sqlite` is a rebuildable derived index: SQLite FTS5 plus dense vectors.
- Semantic embeddings are optional and require `@huggingface/transformers` (or another provider implementing `EmbeddingProvider`). Without it, search falls back to content/cue/FTS matching.
- Subagents may only write `project` memories and cannot delete.
- Writes require an audit logger.

## Skills

Agent Skills compatible. Discovery order (project overrides user): `.agents/skills`, `.bourbon/skills`, `.kimi/skills`, `.claude/skills`, then user-level equivalents.
Catalog is injected into the prompt; `Skill` loads full instructions; `SkillResource` reads bundled files. `/skill/name` activates in the REPL.

## Tasks and Todos

- Todo V1 is in-memory (`TodoWrite`).
- Task V2 is file-backed under `~/.bourbon/tasks/{list}/{id}.json` with a high-watermark id and file lock.
- Supports owner, `blocks`/`blockedBy`, active-blocker filtering, and peer cleanup on delete.
- Subagent tool visibility: async runs hide Task V2 tools; teammates may use them.

## Security

Execution flow for each tool call: subagent filter → capability inference → policy engine → permission decision → sandbox (destructive Bash only) → tool handler → audit.

- File policy: allow/deny/mandatory-deny globs; workdir-scoped.
- Command policy: deny substrings/globs and approval patterns.
- Approvals: allow once, allow for session, reject.
- Sandbox providers: `local`, `seatbelt` (macOS), `bubblewrap` (Linux), `docker`, or `auto`. Destructive Bash runs through the sandbox when enabled.
- Credentials: sensitive env vars are stripped; an allowlisted HTTP credential proxy exists for Docker.
- Audit: JSONL under `~/.bourbon/audit/`.

## MCP

Configure `[[mcp.servers]]` with `transport = "stdio" | "http"`. Tools are registered as `{server}-{tool}` at MEDIUM risk. stdio `npx` packages must already be installed; the client never auto-downloads. Connection failures are reported but do not stop the REPL.

## Subagents

Profiles: `default`, `coder`, `explore`, `plan`, `quick_task`, `teammate`.
- `explore`/`plan` are restricted to Read/Glob/Grep/AstGrep/WebFetch.
- `Agent` blocks by default; `run_in_background=true` returns a run id and `AgentWait` joins it.
- Each subagent gets an isolated session under `{project}/subagents/`.
- `teammate` may use Task V2 tools and shares the parent task list.

## Observability

Set `[observability] enabled = true` and `otlp_endpoint` (or `OTEL_EXPORTER_OTLP_ENDPOINT`). Spans: `invoke_agent bourbon`, `chat {model}`, `execute_tool {name}`. Debug JSONL is enabled with `BOURBON_DEBUG=1` or `BOURBON_DEBUG_LOG=/path`; full prompts require `BOURBON_DEBUG_PROMPTS=1`.

## Error Handling Policy

- **HIGH risk** (installs, version changes, destructive/system commands): stop and ask; never auto-switch versions or parameters.
- **MEDIUM risk** (file writes/edits): report the failure and ask before alternatives.
- **LOW risk** (reads, search, exploration): may retry one genuinely different approach, then report.

## Testing

```bash
cd ts
bun run typecheck
bun test
```

Tests cover session/resume/compaction, prompt anchors, tools, memory (including a fake embedding provider), permissions/resume, sandbox providers, MCP stdio + HTTP, subagents, observability OTLP export, OpenAI-compatible streaming, Markdown rendering/live redraw, the status footer and scroll region, CLI print/init/slash commands, and real-model E2E against the configured endpoint.

## Product Principles

Follow Dieter Rams: less, but better. Prefer useful, understandable, honest, durable behavior over novelty. Every tool, prompt section, UI element, and dependency must earn its place. Empty states, errors, permissions, and edge cases matter.
