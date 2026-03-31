# Bourbon - General-Purpose AI Agent Platform

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Bourbon is a general-purpose AI agent platform with a code-first evolution, designed for software engineering, data analysis, and domain-specific tasks through an extensible skill system.

## Overview

**Current Stage (B)**: General-purpose agent for knowledge work
- **Software Engineering**: Code search, refactoring, analysis
- **Domain Expertise**: Investment analysis, note management, and more via skills
- **External Tools**: MCP Client for databases, APIs
- **Security**: Multi-layer sandbox isolation (bubblewrap/docker/seatbelt), access control, audit logging
- **Safe Operations**: Sandboxed file operations, risk-based error handling

**Architecture**:
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Skills    │     │   Agent     │     │    MCP      │
│  (Domain)   │◀───▶│   Core      │◀───▶│  (External) │
└─────────────┘     └─────────────┘     └─────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────┐
│                 Built-in Tools                      │
│  File Ops │ Search │ Bash │ LLM │ Todos │ Config   │
└─────────────────────────────────────────────────────┘
        │                    │
        ▼                    ▼
┌─────────────┐     ┌─────────────────────────────────┐
│  Sandbox    │     │  Access Control + Audit          │
│  Isolation  │     │  Capabilities │ Policy │ Events  │
└─────────────┘     └─────────────────────────────────┘
```

## Quick Start

```bash
# Clone and setup
git clone <repo-url>
cd bourbon

# Install with uv (recommended)
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"

# Run the agent
python -m bourbon

# Or use the CLI
bourbon
```

## Project Structure

```
.
├── src/bourbon/              # Core agent implementation
│   ├── cli.py               # Entry point
│   ├── agent.py             # Core agent loop
│   ├── repl.py              # REPL with Rich streaming markdown
│   ├── skills.py            # Skill system (Agent Skills compatible)
│   ├── mcp_client/          # MCP Client implementation
│   ├── tools/               # Built-in tools
│   ├── sandbox/             # Sandbox isolation (bubblewrap/docker/seatbelt)
│   ├── access_control/      # Capability-based access control
│   └── audit/               # Security event logging
├── .kimi/skills/             # Project-level skills
│   ├── investment-skill/    # Investment analysis
│   ├── note-vault/          # Note management
│   ├── data-analysis-skill/ # Data analysis
│   ├── document-parse-skill/# Document parsing
│   ├── report-gen-skill/    # Report generation
│   └── web-fetch-skill/     # Web fetching
├── evals/                    # Evaluation framework (promptfoo)
│   ├── cases/               # Test case YAML files
│   └── fixtures/            # Pre-built test fixtures
├── promptfooconfig.yaml      # Promptfoo configuration
└── tests/                    # Unit tests
```

## Core Capabilities

### Built-in Tools

| Tool | Purpose | Safety |
|------|---------|--------|
| `read_file` | Read text/media files | Sandboxed to workdir |
| `write_file` | Create/modify files | Backup before changes |
| `shell` | Execute bash commands | Blacklist dangerous commands |
| `search` | Code search (ripgrep) | Read-only |
| `todo` | Task management | - |

### Stage B: General Knowledge Tools

| Tool | Purpose | Domain |
|------|---------|--------|
| `fetch_url` | Fetch web content | Web |
| `csv_analyze` | CSV statistics | Data |
| `json_query` | JSON path queries | Data |
| `pdf_to_text` | PDF text extraction | Documents |
| `docx_to_markdown` | Word conversion | Documents |

```bash
# Install Stage B dependencies
uv pip install -e ".[stage-b]"
```

### Skill System (Agent Skills Compatible)

Bourbon implements the [Agent Skills](https://agentskills.io/) open specification:

**Skill Discovery Scopes** (priority order):
1. `{workdir}/.kimi/skills/*/` - Project-level
2. `{workdir}/.agents/skills/*/` - Project-level, cross-client
3. `{workdir}/.bourbon/skills/*/` - Project-level, client-specific
4. `~/.agents/skills/*/` - User-level, cross-client
5. `~/.bourbon/skills/*/` - User-level, client-specific

### MCP Integration

Connect to external tool servers via Model Context Protocol:

```toml
# ~/.bourbon/config.toml
[mcp]
enabled = true

[[mcp.servers]]
name = "fetch"
transport = "stdio"
command = "uvx"
args = ["mcp-server-fetch"]
```

## Security

### Sandbox Isolation

Multi-provider sandbox for isolating tool execution:

| Provider | Platform | Isolation |
|----------|----------|-----------|
| Bubblewrap | Linux | Namespace-based (filesystem, network, PID) |
| Docker | Cross-platform | Container isolation |
| Seatbelt | macOS | App Sandbox profiles |
| Local | Any | No isolation (development) |

### Access Control & Audit

- **Capability-based access control**: Fine-grained permissions for tool operations
- **Audit logging**: Security-relevant events tracked for review
- **Credential isolation**: Credentials proxied without direct exposure to sandboxed processes

### Risk-Based Error Handling

| Risk Level | Operations | Strategy |
|------------|------------|----------|
| **HIGH** | Install/uninstall, system commands | MUST STOP and ask user |
| **MEDIUM** | File modifications | Report error, ask before alternatives |
| **LOW** | Read, search | May intelligently recover |

## Evaluation Framework

Evaluations run through [promptfoo](https://www.promptfoo.dev/):

```bash
# Run all evaluations
npx promptfoo@latest eval

# Run specific category
npx promptfoo@latest eval --filter-pattern "Skills"

# Multiple iterations for variance analysis
npx promptfoo@latest eval --repeat 5

# Open promptfoo dashboard
npx promptfoo@latest view
```

**Test Categories**: calibration, safety, security, sandbox, skills, code-search, file-operations, general, validator-smoke

## Development

```bash
# Run linting
ruff check src tests
ruff format src tests

# Type check
mypy src

# Run tests
pytest

# Run specific test
pytest tests/test_skills_new.py -v
```

## Configuration

Global configuration in `~/.bourbon/config.toml`:

```toml
[llm]
default_provider = "anthropic"

[llm.anthropic]
api_key = "your-api-key"
model = "claude-sonnet-4-6"

[agent]
workdir = "/path/to/workspace"

[mcp]
enabled = true
default_timeout = 30
```

## Documentation

- `AGENTS.md` - Detailed development guide
- `EVAL_GUIDE.md` - Evaluation framework documentation
- `docs/` - Design specs and implementation plans

## License

MIT License

## Acknowledgments

- [Agent Skills](https://agentskills.io/) - Skill system specification
- [Model Context Protocol](https://modelcontextprotocol.io/) - External tool integration
- [promptfoo](https://www.promptfoo.dev/) - Evaluation framework
