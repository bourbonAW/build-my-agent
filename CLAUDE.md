# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Think and search in English, respond in Chinese.

## Commands

```bash
# Install dependencies (base)
uv pip install -e ".[dev]"

# Install with Stage B dependencies (documents, web, data tools)
uv pip install -e ".[stage-b]"

# Install with local semantic memory (fastembed)
uv pip install -e ".[semantic]"

# Run agent
python -m bourbon

# Lint
ruff check src tests
ruff format src tests

# Type check
mypy src

# Run all tests
pytest

# Run a single test file
pytest tests/test_skills_new.py -v

# Run specific test
pytest tests/test_agent_error_policy.py::TestName -v

# Run MCP-specific tests
pytest tests/test_mcp_config.py tests/test_mcp_manager.py -v

# Run sandbox tests
pytest tests/test_sandbox_bwrap.py tests/test_sandbox_docker.py tests/test_sandbox_local.py tests/test_sandbox_seatbelt.py -v

# Run evaluations (via promptfoo)
npx promptfoo@latest eval
npx promptfoo@latest eval --filter-pattern "Skills"
npx promptfoo@latest eval --repeat 5
npx promptfoo@latest eval --no-cache
npx promptfoo@latest view
```

## Architecture

Bourbon is a general-purpose AI agent platform built around a synchronous conversation loop. The agent orchestrates LLM calls, tool execution, skill loading, sandbox isolation, MCP server connections, session persistence, memory, and observability.

### Core Flow

```
CLI (cli.py) -> REPL (repl.py) -> Agent.step() -> LLM.chat() -> _execute_tools() -> loop
```

`Agent.step()` in `src/bourbon/agent.py` is the main entry point. It delegates to `_run_conversation_loop()`, which repeatedly calls the LLM and executes tool calls until the LLM stops with a text response. The entire stack is **synchronous** — no asyncio; subprocess calls use `subprocess.run()` blocking mode.

### Session System (`src/bourbon/session/`)

Manages the full message lifecycle with crash safety and compaction.

- **`TranscriptMessage`** — core message type with `uuid`, `parent_uuid` (chain links), `session_id`, `role`, and frozen content blocks (`TextBlock`, `ToolUseBlock`, `ToolResultBlock`).
- **`MessageChain`** — in-memory linked list; `compact()` collapses history above the token threshold into a single boundary message.
- **`Session`** — wraps chain (in-memory) + `TranscriptStore` (JSONL file) + `ContextManager` (token tracking). `add_message()` appends to chain first, then persists — ordering guarantees crash safety.
- **`SessionManager`** — `create_session()`, `resume_session()`, `resume_latest()`, `delete_session()`. Resume rebuilds the chain from JSONL + a compact manifest (parent UUID overrides for chain links across compaction boundaries).

### Subagent System (`src/bourbon/subagent/`)

Spawns isolated sub-agent instances with type-based tool access control.

Six agent types with different tool access: `default`, `coder`, `explore` (read-only), `plan` (read-only), `quick_task` (time-limited), `teammate` (in-process parallel). `explore` and `plan` types are restricted to `READ_ONLY_TOOLS` at the manager level — no file writes or shell execution. `SubagentMode` enum (`NORMAL`, `TEAMMATE`, `ASYNC`) controls whether the caller waits.

### Task Management (`src/bourbon/tasks/`)

File-backed tracking of background/long-running tasks. `TaskService` persists `TaskCreate`/`TaskUpdate` records to disk. Used by `task_tools.py` to expose task CRUD to the agent. Not asyncio — agents poll `TaskService` for status.

### Prompt System (`src/bourbon/prompt/`)

Builds the system prompt from registered ordered sections.

- **`PromptBuilder`** — assembles sections sorted by `order` integer, joins with newlines.
- **Static sections** (`sections.py`) — identity (10), memory_anchors (15), task_guidelines (20), subagent_guidelines (25), error_handling (30), task_adaptability (40).
- **Dynamic sections** (`dynamic.py`) — skills catalog (60), MCP tools (70); generated async each step.
- The `memory_anchors` section (order 15) injects merged AGENTS.md + USER.md preferences and the MEMORY.md index with token budgets.

### Memory System (`src/bourbon/memory/`)

File-first immutable memory with optional local semantic indexing.

**Minimal model:** Each record has `id`, `target` (scoping string, e.g. `"project"`, `"user"`), `content`, `created_at`, `cues` (extracted phrases for retrieval).

