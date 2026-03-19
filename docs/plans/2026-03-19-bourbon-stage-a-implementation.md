# Bourbon Agent - Stage A Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a code-specialist agent CLI with REPL, code-centric tools (bash/read/write/edit/rg/ast-grep), todos, skills, and context compression.

**Context:** This is Stage A of a general-purpose agent platform. While Bourbon's long-term vision is a versatile agent for any domain, we intentionally start with **exceptional code capabilities**. This provides:
1. A well-defined domain to perfect the agent architecture
2. Immediate value for developers (the initial users)
3. Tools (search, analysis) that establish patterns for other domains
4. A foundation that generalizes naturally in Stage B

**Architecture:** Single-agent architecture with tool dispatch pattern. REPL drives an async agent loop that calls LLM with code-optimized tools. Configuration stored in `~/.bourbon/`.

**Tech Stack:** Python 3.14, uv, ruff, anthropic/openai SDK, rich, prompt-toolkit, pydantic-settings

---

## File Structure Overview

```
bourbon/
├── pyproject.toml
├── README.md
├── AGENTS.md
├── src/
│   └── bourbon/
│       ├── __init__.py              # Version info
│       ├── __main__.py              # python -m bourbon
│       ├── cli.py                   # Entry point, config init
│       ├── config.py                # Configuration management
│       ├── llm.py                   # Multi-provider LLM client
│       ├── repl.py                  # Rich-based REPL
│       ├── agent.py                 # Core agent loop
│       ├── tools/
│       │   ├── __init__.py          # Tool registry, decorators
│       │   ├── base.py              # bash, read, write, edit
│       │   └── search.py            # rg, ast-grep integration
│       ├── skills.py                # Skill loading system
│       ├── todos.py                 # Todo management
│       └── compression.py           # Context compression
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_tools_base.py
    ├── test_tools_search.py
    ├── test_todos.py
    └── test_skills.py
```

---

## Chunk 1: Project Bootstrap and Configuration

### Task 1: Initialize Project with uv

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `AGENTS.md`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "bourbon"
version = "0.1.0"
description = "A personal programming assistant agent"
readme = "README.md"
requires-python = ">=3.14"
license = {text = "MIT"}
authors = [
    {name = "Bourbon Contributors"}
]
keywords = ["agent", "cli", "coding-assistant", "llm"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.14",
    "Topic :: Software Development :: Tools",
]
dependencies = [
    "anthropic>=0.49.0",
    "openai>=1.66.0",
    "rich>=13.9.0",
    "prompt-toolkit>=3.0.50",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.8.0",
    "toml>=0.10.2",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.25.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.11.0",
    "mypy>=1.15.0",
]

[project.scripts]
bourbon = "bourbon.cli:main"

[project.urls]
Homepage = "https://github.com/yourusername/bourbon"
Repository = "https://github.com/yourusername/bourbon"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/bourbon"]

[tool.ruff]
target-version = "py314"
line-length = 100

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "F",   # Pyflakes
    "I",   # isort
    "N",   # pep8-naming
    "W",   # pycodestyle warnings
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "SIM", # flake8-simplify
]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
pythonpath = ["src"]

[tool.mypy]
python_version = "3.14"
strict = true
warn_return_any = true
warn_unused_ignores = true
```

- [ ] **Step 2: Create README.md**

```markdown
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
- **Context Compression**: Handle long coding sessions without losing context
- **Multi-Provider LLM**: Anthropic Claude and OpenAI support

**Future stages** will expand Bourbon into general knowledge work (documents, web, data analysis) and autonomous workflows.

## Quick Start

```bash
# Install with uv
uv pip install -e ".[dev]"

# Configure
bourbon --init

# Run
bourbon
```

## Usage

```
🥃 bourbon >> 帮我分析这个项目的结构

> rg_search: Found 42 matches in 12 files

根据搜索结果，这个项目...

🥃 bourbon >> /tasks
[ ] 1: 分析项目结构
[>] 2: 重构 main.py <- 正在处理

🥃 bourbon >> /exit
```

## Roadmap

- **Stage A** (Current): Personal programming assistant
- **Stage B**: Team collaboration with subagents
- **Stage C**: Automated workflows

## License

MIT
```

- [ ] **Step 3: Create AGENTS.md**

```markdown
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
  - `skills.py`: Skill loading (coding patterns)
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

## Adding New Tools

1. Define tool schema in `tools/__init__.py`
2. Implement handler in appropriate module
3. Register in tool registry
4. Add tests
```

- [ ] **Step 4: Install Python 3.14 with uv**

```bash
cd /home/hf/github_project/build-my-agent
uv python install 3.14
uv venv --python 3.14
```

Expected: Python 3.14.0aX installed, `.venv` created

- [ ] **Step 5: Install dependencies**

```bash
uv pip install -e ".[dev]"
```

Expected: All dependencies installed successfully

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml README.md AGENTS.md
git commit -m "chore: Initialize project with uv and Python 3.14

- Add pyproject.toml with dependencies
- Add README.md with quick start
- Add AGENTS.md for development guide
- Configure ruff for linting/formatting
- Setup pytest for testing"
```

---

### Task 2: Configuration System

**Files:**
- Create: `src/bourbon/__init__.py`
- Create: `src/bourbon/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create src/bourbon/__init__.py**

```python
"""Bourbon - A personal programming assistant agent."""

