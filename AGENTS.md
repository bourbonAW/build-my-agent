# AGENTS.md

Development guide for AI agents working on Bourbon.

## Project Vision

**Bourbon is a general-purpose agent platform** with a code-first evolution:
- **Stage A (Completed)**: Perfect code capabilities - search, refactoring, analysis
- **Stage B (Current)**: General-purpose knowledge work - documents, web, data, domain skills, sandbox isolation, subagents, persistent tasks, observability
- **Stage C**: Autonomous workflows across all domains

## Current Focus

Bourbon has evolved from a code specialist to a multi-agent platform with:
- **Software Engineering**: Code search, refactoring, analysis (Stage A capabilities)
- **Domain Expertise via Skills**: Investment analysis, note management, data analysis, and more
- **External Integrations**: MCP Client for databases, APIs, and external tools
- **Knowledge Work**: Documents, web, data analysis
- **Multi-Agent**: Subagent system with parallel execution, tool filtering, and cancellation
- **Persistent Tasks**: File-backed workflow tasks with ownership and dependencies (Task V2)
- **Session Management**: Structured session layer with MessageChain, ContextManager, and transcript storage
- **Memory (Phase 2 Delivered)**: File-first memory stack with prompt anchors, recall, governed writes, and promoted preference injection into managed USER.md
- **Security**: Multi-layer sandbox isolation, permissions, access control, credential management, audit logging
- **Observability**: OpenTelemetry tracing integration
- **Context Management**: Long session support with compression and streaming markdown rendering

### Key Capabilities

1. **Core Tools**: File operations, code search, bash execution, todo/task management
2. **Subagent System**: Parallel task execution, code exploration, focused work via specialized sub-agents
3. **Skill System**: Agent Skills compatible - progressive disclosure, multi-scope discovery
4. **MCP Integration**: External tool servers for extended capabilities
5. **Sandbox Isolation**: Bubblewrap, Docker, seatbelt providers for safe tool execution
6. **Memory System**: Governed memory records with write, search, promote, and archive lifecycle
7. **Eval Framework**: Promptfoo-based evaluation + community benchmarks

## Project Structure

