# Bourbon - General-Purpose AI Agent Platform

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Bourbon is a general-purpose AI agent platform with a code-first evolution, designed for software engineering, data analysis, and domain-specific tasks through an extensible skill system.

## 🎯 Overview

**Current Stage (B)**: General-purpose agent for knowledge work
- ✅ **Software Engineering**: Code search, refactoring, analysis
- ✅ **Domain Expertise**: Investment analysis via skills
- ✅ **External Tools**: MCP Client for databases, APIs
- ✅ **Safe Operations**: Sandboxed file operations, risk-based error handling

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
```

## 🚀 Quick Start

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

## 📁 Project Structure

```
.
├── src/bourbon/           # Core agent implementation
│   ├── cli.py            # Entry point
│   ├── agent.py          # Core agent loop
│   ├── skills.py         # Skill system (Agent Skills compatible)
│   ├── mcp_client/       # MCP Client implementation
│   ├── tools/            # Built-in tools
│   └── ...
├── .kimi/skills/          # Project-level skills
│   └── investment-skill/ # Investment analysis skill
├── evals/                 # Evaluation framework
│   ├── runner.py         # Test runner
│   └── cases/            # Test cases
└── tests/                 # Unit tests
```

## 🛠️ Core Capabilities

### 1. Built-in Tools

| Tool | Purpose | Safety |
|------|---------|--------|
| `read_file` | Read text/media files | Sandboxed to workdir |
| `write_file` | Create/modify files | Backup before changes |
| `shell` | Execute bash commands | Blacklist dangerous commands |
| `search` | Code search (rg/ast-grep) | Read-only |
| `todo` | Task management | - |

### Stage B: General Knowledge Tools

| Tool | Purpose | Domain |
|------|---------|--------|
| `fetch_url` | Fetch web content | Web |
| `csv_analyze` | CSV statistics | Data |
| `json_query` | JSON path queries | Data |
| `pdf_to_text` | PDF text extraction | Documents |
| `docx_to_markdown` | Word conversion | Documents |

### 2. Skill System (Agent Skills Compatible)

Bourbon implements the [Agent Skills](https://agentskills.io/) open specification:

```bash
# List available skills
> /skills

# Activate a skill
> /skill/investment-agent

# Use skill resources
> skill_read_resource("investment-agent", "config/portfolio.yaml")
```

**Skill Discovery Scopes** (priority order):
1. `{workdir}/.agents/skills/*/` - Project-level, cross-client
2. `{workdir}/.bourbon/skills/*/` - Project-level, client-specific
3. `~/.agents/skills/*/` - User-level, cross-client
4. `~/.bourbon/skills/*/` - User-level, client-specific

### 3. MCP Integration

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

## 🧪 Evaluation Framework

Comprehensive testing for skills, safety, and performance:

```bash
# Run all evaluations
npx promptfoo@latest eval

# Run specific category
npx promptfoo@latest eval --filter-pattern "Skills"

# Run with multiple iterations for variance analysis
npx promptfoo@latest eval --repeat 5

# Disable cache
npx promptfoo@latest eval --no-cache

# Open promptfoo dashboard
npx promptfoo@latest view
```

**Test Categories**:
- `skills.yaml` - Skill functionality tests
- `safety.yaml` - Security red team tests
- `sandbox.yaml` - Sandbox isolation tests
- `security.yaml` - Security behavior tests

## 📝 Development

```bash
# Run linting
ruff check src tests
ruff format src tests

# Run tests
pytest

# Run specific test
pytest tests/test_skills.py -v
```

## ⚙️ Configuration

Global configuration in `~/.bourbon/config.toml`:

```toml
[llm]
provider = "moonshot"
api_key = "your-api-key"
model = "kimi-k2-0711-preview"

[agent]
workdir = "/path/to/workspace"

[mcp]
enabled = true
default_timeout = 30
```

## 🔒 Safety Features

### Risk-Based Error Handling

| Risk Level | Operations | Strategy |
|------------|------------|----------|
| **HIGH** | Install/uninstall, system commands | MUST STOP and ask user |
| **MEDIUM** | File modifications | Report error, ask before alternatives |
| **LOW** | Read, search | May intelligently recover |

### Path Safety
- All file operations sandboxed to workspace
- No access outside working directory without explicit permission

### Command Safety
- Dangerous bash commands blacklisted
- Interactive confirmation for high-risk operations

## 📚 Documentation

- `AGENTS.md` - Detailed development guide
- `EVAL_GUIDE.md` - Evaluation framework documentation
- `evals/INVESTMENT_SKILL_*.md` - Investment skill optimization

## 📄 License

MIT License

## 🙏 Acknowledgments

- [Agent Skills](https://agentskills.io/) - Skill system specification
- [Model Context Protocol](https://modelcontextprotocol.io/) - External tool integration
