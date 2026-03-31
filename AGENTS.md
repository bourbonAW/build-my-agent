# AGENTS.md

Development guide for AI agents working on Bourbon.

## Project Vision

**Bourbon is a general-purpose agent platform** with a code-first evolution:
- **Stage A (Completed)**: Perfect code capabilities - search, refactoring, analysis
- **Stage B (Current)**: General-purpose knowledge work - documents, web, data, domain skills, sandbox isolation
- **Stage C**: Autonomous workflows across all domains

## Stage B Focus: General-Purpose Agent

Bourbon has evolved from a code specialist to a general-purpose agent with:
- **Software Engineering**: Code search, refactoring, analysis (Stage A capabilities)
- **Domain Expertise via Skills**: Investment analysis, note management, data analysis, and more
- **External Integrations**: MCP Client for databases, APIs, and external tools
- **Knowledge Work**: Documents, web, data analysis
- **Security**: Multi-layer sandbox isolation, access control, credential management, audit logging
- **Context Management**: Long session support with compression and streaming markdown rendering

### Key Capabilities

1. **Core Tools**: File operations, code search, bash execution, todo management
2. **Skill System**: Agent Skills compatible - progressive disclosure, multi-scope discovery
3. **MCP Integration**: External tool servers for extended capabilities
4. **Sandbox Isolation**: Bubblewrap, Docker, seatbelt providers for safe tool execution
5. **Eval Framework**: Promptfoo-based evaluation for skills, safety, and performance

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
│   ├── todos.py             # Todo management
│   ├── debug.py             # Debug logging
│   ├── tools/               # Built-in tools
│   │   ├── base.py          # File ops, bash, todos
│   │   ├── search.py        # Code search (ripgrep)
│   │   ├── skill_tool.py    # Skill activation tool
│   │   ├── web.py           # Web fetch (Stage B)
│   │   ├── data.py          # CSV/JSON analysis (Stage B)
│   │   └── documents.py     # PDF/DOCX extraction (Stage B)
│   ├── sandbox/             # Sandbox isolation
│   │   ├── runtime.py       # Runtime manager
│   │   ├── policy.py        # Sandbox policies
│   │   ├── credential.py    # Credential isolation
│   │   ├── credential_proxy.py
│   │   └── providers/       # bubblewrap, docker, seatbelt, local
│   ├── access_control/      # Capability-based access control
│   │   ├── capabilities.py
│   │   └── policy.py
│   ├── audit/               # Security event logging
│   │   └── events.py
│   └── mcp_client/          # MCP Client implementation
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
│   │   ├── calibration.yaml # Multi-dimensional scoring
│   │   ├── safety.yaml      # Safety red team tests
│   │   ├── security.yaml    # Security behavior tests
│   │   ├── sandbox.yaml     # Sandbox isolation tests
│   │   ├── skills.yaml      # Skill functionality tests
│   │   ├── code-search.yaml # Code search tests
│   │   ├── file-operations.yaml
│   │   ├── general.yaml
│   │   └── validator-smoke.yaml
│   └── fixtures/            # Pre-built test fixtures
├── promptfooconfig.yaml      # Promptfoo configuration (eval entrypoint)
├── tests/                    # Unit tests
└── docs/                     # Design docs, specs, plans
```

## Development Commands

```bash
# Install dependencies
uv pip install -e ".[dev]"

# Install Stage B dependencies
uv pip install -e ".[stage-b]"

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
2. **Multi-layer security**: Sandbox providers (bubblewrap/docker/seatbelt) + capability-based access control + audit logging
3. **Command safety**: Dangerous bash commands blacklisted, interactive confirmation for high-risk operations
4. **Token management**: Auto-compact when context grows
5. **Configuration**: Global config in ~/.bourbon/
6. **Error handling**: Risk-based policy (see below)
7. **Streaming markdown**: Rich library with newline-split buffering for incremental rendering
8. **Eval via promptfoo**: Standardized evaluation with caching, dashboards, and multi-dimensional scoring

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

Following the Agent Skills specification, Bourbon uses three-tier disclosure:

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

Evaluations run through [promptfoo](https://www.promptfoo.dev/), replacing the previous custom eval runner.

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
- **Fixtures**: Pre-built artifacts and project templates in `evals/fixtures/`
- **Assertions**: Promptfoo `javascript` assertions for file checks, `llm-rubric` for subjective evaluation, `contains`/`not-contains` for text matching

### Test Categories

| Category | Description |
|----------|-------------|
| `calibration.yaml` | Multi-dimensional scoring with pre-built artifacts |
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
