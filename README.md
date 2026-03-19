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
🥃 bourbon >> 分析这个项目的代码结构

> rg_search: 在 12 个文件中找到 42 处匹配
> read_file: 读取 src/bourbon/agent.py (150 行)

根据搜索结果，这个项目使用了标准的 Python 包结构...

🥃 bourbon >> /tasks
[ ] 1: 分析项目结构
[>] 2: 重构 main.py <- 正在处理

🥃 bourbon >> /exit
```

## Roadmap

- **Stage A** (Current): Code Specialist - refactoring, analysis, code review
- **Stage B**: General Assistant - web, documents, data analysis, writing
- **Stage C**: Autonomous Workflows - self-directed, multi-domain tasks

## License

MIT
