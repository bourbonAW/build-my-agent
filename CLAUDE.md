# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (base)
uv pip install -e ".[dev]"

# Install with Stage B dependencies (documents, web, data tools)
uv pip install -e ".[stage-b]"

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

# Run evaluations
npx promptfoo@latest eval
npx promptfoo@latest eval --filter-pattern "Skills"
npx promptfoo@latest eval --repeat 5
npx promptfoo@latest eval --no-cache
npx promptfoo@latest view
```

## Architecture

Bourbon is a general-purpose AI agent platform built around a synchronous conversation loop. The agent orchestrates LLM calls, tool execution, skill loading, and MCP server connections.

### Core Flow

```
CLI (cli.py) -> REPL (repl.py) -> Agent.step() -> LLM.chat() -> _execute_tools() -> loop
```

`Agent.step()` in `src/bourbon/agent.py` is the main entry point: it adds user input to message history, compresses context if needed, then runs `_run_conversation_loop()` which repeatedly calls the LLM and executes tool calls until the LLM stops with a text response (no tool calls). Max rounds are capped by `config.ui.max_tool_rounds` (default 50).

### Tool System (`src/bourbon/tools/`)

Tools are registered via `@register_tool()` decorator into a global `ToolRegistry` singleton. The registry lazily imports tool modules on first use (`base`, `search`, `skill_tool`). Each `Tool` has a `RiskLevel` (LOW/MEDIUM/HIGH) that drives the error-handling policy.

- `base.py` - File operations, bash, todo management
- `search.py` - Code search using ripgrep
- `skill_tool.py` - The `skill` tool that loads skill content
- `web.py`, `data.py`, `documents.py` - Stage B tools (conditionally available)

High-risk operations (detected by `Tool.is_high_risk_operation()`) that return an error cause `Agent._execute_tools()` to set `self.pending_confirmation` and return early, presenting an interactive confirmation prompt to the user.

### Skill System (`src/bourbon/skills.py`)

Implements the [Agent Skills](https://agentskills.io/) specification with three-tier progressive disclosure:

1. **Tier 1** - Catalog shown in system prompt (name + description, ~50-100 tokens each)
2. **Tier 2** - Full SKILL.md body loaded when agent calls the `skill` tool
3. **Tier 3** - Resources (scripts/, references/, assets/) read on demand

`SkillScanner` discovers skills by scanning directories in priority order (project-level overrides user-level):
1. `{workdir}/.agents/skills/*/`
2. `{workdir}/.bourbon/skills/*/`
3. `{workdir}/.claude/skills/*/`
4. `~/.agents/skills/*/`, `~/.bourbon/skills/*/`, `~/.claude/skills/*/`

Each skill requires a `SKILL.md` with YAML frontmatter (`name`, `description` required).

### MCP Integration (`src/bourbon/mcp_client/`)

MCP servers are configured in `~/.bourbon/config.toml` under `[mcp]`. The `MCPManager` connects to servers on startup (call `Agent.initialize_mcp_sync()` before first use) and registers their tools into the global `ToolRegistry` with the naming convention `{server_name}:{tool_name}`. All MCP tools default to `RiskLevel.MEDIUM`.

### LLM Client (`src/bourbon/llm.py`)

Multi-provider client supporting Anthropic and OpenAI-compatible APIs. Provider is selected by `config.llm.default_provider`. Configured globally in `~/.bourbon/config.toml`:

```toml
[llm]
default_provider = "anthropic"

[llm.anthropic]
api_key = "your-key"
model = "claude-sonnet-4-6"
```

### Context Compression (`src/bourbon/compression.py`)

`ContextCompressor` monitors token usage and compacts old messages when `config.ui.token_threshold` is exceeded. The agent also calls `microcompact()` on every step. Skills in use are protected from compaction.

### Evaluation Framework (`evals/` + `promptfooconfig.yaml`)

Evaluations now run through promptfoo. `promptfooconfig.yaml` is the entrypoint, and the cases live in root-level YAML files under `evals/cases/` (for example `skills.yaml`, `sandbox.yaml`, `security.yaml`).

- `evals/promptfoo_provider.py` wraps `Agent.step()` and returns JSON output with `text`, `workdir`, and timing metadata for promptfoo assertions.
- `evals/promptfoo_artifact_provider.py` serves prebuilt calibration artifacts directly to promptfoo's `llm-rubric` assertions.
- File and audit assertions are implemented as promptfoo `javascript` assertions that read files from the returned `workdir`.
- Calibration scoring uses promptfoo `llm-rubric` metrics plus range checks in `javascript` assertions.

## Key Design Decisions

- **Path safety**: All file operations sandboxed to `Agent.workdir` (defaults to `cwd`)
- **Risk-based error handling**: HIGH-risk tool failures pause execution for user confirmation rather than auto-recovering
- **Skill discovery**: Project-level skills (`.bourbon/skills/` or `.agents/skills/`) override user-level skills
- **MCP tools share the global registry**: Registered with `server:tool` prefix; no code changes needed to add new MCP servers
- **Tool registration is lazy**: `definitions()`, `handler()`, and `get_tool_with_metadata()` import tool modules on first call to avoid circular imports