Key components:
- **`MemoryStore`** — CRUD on `~/.bourbon/memory/<project-key>/` markdown files + MEMORY.md index. Grep-based keyword fallback.
- **`MemoryManager`** — orchestrates read/write/search; integrates semantic index with graceful fallback to keyword search. Detects stale/corrupt index and triggers rebuild.
- **`MemoryRetriever`** — hybrid RRF (Reciprocal Rank Fusion) fusing FTS5 keyword + cosine vector channels.
- **`MemorySearchIndex`** — SQLite FTS5 + vector storage. Stores provider/model/dimensions metadata for stale detection.
- **`FastEmbedProvider`** (`embeddings.py`) — lazy-loaded local embeddings via optional `fastembed` dependency. Raises `EmbeddingUnavailableError` on missing dep; system degrades cleanly.
- **`cues.py`** — deterministic phrase extraction from messages; expanded at query time for richer recall.
- **`policy.py`** — `check_write_permission()` gates writes; subagents restricted to `"project"` target only.
- **`files.py`** — reads AGENTS.md, merges global `~/.bourbon/USER.md` with project-local (project-local wins), reads MEMORY.md with token budgets.
- **Pre-compact flush** — before chain compaction, agent deterministically flushes memory candidates (keyword + error detection) without an LLM turn, so critical context survives compaction.

### Observability (`src/bourbon/observability/`)

OpenTelemetry tracing, gracefully degraded when `opentelemetry` is not installed.

- **`ObservabilityManager`** — singleton TracerProvider; exports via OTLP (endpoint from env `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` → `OTEL_EXPORTER_OTLP_ENDPOINT` → config). Uses `BatchSpanProcessor`.
- **`BourbonTracer`** — thin facade with context managers `llm_call()`, `tool_call()`, `agent_step()`. Records token counts, model name, finish reason. **Deliberately omits message bodies** (metadata-only, privacy-conscious). Conforms to OpenTelemetry GenAI semantic conventions.

### Permissions System (`src/bourbon/permissions/`)

Runtime access control evaluated at each tool call boundary. `PermissionChecker` evaluates policies against the executing actor context (user, agent, or subagent type). `matching.py` implements policy rule evaluation.

### Tool System (`src/bourbon/tools/`)

Tools registered via `@register_tool()` decorator into a global `ToolRegistry` singleton (lazy module imports). Each `Tool` has a `RiskLevel` (LOW/MEDIUM/HIGH).

Key modules:
- `base.py` — file ops, bash, todo; `read_file()` supports `offset` (1-indexed start line) and `limit`.
- `memory.py` — `MemorySearch`, `MemoryWrite`, `MemoryStatus`.
- `agent_tool.py` — spawns subagents.
- `task_tools.py` — task CRUD.
- `skill_tool.py` — loads skill content on demand.
- `tool_search.py` — searches available tools.
- `web.py`, `data.py`, `documents.py` — Stage B tools (conditionally registered).

High-risk tool failures set `Agent.pending_confirmation` and pause execution for interactive confirmation rather than auto-recovering.

### Other Subsystems

- **REPL** (`repl.py`) — Rich streaming markdown with simple newline-split buffering for incremental rendering.
- **Skills** (`skills.py`) — [Agent Skills](https://agentskills.io/) spec with three-tier disclosure. Scanner resolves project-level over user-level in priority order: `.kimi/skills/` → `.agents/skills/` → `.bourbon/skills/`.
- **MCP** (`mcp_client/`) — configured in `~/.bourbon/config.toml`. MCP tools registered as `{server}:{tool}` in the global registry.
- **Sandbox** (`sandbox/`) — bubblewrap (Linux) / seatbelt (macOS) / docker / local; selected by `runtime.py`.
- **Compression** (`compression.py`) — `ContextCompressor` triggers `microcompact()` on every step; full compact when token threshold exceeded.
- **LLM Client** (`llm.py`) — Anthropic + OpenAI-compatible; provider selected by `config.llm.default_provider`.

### Configuration

`~/.bourbon/config.toml` — global config. Key sections: `[llm]`, `[llm.anthropic]`, `[mcp]`, `[memory]`, `[observability]`, `[sandbox]`, `[access_control]`, `[audit]`.

### Evaluation Framework

`evals/` + `promptfooconfig.yaml` via [promptfoo](https://www.promptfoo.dev/). Test cases in `evals/cases/` (YAML). Custom providers:
- `evals/promptfoo_provider.py` — wraps `Agent.step()`, returns `{text, workdir, timing}`.
- `evals/memory_retrieval_provider.py` — deterministic memory retrieval eval with hybrid semantic variant.
- File/audit assertions use `javascript` assertions reading from the returned `workdir`.
