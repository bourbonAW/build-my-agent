# Bourbon

Bourbon is a general-purpose AI agent platform for software engineering and knowledge work: tools, skills, persistent tasks, memory, subagents, MCP, and sandboxed execution.

[![Bun](https://img.shields.io/badge/Bun-1.4+-black?logo=bun)](https://bun.sh)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Status: TypeScript migration.** The active implementation is being rebuilt in TypeScript under `ts/` on the `feat/ts-rewrite` branch. The Python implementation on `master` is legacy: it receives no new features and will be retired when the migration lands. `flywheel/` and `evals/` are the remaining Python tooling pending migration.

## Highlights

- **Terminal agent** — REPL and one-shot `--print` mode, streaming Markdown with live redraw, and a fixed footer for context, tokens, model, and activity.
- **Providers** — Anthropic and OpenAI-compatible endpoints (`anthropic`, `openai`, `kimi`).
- **Tools** — files, search, Bash, web, CSV/JSON, PDF/DOCX, todos, persistent tasks, memory, and tool discovery.
- **Extensible** — Agent Skills, MCP servers (stdio/HTTP), and foreground/background/teammate subagents.
- **Sessions** — append-only JSONL transcripts, resume, microcompaction, and automatic full compaction.
- **Memory** — file-first immutable records with cues, a rebuildable `MEMORY.md`, and SQLite FTS with optional embeddings.
- **Security** — capability inference, permission prompts, sandbox providers, and JSONL audit.
- **Observability** — OpenTelemetry spans for agent steps, chats, and tool calls.

## Try the TypeScript build

Active code lives on `feat/ts-rewrite` (not yet merged into `master`). Requires Bun 1.4+.

```bash
git checkout feat/ts-rewrite
cd ts
bun install
bun run src/index.ts --init    # create ~/.bourbon/config.toml
bun run start                  # interactive REPL
```

One-shot and resume:

```bash
bun run src/index.ts -p "Explain this repo" -w /path/to/work
bun run src/index.ts --resume-last
```

Provider keys live in `~/.bourbon/config.toml`; there is no `.env` loading. See `AGENTS.md` on `feat/ts-rewrite` for the full configuration reference.

## Repository layout

| Path | Status |
|------|--------|
| `ts/` | Active TypeScript implementation (`feat/ts-rewrite`) |
| `src/bourbon/` | Legacy Python implementation (`master`) |
| `tests/`, `docs/` | Legacy Python tests and design notes |
| `flywheel/`, `evals/` | Python tooling pending migration |

## Development

TypeScript, on `feat/ts-rewrite`:

```bash
cd ts
bun run typecheck
bun test
```

Python on this branch is legacy. It still runs with:

```bash
uv pip install -e ".[dev]"
python -m bourbon
```

## Documentation

- `AGENTS.md` on `feat/ts-rewrite` — TypeScript architecture, commands, and testing.
- `docs/` — design notes and implementation plans.
- `EVAL_GUIDE.md` — legacy Python evaluation guide, pending migration.

## License

MIT