```
.
├── src/bourbon/              # Core agent implementation
│   ├── cli.py               # Entry point
│   ├── agent.py             # Core agent loop
│   ├── repl.py              # REPL interface with Rich streaming markdown
│   ├── config.py            # Configuration management (~/.bourbon/)
│   ├── llm.py               # Multi-provider LLM client
│   ├── skills.py            # Agent Skills compatible skill system
│   ├── compression.py       # Context compression
│   ├── todos.py             # In-memory todo management (V1)
│   ├── debug.py             # Debug logging
│   ├── prompt/              # Prompt management system
│   │   ├── builder.py       # PromptBuilder with ordered sections
│   │   ├── context.py       # PromptContext for section rendering
│   │   ├── dynamic.py       # Dynamic prompt sections
│   │   ├── sections.py      # Static prompt section definitions
│   │   └── types.py         # PromptSection types
│   ├── session/             # Session management layer
│   │   ├── chain.py         # MessageChain (in-memory message list)
│   │   ├── context.py       # ContextManager (token tracking, compact)
│   │   ├── manager.py       # SessionManager orchestration
│   │   ├── storage.py       # TranscriptStore (append-only JSONL)
│   │   └── types.py         # Session types (metadata, summaries, triggers)
│   ├── subagent/            # Subagent runtime system
│   │   ├── manager.py       # SubagentManager (lifecycle orchestration)
│   │   ├── types.py         # AgentDefinition, SubagentRun, RunStatus
│   │   ├── cancel.py        # AbortController hierarchy
│   │   ├── registry.py      # RunRegistry (in-memory runtime-job storage)
│   │   ├── executor.py      # AsyncExecutor (ThreadPoolExecutor)
│   │   ├── tools.py         # Tool filtering by agent type
│   │   ├── errors.py        # SubagentErrorCode, RunError
│   │   ├── result.py        # Result finalization
│   │   ├── partial_result.py # Partial result extraction
│   │   ├── cleanup.py       # Resource cleanup
│   │   └── session_adapter.py # Subagent session isolation
│   ├── tasks/               # Persistent workflow tasks (V2)
│   │   ├── types.py         # TaskRecord (id, subject, status, owner, blocks)
│   │   ├── store.py         # JSON file persistence + highwatermark
│   │   ├── service.py       # Business rules (dependencies, owner, cleanup)
│   │   ├── list_id.py       # Task list scope resolution
│   │   ├── locking.py       # POSIX file locking
│   │   └── constants.py     # Task constants
│   ├── tools/               # Built-in tools
│   │   ├── base.py          # File ops, bash, todos
│   │   ├── search.py        # Code search (ripgrep)
│   │   ├── skill_tool.py    # Skill activation tool
│   │   ├── agent_tool.py    # Subagent spawn tool
│   │   ├── task_tools.py    # TaskCreate/TaskUpdate/TaskList/TaskGet
│   │   ├── todo_tool.py     # TodoWrite tool
│   │   ├── tool_search.py   # Tool discovery
│   │   ├── execution_queue.py # Tool execution queue
│   │   ├── web.py           # Web fetch (Stage B)
│   │   ├── data.py          # CSV/JSON analysis (Stage B)
│   │   └── documents.py     # PDF/DOCX extraction (Stage B)
│   ├── sandbox/             # Sandbox isolation
│   │   ├── runtime.py       # Runtime manager
│   │   ├── policy.py        # Sandbox policies
│   │   ├── credential.py    # Credential isolation
│   │   ├── credential_proxy.py
│   │   └── providers/       # bubblewrap, docker, seatbelt, local
│   ├── permissions/         # Permission system
│   │   ├── matching.py      # Permission matching logic
│   │   ├── runtime.py       # Permission runtime enforcement
│   │   └── presentation.py  # Permission UI presentation
│   ├── access_control/      # Capability-based access control
│   │   ├── capabilities.py
│   │   └── policy.py
│   ├── observability/       # OpenTelemetry integration
│   │   ├── manager.py       # Observability manager
│   │   └── tracer.py        # Tracer wrapper
│   ├── audit/               # Security event logging
│   │   └── events.py
│   └── mcp_client/          # MCP Client implementation
│       ├── config.py        # MCP server configuration
│       ├── connector.py     # Server connection management
│       ├── manager.py       # MCPManager orchestration
│       ├── runtime.py       # MCP runtime
│       └── utils.py         # MCP utilities
├── .kimi/skills/             # Project-level skills
│   ├── investment-skill/    # Investment analysis
│   ├── note-vault/          # Note management
│   ├── data-analysis-skill/ # Data analysis
│   ├── document-parse-skill/# Document parsing
│   ├── report-gen-skill/    # Report generation
│   └── web-fetch-skill/     # Web fetching
├── evals/                    # Evaluation framework (promptfoo)
│   ├── promptfoo_provider.py       # Agent provider for promptfoo
│   ├── promptfoo_artifact_provider.py  # Calibration artifact provider
│   ├── cases/               # Test case YAML files
│   ├── benchmarks/          # Community benchmarks (BigBench, GAIA, GSM8K, HumanEval, MT-Bench)
│   ├── loaders/             # Benchmark dataset loaders (HuggingFace, etc.)
│   ├── fixtures/            # Pre-built test fixtures
│   └── results/             # Eval run results
├── tests/                    # Unit tests (organized by module)
│   ├── session/             # Session layer tests
│   ├── test_subagent/       # Subagent system tests
│   ├── tools/               # Tool-specific tests
│   ├── evals/               # Eval framework tests
│   └── stage_b/             # Stage B tool tests
├── docs/                     # Design docs, specs, plans
│   ├── specs/               # Core design specs
│   └── superpowers/         # Feature design & implementation
│       ├── specs/           # Feature design documents
│       ├── plans/           # Implementation plans
│       └── guides/          # Usage guides
├── promptfooconfig.yaml      # Promptfoo configuration (eval entrypoint)
└── pyproject.toml            # Project metadata & dependencies
```

## Development Commands

