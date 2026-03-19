# Bourbon Agent - Design Specification

**Version:** 1.0  
**Date:** 2026-03-19  
**Status:** Stage A (Personal Programming Assistant)

---

## 1. Overview

Bourbon is a Python-based coding agent designed for developers who want a powerful, extensible CLI assistant. It follows a progressive architecture roadmap: **Personal Assistant → Team Collaboration → Automated Workflows**.

The name "Bourbon" represents smoothness, depth, and craftsmanship — qualities we aim for in the agent's interaction experience.

### 1.1 Core Philosophy

- **Model-first**: The LLM is the agent; our job is to provide great tools and get out of the way
- **Progressive complexity**: Start simple, add capabilities incrementally
- **Unix philosophy**: Do one thing well, compose with other tools
- **Developer-centric**: Built by developers, for developers

### 1.2 Technology Stack

| Component | Choice | Version/Notes |
|-----------|--------|---------------|
| Language | Python | 3.14+ (via uv) |
| Package Manager | uv | 0.7.19+ |
| Lint/Format | ruff | Latest |
| Browser Automation | basepywright | For web-based tools |
| Syntax Search | ast-grep | Structural code search |
| Text Search | ripgrep (rg) | Fast regex search |
| REPL UI | rich + prompt-toolkit | Syntax highlighting, completion |
| MCP | mcp SDK | Model Context Protocol |
| Configuration | pydantic-settings | TOML-based |

---

## 2. Architecture

### 2.1 High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│                      BOURBON AGENT                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   REPL UI   │───▶│  Agent Core  │───▶│  LLM Client  │  │
│  │   (rich)    │◀───│   (async)    │◀───│(Anthropic/  │  │
│  └─────────────┘    └──────┬───────┘    │   OpenAI)    │  │
│                            │            └──────────────┘  │
│                            ▼                               │
│              ┌─────────────────────────┐                   │
│              │     Tool Registry       │                   │
│              │  ┌─────┐ ┌─────┐ ┌────┐ │                   │
│              │  │bash │ │read │ │rg  │ │  + ast-grep      │
│              │  │write│ │edit │ │mcp │ │                   │
│              │  └─────┘ └─────┘ └────┘ │                   │
│              └─────────────────────────┘                   │
│                            │                               │
│                            ▼                               │
│              ┌─────────────────────────┐                   │
│              │   Supporting Systems    │                   │
│              │  • TodoManager          │                   │
│              │  • SkillLoader          │                   │
│              │  • ContextCompressor    │                   │
│              │  • ConfigManager        │                   │
│              └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Module Structure

```
bourbon/
├── pyproject.toml              # uv configuration
├── README.md
├── AGENTS.md                   # Development documentation
├── src/
│   └── bourbon/
│       ├── __init__.py         # Package version
│       ├── __main__.py         # python -m bourbon entry
│       ├── cli.py              # CLI argument parsing
│       ├── repl.py             # Rich-based REPL interface
│       ├── agent.py            # Core agent loop
│       ├── config.py           # Configuration management
│       ├── llm.py              # Multi-provider LLM client
│       ├── tools/
│       │   ├── __init__.py     # Tool registry
│       │   ├── base.py         # bash, read, write, edit
│       │   ├── search.py       # rg, ast-grep integration
│       │   └── mcp.py          # MCP client wrapper
│       ├── skills.py           # Skill loading system
│       ├── todos.py            # Todo management
│       └── compression.py      # Context compression
└── tests/                      # Test suite
```

---

## 3. Configuration System

### 3.1 Global Configuration Directory

Location: `~/.bourbon/`

```
~/.bourbon/
├── config.toml                 # Main configuration
├── skills/                     # Skill definitions
│   ├── python-refactor/
│   │   └── SKILL.md
│   └── code-review/
│       └── SKILL.md
└── history/                    # REPL history (optional)
    └── bourbon_history
```

### 3.2 Configuration File Format