__version__ = "0.1.0"
```

- [ ] **Step 2: Write test for config**

```python
"""Tests for configuration system."""

import os
import tempfile
from pathlib import Path

import pytest
import toml

from bourbon.config import Config, ConfigManager


class TestConfig:
    """Test configuration dataclass."""

    def test_default_config(self):
        """Test config with default values."""
        config = Config()
        assert config.llm.default_provider == "anthropic"
        assert config.ui.theme == "dracula"
        assert config.tools.bash.timeout_seconds == 120

    def test_config_from_dict(self):
        """Test loading config from dictionary."""
        data = {
            "llm": {
                "default_provider": "openai",
                "openai": {"api_key": "test-key", "model": "gpt-4o"},
            },
            "ui": {"theme": "monokai"},
        }
        config = Config.from_dict(data)
        assert config.llm.default_provider == "openai"
        assert config.llm.openai.api_key == "test-key"
        assert config.ui.theme == "monokai"


class TestConfigManager:
    """Test configuration manager."""

    def test_get_config_dir(self):
        """Test config directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            expected = Path(tmpdir) / ".bourbon"
            assert manager.get_config_dir() == expected

    def test_ensure_config_dir_creates_directory(self):
        """Test that ensure_config_dir creates the directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            manager.ensure_config_dir()
            assert manager.get_config_dir().exists()

    def test_create_default_config(self):
        """Test creating default config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            manager.ensure_config_dir()
            
            # Create with test API key
            config = manager.create_default_config(anthropic_key="test-ant-key")
            
            assert config.llm.anthropic.api_key == "test-ant-key"
            assert config.llm.default_provider == "anthropic"
            
            # Verify file was created
            config_path = manager.get_config_path()
            assert config_path.exists()
            
            # Verify it's valid TOML
            data = toml.load(config_path)
            assert data["llm"]["default_provider"] == "anthropic"

    def test_load_config(self):
        """Test loading existing config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            manager.ensure_config_dir()
            
            # Create config first
            manager.create_default_config(anthropic_key="my-key")
            
            # Load it
            config = manager.load_config()
            assert config.llm.anthropic.api_key == "my-key"

    def test_load_config_missing_file(self):
        """Test loading when config doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            manager.ensure_config_dir()
            
            # Should raise error with helpful message
            with pytest.raises(FileNotFoundError):
                manager.load_config()
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /home/hf/github_project/build-my-agent
uv run pytest tests/test_config.py -v
```

Expected: ImportError or ModuleNotFoundError for bourbon.config

- [ ] **Step 4: Implement config.py**

```python
"""Configuration management for Bourbon."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import toml


@dataclass
class AnthropicConfig:
    """Anthropic LLM configuration."""
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    base_url: str = "https://api.anthropic.com"
    max_tokens: int = 8000
    temperature: float = 0.7


@dataclass
class OpenAIConfig:
    """OpenAI LLM configuration."""
    api_key: str = ""
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    max_tokens: int = 8000
    temperature: float = 0.7


@dataclass
class LLMConfig:
    """LLM configuration container."""
    default_provider: str = "anthropic"
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)


@dataclass
class BashConfig:
    """Bash tool configuration."""
    allowed_commands: list[str] = field(default_factory=lambda: ["*"])
    blocked_commands: list[str] = field(default_factory=lambda: [
        "rm -rf /", "sudo", "shutdown", "reboot", "> /dev/sda"
    ])
    timeout_seconds: int = 120


@dataclass
class RgConfig:
    """ripgrep tool configuration."""
    binary_path: str = "rg"
    default_args: list[str] = field(default_factory=lambda: [
        "--smart-case", "--hidden", "--glob", "!.git"
    ])
    max_results: int = 100


@dataclass
class AstGrepConfig:
    """ast-grep tool configuration."""
    binary_path: str = "ast-grep"
    default_args: list[str] = field(default_factory=lambda: ["--json"])


@dataclass
class ToolsConfig:
    """Tools configuration container."""
    bash: BashConfig = field(default_factory=BashConfig)
    rg: RgConfig = field(default_factory=RgConfig)
    ast_grep: AstGrepConfig = field(default_factory=AstGrepConfig)


@dataclass
class UIConfig:
    """UI configuration."""
    theme: str = "dracula"
    auto_compact: bool = True
    token_threshold: int = 100000
    show_token_count: bool = True
    syntax_highlighting: bool = True