```bash
# Install dependencies
uv pip install -e ".[dev]"

# Install Stage B dependencies
uv pip install -e ".[stage-b]"

# Install observability dependencies
uv pip install -e ".[observability]"

# Run linting
ruff check src tests
ruff format src tests

# Type check
mypy src

# Run tests
pytest

# Run evaluations
npx promptfoo@latest eval
npx promptfoo@latest eval --filter-pattern "Skills"
npx promptfoo@latest view

# Run agent
python -m bourbon
```

## Key Design Decisions

1. **Path safety**: All file operations sandboxed to workspace
2. **Multi-layer security**: Sandbox providers (bubblewrap/docker/seatbelt) + permissions + capability-based access control + audit logging
3. **Command safety**: Dangerous bash commands blacklisted, interactive confirmation for high-risk operations
4. **Token management**: Auto-compact when context grows; session layer tracks token status
5. **Configuration**: Global config in ~/.bourbon/
6. **Error handling**: Risk-based policy (see below)
7. **Streaming markdown**: Rich library with newline-split buffering for incremental rendering
8. **Eval via promptfoo**: Standardized evaluation with caching, dashboards, multi-dimensional scoring, and community benchmarks
9. **Subagent isolation**: Each subagent gets its own session, tool set, and abort controller
10. **Task/Todo split**: In-memory todos (V1) for quick checklists; persistent file-backed tasks (V2) for workflow management
11. **Memory (planned)**: File-first + grep recall; prompt anchors (AGENTS.md, MEMORY.md, USER.md); governed writes with scope isolation

## Session Management

The session layer (`src/bourbon/session/`) provides structured conversation management:

- **MessageChain**: In-memory ordered message list with role tracking
- **TranscriptStore**: Append-only JSONL persistence for full conversation history
- **ContextManager**: Token estimation, microcompact, auto/manual compact triggers
- **SessionManager**: Orchestrates chain + store + context; supports session resume

## Subagent System

The subagent system (`src/bourbon/subagent/`) enables parallel task execution:

### Architecture

```
SubagentManager
  ├── RunRegistry (runtime-job state)
  ├── AsyncExecutor (ThreadPoolExecutor)
  ├── AbortController (cancellation hierarchy)
  ├── ToolFilter (agent-type-based tool access)
  └── ResourceManager (cleanup)
```

### Agent Types

Each subagent type gets a filtered tool set. Tool filtering is defined in `subagent/tools.py` via `AGENT_TYPE_CONFIGS`.

### Execution Modes

- **Synchronous**: Blocking execution, result returned inline
- **Asynchronous**: Background execution via thread pool, result polled or awaited

## Task & Todo System

Bourbon has two layers of work tracking:

| Layer | Storage | Scope | Tools |
|-------|---------|-------|-------|
| **Todo V1** | In-memory | Single session | `TodoWrite` |
| **Task V2** | JSON files (`~/.bourbon/tasks/`) | Persistent, cross-session | `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet` |

Task V2 supports ownership, dependencies (`blocks`/`blockedBy`), and status lifecycle.

## Prompt Management

The prompt system (`src/bourbon/prompt/`) uses ordered sections:

| Order | Section | Content |
|-------|---------|---------|
| 10 | identity | Agent identity and capabilities |
| 15 | memory_anchors | AGENTS.md, MEMORY.md, USER.md, and promoted managed blocks |
| 20 | task_guidelines | Task execution guidelines |
| 25 | subagent_guidelines | Subagent behavior rules |
| 30 | error_handling | Error handling policy |
| 40 | task_adaptability | Adaptive task behavior |
| 60 | skills | Skill catalog (progressive disclosure) |
| 70 | mcp_tools | MCP tool catalog |

Sections can be static strings or async callables receiving `PromptContext`.

## Memory System

Bourbon has a two-phase memory system for persisting and recalling agent-relevant context across sessions.

### Phase 1: File-First Recall (Completed)

- **Tools**: `memory_write`, `memory_search`, `memory_status`
- **Storage**: Individual `.md` records under `~/.bourbon/projects/{key}/memory/`
- **Index**: `MEMORY.md` (≤200 active records, one-line summaries injected into prompt)
- **Recall**: Grepped keyword search with status/kind/scope filters

### Phase 2: Promoted Preference Injection (Completed)

