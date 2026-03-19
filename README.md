# 🥃 Bourbon

A general-purpose agent platform starting with exceptional code capabilities.

## Overview

Bourbon is designed as a **general agent** that can handle diverse tasks, but Stage A focuses on being an **exceptional coding assistant**. This code-first approach lets us perfect the core architecture with a well-defined domain before expanding to general knowledge work.

## Stage A Features (Code Specialist)

- **Code-Optimized REPL**: Terminal interface with syntax highlighting, designed for coding workflows
- **Advanced Code Search**: ripgrep for text search + ast-grep for structural/AST search
- **Safe File Operations**: Read, write, edit with path sandboxing and security checks
- **Task Management**: Track coding tasks and subtasks
- **Skill System**: Load coding patterns, refactoring recipes, language-specific guides
- **MCP Client**: Connect to external Model Context Protocol servers for extended capabilities
- **Context Compression**: Handle long coding sessions without losing context
- **Multi-Provider LLM**: Anthropic Claude and OpenAI support

**Future stages** will expand Bourbon into general knowledge work (documents, web, data analysis) and autonomous workflows.

## Quick Start

```bash
# Install with uv
uv pip install -e ".[dev]"

# Configure (interactive setup)
bourbon --init

# Run
bourbon
```

## Usage

### REPL Commands

```
🥃 bourbon >> /help
Available commands:
  /compact - Manually compress context
  /tasks   - Show todo list
  /skills  - List available skills
  /clear   - Clear conversation history
  /help    - Show help message
  /exit    - Exit the REPL

🥃 bourbon >> 分析这个项目的代码结构

> rg_search: Found 42 matches in 12 files
> read_file: Read src/bourbon/agent.py (150 lines)

根据搜索结果，这个项目使用了标准的 Python 包结构...

🥃 bourbon >> /tasks
[x] 分析项目结构
[>] 重构 main.py <- 正在处理
[ ] 添加测试

🥃 bourbon >> /exit
```

### Skills

Skills are loaded from `~/.bourbon/skills/`:

```markdown
---
name: python-refactoring
description: Python refactoring patterns
---

# Refactoring Guide

1. Use ast-grep to find patterns...
```

Load with: `load_skill("python-refactoring")`

### MCP (Model Context Protocol)

Bourbon supports MCP servers to extend its capabilities with external tools:

**Configuration** (`~/.bourbon/config.toml`):

```toml
[mcp]
enabled = true

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

**Usage**:

MCP tools are automatically available to the agent with the `server_name:tool_name` prefix:

```
> 使用 fetch:fetch_url 获取 https://example.com 的内容
> 使用 github:search_issues 搜索 bourbon 项目的 open issues
```

View MCP status with `/mcp` command.

**Recommended MCP Servers**:
- [mcp-server-fetch](https://github.com/modelcontextprotocol/servers) - Web content fetching
- [GitHub MCP](https://github.com/github/github-mcp-server) - GitHub operations
- [Filesystem MCP](https://github.com/modelcontextprotocol/servers) - File operations

## Project Structure

```
bourbon/
├── src/bourbon/
│   ├── agent.py          # Core agent loop
│   ├── cli.py            # CLI entry point
│   ├── config.py         # Configuration management
│   ├── llm.py            # Anthropic/OpenAI clients
│   ├── repl.py           # REPL interface
│   ├── skills.py         # Skill loading
│   ├── todos.py          # Todo management
│   ├── compression.py    # Context compression
│   ├── mcp_client/       # MCP Client implementation
│   │   ├── config.py     # MCP configuration
│   │   ├── manager.py    # MCP connection management
│   │   └── connector.py  # Transport connectors
│   └── tools/
│       ├── base.py       # bash, read, write, edit
│       ├── search.py     # rg, ast-grep
│       └── __init__.py   # Tool registry
├── tests/             # Test suite
└── docs/
    ├── specs/         # Design specifications
    └── plans/         # Implementation plans
```

## Development

```bash
# Run tests
uv run pytest

# Run linting
ruff check src tests
ruff format src tests

# Type checking
mypy src

# Run in development mode
uv run python -m bourbon
```

## Roadmap

- **Stage A** (Current): Code Specialist - refactoring, analysis, code review
- **Stage B**: General Assistant - web, documents, data analysis, writing
- **Stage C**: Autonomous Workflows - self-directed, multi-domain tasks

## Tech Stack

- Python 3.14
- uv (package management)
- ruff (linting/formatting)
- Anthropic & OpenAI APIs
- rich & prompt-toolkit (REPL)
- pytest (testing)

## License

MIT