@dataclass
class Config:
    """Root configuration."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Create Config from dictionary."""
        llm_data = data.get("llm", {})
        anthropic_data = llm_data.get("anthropic", {})
        openai_data = llm_data.get("openai", {})
        
        tools_data = data.get("tools", {})
        bash_data = tools_data.get("bash", {})
        rg_data = tools_data.get("rg", {})
        ast_grep_data = tools_data.get("ast_grep", {})
        
        ui_data = data.get("ui", {})
        
        return cls(
            llm=LLMConfig(
                default_provider=llm_data.get("default_provider", "anthropic"),
                anthropic=AnthropicConfig(**anthropic_data),
                openai=OpenAIConfig(**openai_data),
            ),
            tools=ToolsConfig(
                bash=BashConfig(**bash_data),
                rg=RgConfig(**rg_data),
                ast_grep=AstGrepConfig(**ast_grep_data),
            ),
            ui=UIConfig(**ui_data),
        )

    def to_dict(self) -> dict:
        """Convert Config to dictionary."""
        return {
            "llm": {
                "default_provider": self.llm.default_provider,
                "anthropic": {
                    "api_key": self.llm.anthropic.api_key,
                    "model": self.llm.anthropic.model,
                    "base_url": self.llm.anthropic.base_url,
                    "max_tokens": self.llm.anthropic.max_tokens,
                    "temperature": self.llm.anthropic.temperature,
                },
                "openai": {
                    "api_key": self.llm.openai.api_key,
                    "model": self.llm.openai.model,
                    "base_url": self.llm.openai.base_url,
                    "max_tokens": self.llm.openai.max_tokens,
                    "temperature": self.llm.openai.temperature,
                },
            },
            "tools": {
                "bash": {
                    "allowed_commands": self.tools.bash.allowed_commands,
                    "blocked_commands": self.tools.bash.blocked_commands,
                    "timeout_seconds": self.tools.bash.timeout_seconds,
                },
                "rg": {
                    "binary_path": self.tools.rg.binary_path,
                    "default_args": self.tools.rg.default_args,
                    "max_results": self.tools.rg.max_results,
                },
                "ast_grep": {
                    "binary_path": self.tools.ast_grep.binary_path,
                    "default_args": self.tools.ast_grep.default_args,
                },
            },
            "ui": {
                "theme": self.ui.theme,
                "auto_compact": self.ui.auto_compact,
                "token_threshold": self.ui.token_threshold,
                "show_token_count": self.ui.show_token_count,
                "syntax_highlighting": self.ui.syntax_highlighting,
            },
        }


class ConfigManager:
    """Manages configuration files."""
    
    CONFIG_DIR_NAME = ".bourbon"
    CONFIG_FILE_NAME = "config.toml"
    
    def __init__(self, home_dir: Optional[Path] = None):
        """Initialize with optional home directory override."""
        self._home = home_dir or Path.home()
    
    def get_config_dir(self) -> Path:
        """Get configuration directory path."""
        return self._home / self.CONFIG_DIR_NAME
    
    def get_config_path(self) -> Path:
        """Get configuration file path."""
        return self.get_config_dir() / self.CONFIG_FILE_NAME
    
    def ensure_config_dir(self) -> Path:
        """Ensure configuration directory exists."""
        config_dir = self.get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir
    
    def create_default_config(
        self, 
        anthropic_key: str = "", 
        openai_key: str = ""
    ) -> Config:
        """Create default configuration file."""
        self.ensure_config_dir()
        
        config = Config()
        config.llm.anthropic.api_key = anthropic_key
        config.llm.openai.api_key = openai_key
        
        config_path = self.get_config_path()
        with open(config_path, "w") as f:
            toml.dump(config.to_dict(), f)
        
        # Secure the file
        config_path.chmod(0o600)
        
        return config
    
    def load_config(self) -> Config:
        """Load configuration from file."""
        config_path = self.get_config_path()
        
        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration not found at {config_path}\n"
                f"Run 'bourbon --init' to create one."
            )
        
        with open(config_path, "r") as f:
            data = toml.load(f)
        
        return Config.from_dict(data)
    
    def save_config(self, config: Config) -> None:
        """Save configuration to file."""
        self.ensure_config_dir()
        config_path = self.get_config_path()
        
        with open(config_path, "w") as f:
            toml.dump(config.to_dict(), f)
        
        config_path.chmod(0o600)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_config.py -v
```

Expected: All 6 tests pass

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/__init__.py src/bourbon/config.py tests/test_config.py
git commit -m "feat: Add configuration system

- Config dataclasses for all settings
- ConfigManager for file operations
- Support for Anthropic and OpenAI configs
- Tool-specific configurations (bash, rg, ast-grep)
- UI configuration options
- Comprehensive test coverage"
```

---

## Chunk 2: Todo Management and Tool Registry Foundation

### Task 3: Todo Management System

**Files:**
- Create: `src/bourbon/todos.py`
- Create: `tests/test_todos.py`

- [ ] **Step 1: Write tests for todos**