```toml
# ~/.bourbon/config.toml

[llm]
default_provider = "anthropic"

[llm.anthropic]
api_key = "sk-ant-..."
model = "claude-sonnet-4-6"
base_url = "https://api.anthropic.com"
max_tokens = 8000
temperature = 0.7

[llm.openai]
api_key = "sk-..."
model = "gpt-4o"
base_url = "https://api.openai.com/v1"
max_tokens = 8000
temperature = 0.7

[tools.bash]
allowed_commands = ["*"]        # Wildcard = allow all (with blacklist)
blocked_commands = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/sda"]
timeout_seconds = 120

[tools.rg]
binary_path = "rg"
default_args = ["--smart-case", "--hidden", "--glob", "!.git"]
max_results = 100

[tools.ast_grep]
binary_path = "ast-grep"
default_args = ["--json"]

[mcp]
enabled = true
auto_discover = true

[mcp.servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed"]

[ui]
theme = "dracula"
auto_compact = true
token_threshold = 100000
show_token_count = true
syntax_highlighting = true
```

### 3.3 Initialization Flow

1. Check for `~/.bourbon/` existence
2. If missing, create directory structure
3. If `config.toml` missing, create from template with user input
4. Validate API keys and tool availability
5. Load skills from `~/.bourbon/skills/`

---

## 4. Tool System

### 4.1 Tool Registry

Tools are registered in a central registry with schema validation:

```python
@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable
    dangerous: bool = False
```

### 4.2 Stage A Tool Set

| Tool | Purpose | Notes |
|------|---------|-------|
| `bash` | Execute shell commands | Sandbox + blacklist protection |
| `read_file` | Read file contents | Line limits, offset support |
| `write_file` | Write/overwrite files | Auto-create directories |
| `edit_file` | Precise text replacement | Find old_text, replace with new_text |
| `rg_search` | Fast text search | Wrapper around ripgrep |
| `ast_grep_search` | Structural code search | Pattern-based AST matching |
| `TodoWrite` | Task list management | content, status, activeForm |
| `load_skill` | Load skill knowledge | From ~/.bourbon/skills/ |
| `compress` | Manual context compression | Trigger auto-compact |

### 4.3 Search Tools Detail

#### rg_search

```python
{
    "pattern": "class.*Agent",      # Regex pattern
    "path": "src/",                 # Search path (relative)
    "glob": "*.py",                 # File filter
    "case_sensitive": false,        # Case sensitivity
    "context_lines": 2              # Context lines to include
}
```

Output: Structured JSON with file, line, content.

#### ast_grep_search

```python
{
    "pattern": "class $NAME { }",   # ast-grep pattern
    "path": "src/",                 # Search path
    "language": "python",           # Language hint
    "rule_file": null               # Optional YAML rule file
}
```

Patterns examples:
- `class $NAME { }` - Find all class definitions
- `def $FUNC($$$ARGS):` - Find all function definitions
- `$VAR = $EXPR` - Find assignments

### 4.4 Security Model

- **Path sandboxing**: All file paths resolved relative to workspace, must not escape
- **Command blacklisting**: Dangerous commands blocked at tool level
- **Timeout protection**: All subprocess calls have timeouts
- **Output truncation**: Large outputs truncated to prevent context overflow

---

## 5. Core Systems

### 5.1 Agent Loop

```python
async def agent_loop(messages: list[Message]) -> None:
    """
    Main agent interaction loop.
    
    Flow:
    1. Pre-process: Apply micro-compact, check background tasks
    2. Check token count, auto-compact if over threshold
    3. Call LLM with system prompt + messages + tools
    4. Parse response
    5. If tool_use: execute tools, append results, loop
    6. If stop: return control to REPL
    """
```

### 5.2 Todo Manager

Features:
- Max 20 items
- Only one `in_progress` at a time
- Required fields: `content`, `status`, `activeForm`
- Status values: `pending`, `in_progress`, `completed`
- Render format: `[x] done item` / `[>] active item <- activeForm` / `[ ] pending item`