- **Tools**: `memory_promote`, `memory_archive`
- **Mechanism**: Stable `user`/`feedback` preferences move from the weak MEMORY.md index into a managed section of `~/.bourbon/USER.md`
- **Prompt guarantee**: Promoted blocks render before freeform USER.md content with reserved token budget, preventing truncation
- **Lifecycle**: `active` → `promoted` (strong injection) → `stale`/`rejected` (removed from injection, preserved for audit)
- **Content guard**: Bodies >150 tokens are truncated with a backlink to source file

### Architecture

```
Prompt Context (always injected)
  ├─ AGENTS.md              # Project-level behavior rules
  ├─ USER.md                # User preferences (handwritten + managed promoted blocks)
  └─ MEMORY.md              # Memory file index (active records only)

Memory Files
  └─ ~/.bourbon/projects/{project}/memory/
       ├─ MEMORY.md          # Index (≤200 lines, active only)
       ├─ {kind}_{slug}.md   # Individual memory records
       └─ logs/YYYY/MM/DD.md # Daily logs (pre-compact flush)
```

### Design Principles

- Transcript-first: append-only transcript as recoverable fact base
- Bounded prompt memory with hard token limits
- Local recall first (file + grep), no external services in V1
- Scope-aware sharing between main agent and subagents
- Governed writes with confidence, source tracking, and audit

**Design specs:**
- Phase 1: `docs/superpowers/specs/2026-04-19-bourbon-memory-design.md`
- Phase 2: `docs/superpowers/specs/2026-04-22-bourbon-memory-phase2-design.md`

## Skill System (Agent Skills Compatible)