```python
"""Tests for todo management."""

import pytest

from bourbon.todos import TodoItem, TodoManager


class TestTodoItem:
    """Test TodoItem dataclass."""

    def test_create_todo(self):
        """Test creating a todo item."""
        todo = TodoItem(content="Test task", active_form="cli")
        assert todo.content == "Test task"
        assert todo.status == "pending"
        assert todo.active_form == "cli"

    def test_todo_to_dict(self):
        """Test converting todo to dictionary."""
        todo = TodoItem(content="Test", status="in_progress", active_form="repl")
        data = todo.to_dict()
        assert data == {
            "content": "Test",
            "status": "in_progress",
            "activeForm": "repl",
        }


class TestTodoManager:
    """Test TodoManager."""

    def test_empty_todos(self):
        """Test manager with no todos."""
        manager = TodoManager()
        assert manager.items == []
        assert not manager.has_open_items()
        assert manager.render() == "No todos."

    def test_update_single_todo(self):
        """Test updating with single todo."""
        manager = TodoManager()
        result = manager.update([
            {"content": "Task 1", "status": "pending", "activeForm": "cli"}
        ])
        assert len(manager.items) == 1
        assert manager.items[0].content == "Task 1"
        assert "Task 1" in result

    def test_update_multiple_todos(self):
        """Test updating with multiple todos."""
        manager = TodoManager()
        manager.update([
            {"content": "Task 1", "status": "completed", "activeForm": "cli"},
            {"content": "Task 2", "status": "in_progress", "activeForm": "repl"},
            {"content": "Task 3", "status": "pending", "activeForm": "cli"},
        ])
        assert len(manager.items) == 3
        render = manager.render()
        assert "[x] Task 1" in render
        assert "[>] Task 2 <- repl" in render
        assert "[ ] Task 3" in render
        assert "(1/3 completed)" in render

    def test_only_one_in_progress(self):
        """Test that only one todo can be in_progress."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="Only one in_progress allowed"):
            manager.update([
                {"content": "Task 1", "status": "in_progress", "activeForm": "a"},
                {"content": "Task 2", "status": "in_progress", "activeForm": "b"},
            ])

    def test_max_todos_limit(self):
        """Test maximum todo limit."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="Max 20 todos"):
            manager.update([
                {"content": f"Task {i}", "status": "pending", "activeForm": "cli"}
                for i in range(21)
            ])

    def test_content_required(self):
        """Test that content is required."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="content required"):
            manager.update([{"content": "", "status": "pending", "activeForm": "cli"}])

    def test_active_form_required(self):
        """Test that activeForm is required."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="activeForm required"):
            manager.update([{"content": "Task", "status": "pending", "activeForm": ""}])

    def test_invalid_status(self):
        """Test invalid status validation."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="invalid status"):
            manager.update([{"content": "Task", "status": "invalid", "activeForm": "cli"}])

    def test_has_open_items(self):
        """Test checking for open items."""
        manager = TodoManager()
        assert not manager.has_open_items()
        
        manager.update([
            {"content": "Task 1", "status": "completed", "activeForm": "cli"},
        ])
        assert not manager.has_open_items()
        
        manager.update([
            {"content": "Task 1", "status": "completed", "activeForm": "cli"},
            {"content": "Task 2", "status": "pending", "activeForm": "cli"},
        ])
        assert manager.has_open_items()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_todos.py -v
```

Expected: ImportError for bourbon.todos

- [ ] **Step 3: Implement todos.py**

```python
"""Todo management system."""

from dataclasses import dataclass, field


@dataclass
class TodoItem:
    """A single todo item."""
    content: str
    status: str = "pending"  # pending, in_progress, completed
    active_form: str = field(default="")

    def to_dict(self) -> dict:
        """Convert to dictionary for LLM communication."""
        return {
            "content": self.content,
            "status": self.status,
            "activeForm": self.active_form,
        }


class TodoManager:
    """Manages todo items for the agent."""
    
    MAX_TODOS = 20
    VALID_STATUSES = {"pending", "in_progress", "completed"}
    
    def __init__(self):
        """Initialize empty todo list."""
        self.items: list[TodoItem] = []
    
    def update(self, items: list[dict]) -> str:
        """Update todo list from LLM input.
        
        Args:
            items: List of todo dictionaries with content, status, activeForm
            
        Returns:
            Rendered todo list
            
        Raises:
            ValueError: If validation fails
        """
        validated: list[TodoItem] = []
        in_progress_count = 0
        
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()
            
            if not content:
                raise ValueError(f"Item {i}: content required")
            
            if status not in self.VALID_STATUSES:
                raise ValueError(f"Item {i}: invalid status '{status}'")
            
            if not active_form:
                raise ValueError(f"Item {i}: activeForm required")
            
            if status == "in_progress":
                in_progress_count += 1
            
            validated.append(TodoItem(
                content=content,
                status=status,
                active_form=active_form,
            ))
        
        if len(validated) > self.MAX_TODOS:
            raise ValueError(f"Max {self.MAX_TODOS} todos")
        
        if in_progress_count > 1:
            raise ValueError("Only one in_progress allowed")
        
        self.items = validated
        return self.render()
    
    def render(self) -> str:
        """Render todo list as formatted string."""
        if not self.items:
            return "No todos."
        
        lines = []
        for item in self.items:
            status_mark = {
                "completed": "[x]",
                "in_progress": ">",
                "pending": " ",
            }.get(item.status, "?")
            
            suffix = f" <- {item.active_form}" if item.status == "in_progress" else ""
            lines.append(f"[{status_mark}] {item.content}{suffix}")
        
        completed = sum(1 for t in self.items if t.status == "completed")
        lines.append(f"\n({completed}/{len(self.items)} completed)")
        
        return "\n".join(lines)
    
    def has_open_items(self) -> bool:
        """Check if there are any non-completed items."""
        return any(item.status != "completed" for item in self.items)
    
    def to_list(self) -> list[dict]:
        """Export todos as list of dictionaries."""
        return [item.to_dict() for item in self.items]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_todos.py -v
```

Expected: All 10 tests pass

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/todos.py tests/test_todos.py
git commit -m "feat: Add todo management system

- TodoItem dataclass with validation
- TodoManager for CRUD operations
- Render todos with status indicators
- Max 20 todos limit
- Only one in_progress allowed
- Full test coverage"
```

---

### Task 4: Tool Registry Foundation

**Files:**
- Create: `src/bourbon/tools/__init__.py`

- [ ] **Step 1: Create tools package**

```python
"""Tool system for Bourbon agent.

Tools are registered in a central registry and provided to the LLM.
Each tool has a name, description, input schema, and handler function.
"""

