# AGENTS.md

Development guide for AI agents working on Bourbon.

## Project Vision

**Bourbon is a general-purpose agent platform** with a code-first evolution:
- **Stage A (Current)**: Perfect code capabilities - search, refactoring, analysis
- **Stage B**: Expand to general knowledge work - documents, web, data
- **Stage C**: Autonomous workflows across all domains

## Stage A Focus: Code Specialist

This stage builds exceptional software engineering assistance:
- Advanced code search (rg + ast-grep)
- Safe file operations with sandboxing
- Code-aware todo management
- Skills for coding patterns and best practices
- Context management for long coding sessions

## Project Structure

- `src/bourbon/`: Main source code
  - `cli.py`: Entry point
  - `config.py`: Configuration management (~/.bourbon/)
  - `llm.py`: Multi-provider LLM client
  - `repl.py`: REPL interface optimized for code
  - `agent.py`: Core agent loop
  - `tools/`: Tool implementations (search is code-focused)
  - `skills.py`: Agent Skills compatible skill system
  - `todos.py`: Todo management
  - `compression.py`: Context compression

## Development Commands

```bash
# Install dependencies
uv pip install -e ".[dev]"

# Run linting
ruff check src tests
ruff format src tests

# Run tests
pytest

# Run agent
python -m bourbon
```

## Key Design Decisions

1. **Path safety**: All file operations sandboxed to workspace
2. **Command safety**: Dangerous bash commands blacklisted
3. **Token management**: Auto-compact when context grows
4. **Configuration**: Global config in ~/.bourbon/
5. **Error handling**: Risk-based policy (see below)

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

### Usage

**Model-driven activation:**
```
User: "Refactor this code"
Agent: skill("python-refactoring")  # Auto-activated based on context
```

**User-explicit activation:**
```
> /skill/python-refactoring
```

**Read skill resource:**
```
> skill_read_resource("python-refactoring", "scripts/extract.py")
```

### Discovery Scopes

Bourbon scans for skills in (priority order):
1. `{workdir}/.agents/skills/*/` (project-level, cross-client)
2. `{workdir}/.bourbon/skills/*/` (project-level, client-specific)
3. `~/.agents/skills/*/` (user-level, cross-client)
4. `~/.bourbon/skills/*/` (user-level, client-specific)

Project-level skills override user-level skills with the same name.

## Error Handling Strategy

### Risk-Based Policy

| Risk Level | Operations | Failure Strategy |
|------------|-----------|------------------|
| **HIGH** | Software install/uninstall, version changes, system commands, destructive ops | MUST STOP and ask user confirmation |
| **MEDIUM** | File modifications (write, edit) | Report error, ask before alternatives |
| **LOW** | Read file, search, exploration | May intelligently recover and retry |

### Implementation

**Phase 1** (已完成): System prompt enhancement - LLM instructed on error handling rules

**Phase 2** (已完成): Enforced interception - Agent detects high-risk failures and pauses

```python
# Tool registration with risk level
@register_tool(
    name="bash",
    risk_level=RiskLevel.HIGH,
)
def bash_tool(command: str) -> str: ...

# Runtime detection
if tool.is_high_risk_operation(input) and output.startswith("Error"):
    pause_and_ask_user()  # Interactive confirmation in REPL
```

### Critical Rules

1. **NEVER automatically switch versions** - If `pip install package==9.9.9` fails, don't auto-install latest
2. **NEVER change parameters without approval** - If a command fails, report and ask  
3. **ALWAYS report what you did** - For low-risk recoveries, tell user the action taken

### Examples

```
# HIGH RISK - Must pause and ask
User: "安装 numpy 9.9.9"
Agent: pip install numpy==9.9.9 → Error: version not found
Agent: "安装失败。可用版本: 1.26.4, 1.26.3。请选择:"
       "1. 安装最新版  2. 指定其他版本  3. 取消"

# LOW RISK - May recover
User: "读取 main.py"
Agent: read_file("main.py") → Error: not found  
Agent: "文件不存在。找到 src/main.py，正在读取..."
```

## Adding New Tools

1. Define tool schema in `tools/__init__.py`
2. Implement handler in appropriate module
3. Register in tool registry
4. Add tests