Bourbon implements the [Agent Skills](https://agentskills.io/) open specification for skill management.

### Directory Structure

```
~/.bourbon/skills/
├── python-refactoring/
│   ├── SKILL.md          # Required: metadata + instructions
│   ├── scripts/          # Optional: executable code
│   ├── references/       # Optional: documentation
│   └── assets/           # Optional: templates, resources
└── superpowers/
    └── SKILL.md
```

### SKILL.md Format

```yaml
---
name: skill-name
description: What this skill does and when to use it
license: MIT
compatibility: Requires Python 3.8+
metadata:
  author: example-org
  version: "1.0"
---

# Skill Title

Instructions for the agent...
```

### Progressive Disclosure

| Tier | Content | When | Tokens |
|------|---------|------|--------|
| 1 | Catalog (name + description) | Session start | ~50-100 per skill |
| 2 | Full SKILL.md body | On activation | < 5000 recommended |
| 3 | Resources (scripts/references) | On demand | Varies |

### Discovery Scopes

Bourbon scans for skills in (priority order):
1. `{workdir}/.kimi/skills/*/` (project-level)
2. `{workdir}/.agents/skills/*/` (project-level, cross-client)
3. `{workdir}/.bourbon/skills/*/` (project-level, client-specific)
4. `~/.agents/skills/*/` (user-level, cross-client)
5. `~/.bourbon/skills/*/` (user-level, client-specific)

Project-level skills override user-level skills with the same name.

## Error Handling Strategy

### Risk-Based Policy

| Risk Level | Operations | Failure Strategy |
|------------|-----------|------------------|
| **HIGH** | Software install/uninstall, version changes, system commands, destructive ops | MUST STOP and ask user confirmation |
| **MEDIUM** | File modifications (write, edit) | Report error, ask before alternatives |
| **LOW** | Read file, search, exploration | May intelligently recover and retry |

### Critical Rules

1. **NEVER automatically switch versions** - If `pip install package==9.9.9` fails, don't auto-install latest
2. **NEVER change parameters without approval** - If a command fails, report and ask
3. **ALWAYS report what you did** - For low-risk recoveries, tell user the action taken

## Sandbox System

Bourbon uses a multi-provider sandbox for isolating tool execution:

### Providers

| Provider | Platform | Isolation Level |
|----------|----------|-----------------|
| **Bubblewrap** | Linux | Namespace-based (filesystem, network, PID) |
| **Docker** | Cross-platform | Container isolation |
| **Seatbelt** | macOS | App Sandbox profiles |
| **Local** | Any | No isolation (development only) |

### Architecture

```
Policy Engine (sandbox/policy.py)
       ↓
Runtime Manager (sandbox/runtime.py) → selects provider
       ↓
Provider (bubblewrap / docker / seatbelt / local)
       ↓
Isolated tool execution
```

### Credential Management

- `credential.py` - Credential isolation from sandboxed processes
- `credential_proxy.py` - Proxied access to credentials without direct exposure

## Permissions System

The permissions layer (`src/bourbon/permissions/`) provides runtime permission enforcement:

- **matching.py** - Pattern-based permission matching
- **runtime.py** - Runtime permission checks and enforcement
- **presentation.py** - User-facing permission request UI

## Observability

OpenTelemetry integration (`src/bourbon/observability/`) for tracing agent operations:

- **manager.py** - Observability lifecycle management
- **tracer.py** - Span creation and context propagation

Install: `uv pip install -e ".[observability]"`

## MCP Client Integration

Connect to external tool servers via [Model Context Protocol](https://modelcontextprotocol.io/):

### Configuration

```toml
# ~/.bourbon/config.toml
[mcp]
enabled = true
default_timeout = 30

[[mcp.servers]]
name = "fetch"
transport = "stdio"
command = "uvx"
args = ["mcp-server-fetch"]

[[mcp.servers]]
name = "github"
transport = "stdio"
command = "npx"
args = ["-y", "@github/mcp-server"]
env = { GITHUB_TOKEN = "${GITHUB_TOKEN}" }
```

### Tool Naming

MCP tools are registered as `{server_name}:{tool_name}` (e.g. `fetch:fetch_url`). All MCP tools default to `RiskLevel.MEDIUM`.

## Evaluation Framework

Evaluations run through [promptfoo](https://www.promptfoo.dev/).

### Running Evaluations

```bash
# Run all evaluations
npx promptfoo@latest eval

# Filter by category
npx promptfoo@latest eval --filter-pattern "Skills"

# Multiple iterations for variance analysis
npx promptfoo@latest eval --repeat 5

# Open dashboard
npx promptfoo@latest view
```

### Architecture

- **Provider**: `evals/promptfoo_provider.py` wraps `Agent.step()` and returns JSON `{text, workdir, duration}`
- **Artifact Provider**: `evals/promptfoo_artifact_provider.py` serves pre-built calibration artifacts
- **Cases**: YAML files in `evals/cases/` organized by category
- **Benchmarks**: Community benchmarks in `evals/benchmarks/` (BigBench Hard, GAIA, GSM8K, HumanEval, MT-Bench)
- **Loaders**: Dataset loaders in `evals/loaders/` for HuggingFace and other sources
- **Fixtures**: Pre-built artifacts and project templates in `evals/fixtures/`
- **Assertions**: Promptfoo `javascript` assertions for file checks, `llm-rubric` for subjective evaluation, `contains`/`not-contains` for text matching

### Test Categories

| Category | Description |
|----------|-------------|
| `calibration.yaml` | Multi-dimensional scoring with pre-built artifacts |
| `calibration-gen-eval.yaml` | Generated calibration cases |
| `safety.yaml` | Safety red team tests |
| `security.yaml` | Security behavior validation |
| `sandbox.yaml` | Sandbox isolation tests |
| `skills.yaml` | Skill functionality tests |
| `code-search.yaml` | Code search accuracy |
| `file-operations.yaml` | File operation correctness |
| `general.yaml` | General agent behavior |
| `validator-smoke.yaml` | Validator smoke tests |

## Stage B Tools

| Domain | Tool | Description |
|--------|------|-------------|
| **Web** | `fetch_url` | Fetch content from URLs with safety limits |
| **Data** | `csv_analyze`, `json_query` | Analyze CSV/JSON with statistics |
| **Documents** | `pdf_to_text`, `docx_to_markdown` | Extract text from PDF/Word |

Install Stage B dependencies: `uv pip install -e ".[stage-b]"`

---

## Adding New Tools

1. Define tool schema in `tools/__init__.py`
2. Implement handler in appropriate module
3. Register in tool registry with `@register_tool()`
4. Add tests

## Adding MCP Servers

MCP servers provide external tools without code changes:

1. Install the MCP server (e.g., `npm install -g @github/mcp-server`)
2. Add configuration to `~/.bourbon/config.toml`
3. Restart Bourbon
4. Use tools with `server:tool` syntax