from dataclasses import dataclass
from typing import Any, Callable

# Type for tool handlers
ToolHandler = Callable[..., str]


@dataclass
class Tool:
    """Definition of a tool available to the agent."""
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    """Registry of available tools."""
    
    def __init__(self):
        """Initialize empty registry."""
        self._tools: dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def get_handler(self, name: str) -> ToolHandler | None:
        """Get a tool handler by name."""
        tool = self._tools.get(name)
        return tool.handler if tool else None
    
    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())
    
    def get_tool_definitions(self) -> list[dict]:
        """Get tool definitions for LLM API."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]


# Global registry instance
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get or create global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def register_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator to register a tool function.
    
    Example:
        @register_tool(
            name="bash",
            description="Run a shell command",
            input_schema={...},
        )
        def bash_handler(command: str) -> str:
            ...
    """
    def decorator(func: ToolHandler) -> ToolHandler:
        tool = Tool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=func,
        )
        get_registry().register(tool)
        return func
    return decorator


def tool(name: str) -> Tool | None:
    """Get a tool by name."""
    return get_registry().get(name)


def handler(name: str) -> ToolHandler | None:
    """Get a tool handler by name."""
    return get_registry().get_handler(name)


def definitions() -> list[dict]:
    """Get all tool definitions for LLM."""
    return get_registry().get_tool_definitions()
```

- [ ] **Step 2: Commit**

```bash
git add src/bourbon/tools/__init__.py
git commit -m "feat: Add tool registry foundation

- Tool dataclass for tool definitions
- ToolRegistry for managing tools
- @register_tool decorator
- Global registry singleton
- get_tool_definitions() for LLM API"
```

---

## Chunk 3: Base Tools (bash, read, write, edit)

### Task 5: Base Tool Implementation

**Files:**
- Create: `src/bourbon/tools/base.py`
- Create: `tests/test_tools_base.py`

- [ ] **Step 1: Write tests for base tools**

```python
"""Tests for base tools."""

import os
import tempfile
from pathlib import Path

import pytest

from bourbon.tools.base import (
    edit_file,
    read_file,
    run_bash,
    safe_path,
    write_file,
)


class TestSafePath:
    """Test path safety."""

    def test_valid_relative_path(self):
        """Test valid relative path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            result = safe_path("src/main.py", workdir)
            assert result == workdir / "src" / "main.py"

    def test_path_escapes_workspace(self):
        """Test path escaping workspace is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            with pytest.raises(ValueError, match="escapes workspace"):
                safe_path("../outside.txt", workdir)

    def test_absolute_path(self):
        """Test absolute path is handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            # Absolute path within workspace should work
            result = safe_path(f"{tmpdir}/file.txt", workdir)
            assert result == workdir / "file.txt"


class TestRunBash:
    """Test bash tool."""

    def test_simple_command(self):
        """Test simple echo command."""
        result = run_bash("echo hello")
        assert "hello" in result

    def test_blocked_dangerous_command(self):
        """Test dangerous commands are blocked."""
        result = run_bash("sudo ls")
        assert "blocked" in result.lower()
        
        result = run_bash("rm -rf /")
        assert "blocked" in result.lower()

    def test_timeout(self):
        """Test command timeout."""
        result = run_bash("sleep 10", timeout=1)
        assert "Timeout" in result

    def test_output_truncation(self):
        """Test large output is truncated."""
        result = run_bash("python3 -c \"print('x' * 100000)\"", max_output=1000)
        assert len(result) <= 1100  # Some buffer for truncation message


class TestReadFile:
    """Test read_file tool."""

    def test_read_existing_file(self):
        """Test reading an existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Hello, World!")
            
            result = read_file(str(test_file), workdir=Path(tmpdir))
            assert "Hello, World!" in result

    def test_read_nonexistent_file(self):
        """Test reading non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = read_file("nonexistent.txt", workdir=Path(tmpdir))
            assert "Error" in result

    def test_read_with_limit(self):
        """Test reading with line limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("\n".join(f"Line {i}" for i in range(100)))
            
            result = read_file(str(test_file), limit=10, workdir=Path(tmpdir))
            assert "Line 0" in result
            assert "Line 9" in result
            assert "more" in result


