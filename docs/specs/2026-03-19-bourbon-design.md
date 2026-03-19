# Bourbon Agent - Design Specification

**Version:** 1.0  
**Date:** 2026-03-19  
**Status:** Stage A (Personal Programming Assistant)

---

## 1. Overview

**Bourbon is a general-purpose agent platform** with a code-first evolution strategy.

While the long-term vision is a versatile agent capable of handling diverse tasks (writing, analysis, automation, research), **Stage A intentionally focuses on building exceptional code capabilities first**. This allows us to:

1. Perfect the core agent architecture with a well-defined domain
2. Build tools that are useful for code (search, editing, refactoring)
3. Establish patterns that generalize to other domains later
4. Deliver immediate value to developers (ourselves included)

The roadmap progresses from **Code Specialist → General Assistant → Autonomous Workflows**.

The name "Bourbon" represents smoothness, depth, and craftsmanship — qualities we aim for in the agent's interaction experience.

### 1.1 Core Philosophy

- **General agent, specific start**: Architecture supports any domain; implementation starts with code
- **Model-first**: The LLM is the agent; our job is to provide great tools and get out of the way
- **Progressive expansion**: Master code, then generalize to other tasks
- **Unix philosophy**: Do one thing well, compose with other tools
- **Developer-centric**: Built by developers, for developers (starting point, not endpoint)

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

**Evolution Strategy: Perfect the specific, then generalize**

| Stage | Focus | Domain | Key Expansion |
|-------|-------|--------|---------------|
| **A** | Code Specialist | Software engineering | Core agent architecture, code tools (rg, ast-grep) |
| **B** | General Assistant | Knowledge work | Web, documents, data analysis, writing |
| **C** | Autonomous Agent | Multi-domain | Self-direction, workflows, multi-agent teams |

### Stage A: Code Specialist (Current)

**Goal:** An exceptional coding assistant that handles complex software engineering tasks

**Why code first?** Code is a well-structured domain with clear patterns, enabling us to perfect the agent architecture before generalizing. The tools built here (search, analysis, refactoring) establish patterns applicable to other domains.

**Core Features (Code-focused):**
- [ ] REPL with rich UI optimized for code workflows
- [ ] File operations (read, write, edit) with path safety
- [ ] Advanced search (rg for text, ast-grep for structure)
- [ ] Code-aware todo management
- [ ] Skill system for loading coding patterns/best practices
- [ ] Context compression for long coding sessions
- [ ] Multi-provider LLM support (Anthropic + OpenAI)
- [ ] MCP integration for extended capabilities

**Deliverable:** `bourbon` CLI handles real coding tasks: refactoring, analysis, bug fixes, code review

### Stage B: General Assistant (Expansion)

**Goal:** Extend beyond code to general knowledge work while retaining code excellence

**Expansion Areas:**
- **Web capabilities**: Fetch, browse, scrape (via MCP/browser tools)
- **Document processing**: PDF, Office, Markdown analysis
- **Data tasks**: CSV/JSON analysis, transformation
- **Writing assistance**: Documentation, emails, content
- **Multi-modal**: Image understanding (via vision models)

**New Mechanisms:**
- Subagent spawning with context isolation
- File-based task graph system
- Background task execution with notifications
- Agent mailbox (JSONL-based messaging)
- Tool discovery and dynamic loading

**Deliverable:** Bourbon handles mixed tasks: "Analyze this CSV, generate a report, and email it"

### Stage C: Autonomous Workflows (Scale)

**Goal:** Self-directed, long-running, multi-step workflows that span domains

**Autonomy Features:**
- Task board polling and self-assignment
- Proactive execution based on triggers (time, file changes, webhooks)
- Long-running operations with checkpoint/resume
- Multi-agent teams with specialized roles (code, research, writing)
- Decision delegation with approval gates

**Infrastructure:**
- Git worktree isolation for parallel tasks
- Workflow definition language
- Cron-like scheduling
- Event-driven architecture

**Deliverable:** "Keep an eye on this GitHub repo, review PRs, and notify me of critical issues"

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
