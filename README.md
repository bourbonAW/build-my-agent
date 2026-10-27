# Bourbon

Bourbon is a general-purpose AI agent platform for software engineering and knowledge work. It runs as a streaming terminal agent with tools, skills, persistent tasks, memory, subagents, MCP, and sandboxed execution.

[![Bun](https://img.shields.io/badge/Bun-1.4+-black?logo=bun)](https://bun.sh)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Status: TypeScript migration.** `ts/` is the active implementation. The original Python implementation is legacy and has been retired from the main tree; `flywheel/` and `evals/` are the remaining Python tooling pending migration.

## Highlights

- **Terminal agent** — REPL and one-shot `--print` mode, streaming Markdown with live redraw, and a fixed footer for context, tokens, model, and activity.
- **Providers** — Anthropic and OpenAI-compatible endpoints (`anthropic`, `openai`, `kimi`).
- **Tools** — files, search, Bash, web, CSV/JSON, PDF/DOCX, todos, persistent tasks, memory, and tool discovery.
- **Extensible** — Agent Skills, MCP servers (stdio/HTTP), and foreground/background/teammate subagents.
- **Sessions** — append-only JSONL transcripts, resume, microcompaction, and automatic full compaction.
- **Memory** — file-first immutable records with cues, a rebuildable `MEMORY.md`, and SQLite FTS with optional embeddings.
- **Security** — capability inference, permission prompts, sandbox providers, and JSONL audit.
- **Observability** — OpenTelemetry spans for agent steps, chats, and tool calls.

## Quick start

Requires Bun 1.4+.

```bash
cd ts
bun install
bun run src/index.ts --init    # create ~/.bourbon/config.toml
bun run start                  # interactive REPL
```

One-shot and resume:

```bash
bun run src/index.ts -p "Explain this repo" -w /path/to/work
bun run src/index.ts --resume-last
bun run src/index.ts --session-id <id>
```

Configure a provider in `~/.bourbon/config.toml` (no `.env` loading):

```toml
[llm]
default_provider = "anthropic"

[llm.anthropic]
api_key = "..."
model = "claude-sonnet-4-6"
```

Other sections: `[llm.openai]`, `[ui]`, `[tools.*]`, `[tasks]`, `[memory]`, `[mcp]`, `[access_control]`, `[sandbox]`, `[audit]`, `[observability]`. `kimi` uses the OpenAI-compatible section. See `AGENTS.md` for the full reference.

## How it works

```
ts/src/
├── index.ts / cli.ts   CLI, REPL, permissions, history
├── agent/              conversation loop, tool execution, subagents
├── llm.ts              Anthropic + OpenAI-compatible streaming
├── session/            JSONL transcript, message chain, compaction, resume
├── prompt/             ordered sections, environment/git injection, anchors
├── tools/              registry and built-in tools
├── skills.ts           Agent Skills discovery/activation
├── tasks/ + todos.ts   persistent tasks and in-memory todos
├── memory/             records, cues, FTS index, prompt anchors
├── permissions/        policy, matching, suspend/resume
├── access_control/     capability inference and policy engine
├── sandbox/            local, seatbelt, bubblewrap, and Docker providers
├── mcp/                stdio and streamable HTTP clients
├── subagent/           profiles, isolated sessions, background runs
├── observability/      OpenTelemetry tracer
├── markdown.ts         ANSI Markdown renderer and live-redraw stream
└── status.ts           fixed bottom status footer
```

- Sessions live under `~/.bourbon/sessions/{project}/`; configuration lives in `~/.bourbon/config.toml`.
- Every tool call passes through capability inference, policy, permissions, sandboxing (destructive Bash), and audit.
- Skills are discovered from `.agents/skills`, `.bourbon/skills`, `.kimi/skills`, and `.claude/skills` (project overrides user). MCP servers are configured with `[[mcp.servers]]` and `transport = "stdio" | "http"`.
- Prompt anchors: `AGENTS.md`, merged `~/.bourbon/USER.md` + project `USER.md`, and `MEMORY.md`.
- `BOURBON_PLAIN=1` disables the Markdown renderer and footer for plain streaming.

## Development

```bash
cd ts
bun run typecheck
bun test
```

Tests cover sessions and compaction, prompt anchors, tools, memory, permissions, sandbox providers, MCP, subagents, observability, Markdown/status rendering, and the CLI, plus real-model E2E against the configured endpoint.

Legacy Python:

- `flywheel/` and `evals/` still import the retired `bourbon` package and are the next migration target.
- `AGENTS.md` is the current development guide.

## Documentation

- `AGENTS.md` — architecture, commands, module map, security, and testing.
- `docs/` — design notes and implementation plans.

## License

MIT