class TestWriteFile:
    """Test write_file tool."""

    def test_write_new_file(self):
        """Test writing a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_file("test.txt", "Hello!", workdir=Path(tmpdir))
            
            assert "Wrote" in result
            assert (Path(tmpdir) / "test.txt").read_text() == "Hello!"

    def test_create_directories(self):
        """Test that parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_file("a/b/c/test.txt", "Hello!", workdir=Path(tmpdir))
            
            assert "Wrote" in result
            assert (Path(tmpdir) / "a" / "b" / "c" / "test.txt").exists()

    def test_overwrite_existing(self):
        """Test overwriting existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Old content")
            
            result = write_file("test.txt", "New content", workdir=Path(tmpdir))
            
            assert "Wrote" in result
            assert test_file.read_text() == "New content"


class TestEditFile:
    """Test edit_file tool."""

    def test_simple_replace(self):
        """Test simple text replacement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Hello, World!")
            
            result = edit_file("test.txt", "World", "Bourbon", workdir=Path(tmpdir))
            
            assert "Edited" in result
            assert test_file.read_text() == "Hello, Bourbon!"

    def test_text_not_found(self):
        """Test when old_text is not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Hello, World!")
            
            result = edit_file("test.txt", "Missing", "Replacement", workdir=Path(tmpdir))
            
            assert "Error" in result
            assert "not found" in result

    def test_edit_nonexistent_file(self):
        """Test editing non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = edit_file("nonexistent.txt", "old", "new", workdir=Path(tmpdir))
            assert "Error" in result

    def test_only_first_occurrence(self):
        """Test that only first occurrence is replaced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("foo bar foo")
            
            result = edit_file("test.txt", "foo", "baz", workdir=Path(tmpdir))
            
            assert test_file.read_text() == "baz bar foo"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_base.py -v
```

Expected: ImportError for bourbon.tools.base

- [ ] **Step 3: Implement base.py**

```python
"""Base tools: bash, read, write, edit."""

import subprocess
from pathlib import Path

from bourbon.tools import register_tool


def safe_path(path: str, workdir: Path) -> Path:
    """Validate and resolve path within workspace.
    
    Args:
        path: Path string (relative or absolute)
        workdir: Workspace root directory
        
    Returns:
        Resolved Path object
        
    Raises:
        ValueError: If path escapes workspace
    """
    # Handle absolute paths
    if Path(path).is_absolute():
        resolved = Path(path).resolve()
    else:
        resolved = (workdir / path).resolve()
    
    # Check for path traversal
    try:
        resolved.relative_to(workdir.resolve())
    except ValueError as e:
        raise ValueError(f"Path escapes workspace: {path}") from e
    
    return resolved


def run_bash(
    command: str,
    workdir: Path | None = None,
    timeout: int = 120,
    max_output: int = 50000,
) -> str:
    """Run a shell command.
    
    Args:
        command: Shell command to run
        workdir: Working directory (default: current)
        timeout: Timeout in seconds
        max_output: Maximum output length
        
    Returns:
        Command output or error message
    """
    cwd = workdir or Path.cwd()
    
    # Security checks
    dangerous = ["rm -rf /", "sudo ", "shutdown", "reboot", "> /dev/sda", "mkfs."]
    for d in dangerous:
        if d in command:
            return f"Error: Dangerous command blocked ({d})"
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        
        if not output:
            return "(no output)"
        
        if len(output) > max_output:
            output = output[:max_output] + f"\n... ({len(output) - max_output} more chars)"
        
        return output
        
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s)"
    except Exception as e:
        return f"Error: {e}"


def read_file(
    path: str,
    workdir: Path | None = None,
    limit: int | None = None,
    max_output: int = 50000,
) -> str:
    """Read file contents.
    
    Args:
        path: File path (relative to workdir)
        workdir: Workspace root
        limit: Maximum lines to read
        max_output: Maximum characters to return
        
    Returns:
        File contents or error message
    """
    cwd = workdir or Path.cwd()
    
    try:
        fp = safe_path(path, cwd)
        
        if not fp.exists():
            return f"Error: File not found: {path}"
        
        if not fp.is_file():
            return f"Error: Not a file: {path}"
        
        lines = fp.read_text().splitlines()
        
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        
        content = "\n".join(lines)
        
        if len(content) > max_output:
            content = content[:max_output] + f"\n... ({len(content) - max_output} more chars)"
        
        return content
        
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error reading {path}: {e}"


def write_file(
    path: str,
    content: str,
    workdir: Path | None = None,
) -> str:
    """Write content to file.
    
    Args:
        path: File path (relative to workdir)
        content: Content to write
        workdir: Workspace root
        
    Returns:
        Success or error message
    """
    cwd = workdir or Path.cwd()
    
    try:
        fp = safe_path(path, cwd)
        
        # Create parent directories
        fp.parent.mkdir(parents=True, exist_ok=True)
        
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
        
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error writing {path}: {e}"


def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    workdir: Path | None = None,
) -> str:
    """Replace text in file.
    
    Args:
        path: File path
        old_text: Text to find
        new_text: Text to replace with
        workdir: Workspace root
        
    Returns:
        Success or error message
    """
    cwd = workdir or Path.cwd()
    
    try:
        fp = safe_path(path, cwd)
        
        if not fp.exists():
            return f"Error: File not found: {path}"
        
        content = fp.read_text()
        
        if old_text not in content:
            return f"Error: Text not found in {path}"
        
        # Replace only first occurrence
        new_content = content.replace(old_text, new_text, 1)
        fp.write_text(new_content)
        
        return f"Edited {path}"
        
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error editing {path}: {e}"


# Register tools with schemas
@register_tool(
    name="bash",
    description="Run a shell command in the workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
        },
        "required": ["command"],
    },
)
def bash_tool(command: str) -> str:
    """Tool handler for bash."""
    return run_bash(command)


@register_tool(
    name="read_file",
    description="Read the contents of a file.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file (relative to workspace)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
            },
        },
        "required": ["path"],
    },
)
def read_file_tool(path: str, limit: int | None = None) -> str:
    """Tool handler for read_file."""
    return read_file(path, limit=limit)


@register_tool(
    name="write_file",
    description="Write content to a file (creates directories if needed).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file",
            },
            "content": {
                "type": "string",
                "description": "Content to write",
            },
        },
        "required": ["path", "content"],
    },
)
def write_file_tool(path: str, content: str) -> str:
    """Tool handler for write_file."""
    return write_file(path, content)


@register_tool(
    name="edit_file",
    description="Replace exact text in a file (only first occurrence).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file",
            },
            "old_text": {
                "type": "string",
                "description": "Text to find",
            },
            "new_text": {
                "type": "string",
                "description": "Text to replace with",
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
)
def edit_file_tool(path: str, old_text: str, new_text: str) -> str:
    """Tool handler for edit_file."""
    return edit_file(path, old_text, new_text)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_tools_base.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/tools/base.py tests/test_tools_base.py
git commit -m "feat: Add base tools (bash, read, write, edit)

- safe_path() for path sandboxing
- run_bash() with security blacklist
- read_file() with line limits
- write_file() with auto-directory creation
- edit_file() for precise text replacement
- @register_tool decorators for all tools
- Comprehensive test coverage"
```

---

## Chunk 4: Search Tools (rg, ast-grep)

### Task 6: Search Tools Implementation

**Files:**
- Create: `src/bourbon/tools/search.py`
- Create: `tests/test_tools_search.py`

- [ ] **Step 1: Write tests for search tools**

```python
"""Tests for search tools."""

import json
import tempfile
from pathlib import Path

import pytest

from bourbon.tools.search import rg_search, ast_grep_search


class TestRgSearch:
    """Test ripgrep search tool."""

    def test_simple_search(self):
        """Test simple text search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "test.py").write_text("def hello(): pass\n")
            (Path(tmpdir) / "other.txt").write_text("hello world\n")
            
            result = rg_search("hello", path=tmpdir)
            
            assert "test.py" in result
            assert "other.txt" in result
            assert "hello" in result

    def test_regex_search(self):
        """Test regex pattern search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("def foo(): pass\ndef bar(): pass\n")
            
            result = rg_search(r"def \w+", path=tmpdir)
            
            assert "def foo" in result
            assert "def bar" in result

    def test_glob_filter(self):
        """Test file glob filtering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("hello\n")
            (Path(tmpdir) / "test.txt").write_text("hello\n")
            
            result = rg_search("hello", path=tmpdir, glob="*.py")
            
            assert "test.py" in result
            assert "test.txt" not in result

    def test_case_sensitive(self):
        """Test case sensitivity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.txt").write_text("Hello\nHELLO\nhello\n")
            
            # Case sensitive should find exact match
            result = rg_search("Hello", path=tmpdir, case_sensitive=True)
            # Should match only "Hello" not "HELLO" or "hello"

    def test_max_results(self):
        """Test max results limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(10):
                (Path(tmpdir) / f"file{i}.txt").write_text("target\n")
            
            result = rg_search("target", path=tmpdir, max_results=5)
            
            # Should indicate truncation
            assert "truncated" in result.lower() or "more" in result.lower()

    def test_no_matches(self):
        """Test when no matches found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.txt").write_text("content\n")
            
            result = rg_search("nonexistent", path=tmpdir)
            
            assert "No matches" in result


class TestAstGrepSearch:
    """Test ast-grep search tool."""

    def test_find_function_definitions(self):
        """Test finding function definitions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("""
def hello():
    pass

def world(x, y):
    return x + y
""")
            
            result = ast_grep_search("def $FUNC($$$ARGS):", path=tmpdir, language="python")
            
            # Should find both functions
            assert "hello" in result or "world" in result

    def test_find_class_definitions(self):
        """Test finding class definitions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("""