### 5.3 Skill Loader

Skill format (Markdown with YAML frontmatter):

```markdown
---
name: python-refactor
description: Best practices for Python code refactoring
tags: [python, refactoring, cleanup]
---

# Python Refactoring Guide

## When to Use

Use this skill when the user asks to refactor, clean up, or improve Python code.

## Patterns

### Extract Function

...examples...

## Tools to Use

- `ast_grep_search` to find patterns
- `edit_file` for precise replacements
```

Loading is on-demand via `load_skill(name)` tool.

### 5.4 Context Compression

Two-tier system:

1. **Micro-compact**: Before each LLM call, clear old tool_result content (keep last 3)
2. **Auto-compact**: When token count exceeds threshold:
   - Write full conversation to `.bourbon/transcripts/`
   - Generate summary via LLM
   - Replace history with summary + "Continuing..."

Token estimation: `len(json.dumps(messages)) // 4`

---

## 6. REPL Interface

### 6.1 Commands

| Command | Description |
|---------|-------------|
| `<natural language>` | Send message to agent |
| `/compact` | Manually trigger context compression |
| `/tasks` | Display todo list |
| `/skills` | List available skills |
| `/config` | Show current configuration |
| `/exit`, `/quit`, `Ctrl+D` | Exit REPL |

### 6.2 Visual Design

```
🥃 bourbon >> 帮我分析这个项目的结构

> rg_search: Found 42 matches in 12 files
> read_file: Read src/bourbon/agent.py (150 lines)

这个项目使用了标准的 Python 包结构...

🥃 bourbon >> 
```

Features:
- Syntax highlighting for code blocks
- Spinner during tool execution
- Token count display in prompt (optional)
- Command history (up/down arrows)
- Tab completion for commands

---

## 7. Roadmap

### Stage A: Personal Programming Assistant (Current)

**Goal:** A capable, single-user coding assistant

**Core Features:**
- [ ] REPL with rich UI
- [ ] Tool system (bash, read, write, edit)
- [ ] Smart search (rg, ast-grep)
- [ ] Todo management
- [ ] Skill loading
- [ ] Context compression
- [ ] Configuration system
- [ ] Anthropic + OpenAI support
- [ ] MCP integration

**Deliverable:** `bourbon` CLI runs, basic coding tasks work

### Stage B: Team Collaboration

**Goal:** Multiple agents working together

**New Mechanisms:**
- Subagent spawning with context isolation
- File-based task graph system
- Background task execution with notifications
- Agent mailbox (JSONL-based messaging)
- Team configuration and role management

**Deliverable:** Can spawn specialized agents, delegate tasks

### Stage C: Automated Workflows

**Goal:** Self-running, scheduled, autonomous operations

**New Mechanisms:**
- Autonomous agent mode (task board polling)
- Team protocols (request-response patterns)
- Git worktree isolation for parallel tasks
- Cron-like scheduling
- Webhook triggers

**Deliverable:** Full automation platform

---

## 8. Development Guidelines

### 8.1 Code Style

- **Ruff** for linting and formatting
- **Type hints** required for all public APIs
- **Docstrings** in Google style
- **Async/await** for I/O operations

### 8.2 Testing Strategy

- Unit tests for tool handlers
- Integration tests for LLM client
- Mock tests for external tools (rg, ast-grep)
- REPL interaction tests using `pexpect`

### 8.3 Error Handling

- Graceful degradation when tools unavailable
- Clear error messages to user
- Detailed logs in `~/.bourbon/logs/`

---

## 9. Open Questions

1. Should we support prompt caching for Anthropic?
2. How to handle MCP server authentication?
3. Should skills support versioning?
4. What's the migration path from Stage A → B → C?

---

## 10. References

- `learn-claude-code` project: Progressive agent architecture
- MCP Specification: https://modelcontextprotocol.io/
- ast-grep documentation: https://ast-grep.github.io/
- rich library: https://rich.readthedocs.io/
