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