class MyClass:
    pass

class OtherClass(Base):
    pass
""")
            
            result = ast_grep_search("class $NAME:", path=tmpdir, language="python")
            
            assert "MyClass" in result or "OtherClass" in result

    def test_no_matches(self):
        """Test when no matches found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("x = 1\n")
            
            result = ast_grep_search("class $NAME:", path=tmpdir, language="python")
            
            assert "No matches" in result

    def test_invalid_pattern(self):
        """Test invalid pattern handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("x = 1\n")
            
            result = ast_grep_search("not a valid pattern $$$", path=tmpdir, language="python")
            
            # Should handle gracefully
            assert "Error" in result or "No matches" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_search.py -v
```

Expected: ImportError for bourbon.tools.search

- [ ] **Step 3: Implement search.py**

```python
"""Search tools: ripgrep and ast-grep integration."""

import json
import shutil
import subprocess
from pathlib import Path

from bourbon.tools import register_tool


def rg_search(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    case_sensitive: bool = False,
    context_lines: int = 2,
    max_results: int = 100,
) -> str:
    """Search files using ripgrep.
    
    Args:
        pattern: Regex pattern to search
        path: Directory or file to search
        glob: File glob pattern (e.g., '*.py')
        case_sensitive: Whether to match case
        context_lines: Lines of context to include
        max_results: Maximum number of matches
        
    Returns:
        Search results or error message
    """
    # Check if rg is available
    if not shutil.which("rg"):
        return "Error: ripgrep (rg) not found. Please install it."
    
    cmd = ["rg", "--json", "--context", str(context_lines)]
    
    if not case_sensitive:
        cmd.append("--smart-case")
    else:
        cmd.append("--case-sensitive")
    
    if glob:
        cmd.extend(["--glob", glob])
    
    # Add default excludes
    cmd.extend(["--glob", "!.git"])
    
    cmd.extend([pattern, path])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        if result.returncode not in (0, 1):  # 0 = matches, 1 = no matches
            return f"Error: rg failed with code {result.returncode}: {result.stderr}"
        
        if not result.stdout.strip():
            return f"No matches for '{pattern}'"
        
        # Parse JSON lines
        matches = []
        current_match = {}
        
        for line in result.stdout.strip().split("\n"):
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data.get("data", {})
                    file_path = match_data.get("path", {}).get("text", "")
                    line_num = match_data.get("line_number", 0)
                    
                    # Extract matched lines
                    lines = []
                    for submatch in match_data.get("submatches", []):
                        for l in match_data.get("lines", {}).get("text", "").split("\n"):
                            if l:
                                lines.append(l)
                    
                    if lines:
                        matches.append({
                            "file": file_path,
                            "line": line_num,
                            "content": lines[0] if lines else "",
                        })
            except json.JSONDecodeError:
                continue
        
        if not matches:
            return f"No matches for '{pattern}'"
        
        # Format output
        truncated = len(matches) > max_results
        matches = matches[:max_results]
        
        lines = [f"Found {len(matches)} matches for '{pattern}':\n"]
        for m in matches:
            lines.append(f"{m['file']}:{m['line']}: {m['content']}")
        
        if truncated:
            lines.append(f"\n... (results truncated to {max_results})")
        
        return "\n".join(lines)
        
    except subprocess.TimeoutExpired:
        return "Error: Search timed out (60s)"
    except Exception as e:
        return f"Error during search: {e}"


def ast_grep_search(
    pattern: str,
    path: str = ".",
    language: str | None = None,
    max_results: int = 100,
) -> str:
    """Search code using ast-grep.
    
    Args:
        pattern: ast-grep pattern (e.g., 'class $NAME:')
        path: Directory or file to search
        language: Language hint (python, javascript, etc.)
        max_results: Maximum number of matches
        
    Returns:
        Search results or error message
        
    Pattern examples:
        - 'class $NAME:' - Find class definitions
        - 'def $FUNC($$$ARGS):' - Find function definitions
        - '$VAR = $EXPR' - Find assignments
    """
    # Check if ast-grep is available
    if not shutil.which("ast-grep"):
        return "Error: ast-grep not found. Please install it: https://ast-grep.github.io/"
    
    cmd = ["ast-grep", "run", "--json", pattern]
    
    if language:
        cmd.extend(["--lang", language])
    
    cmd.append(path)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        # Parse JSON output
        try:
            matches = json.loads(result.stdout) if result.stdout.strip() else []
            if not isinstance(matches, list):
                matches = [matches] if matches else []
        except json.JSONDecodeError:
            return f"No matches for pattern '{pattern}'"
        
        if not matches:
            return f"No matches for pattern '{pattern}'"
        
        # Format output
        truncated = len(matches) > max_results
        matches = matches[:max_results]
        
        lines = [f"Found {len(matches)} AST matches for '{pattern}':\n"]
        for m in matches:
            file_path = m.get("file", "")
            line = m.get("range", {}).get("start", {}).get("line", 0)
            text = m.get("text", "").replace("\n", " ")[:100]
            lines.append(f"{file_path}:{line}: {text}")
        
        if truncated:
            lines.append(f"\n... (results truncated to {max_results})")
        
        return "\n".join(lines)
        
    except subprocess.TimeoutExpired:
        return "Error: Search timed out (60s)"
    except Exception as e:
        return f"Error during search: {e}"


# Register tools
@register_tool(
    name="rg_search",
    description="Search files using ripgrep (regex-based text search).",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search (default: current directory)",
            },
            "glob": {
                "type": "string",
                "description": "File glob pattern, e.g., '*.py'",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case-sensitive search",
            },
        },
        "required": ["pattern"],
    },
)
def rg_search_tool(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    case_sensitive: bool = False,
) -> str:
    """Tool handler for rg_search."""
    return rg_search(pattern, path, glob, case_sensitive)


@register_tool(
    name="ast_grep_search",
    description="Search code using ast-grep (structural/AST-based search).",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "ast-grep pattern (e.g., 'class $NAME:', 'def $FUNC($$$ARGS):')",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search",
            },
            "language": {
                "type": "string",
                "description": "Language hint (python, javascript, rust, etc.)",
            },
        },
        "required": ["pattern"],
    },
)
def ast_grep_search_tool(
    pattern: str,
    path: str = ".",
    language: str | None = None,
) -> str:
    """Tool handler for ast_grep_search."""
    return ast_grep_search(pattern, path, language)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_tools_search.py -v
```

Expected: Tests pass (may skip if rg/ast-grep not installed)

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/tools/search.py tests/test_tools_search.py
git commit -m "feat: Add search tools (rg, ast-grep)

- rg_search() for regex-based text search
- ast_grep_search() for AST-based structural search
- JSON output parsing for structured results
- Result truncation and formatting
- Tool registration with schemas
- Tests with temp directory fixtures"
```

---

**Plan complete and saved to `docs/plans/2026-03-19-bourbon-stage-a-implementation.md`. Ready to execute?**

This plan covers the foundation (project setup, config, todos, tools). After completing these chunks, we'll need additional plans for:
- Chunk 5: Skills system
- Chunk 6: Context compression
- Chunk 7: LLM client
- Chunk 8: Agent loop
- Chunk 9: REPL interface
- Chunk 10: CLI entry point and integration

Do you want to proceed with executing this plan, or would you like to review/modify anything first?
