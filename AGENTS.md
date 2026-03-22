# AGENTS.md

Development guide for AI agents working on Bourbon.

## Project Vision

**Bourbon is a general-purpose agent platform** with a code-first evolution:
- **Stage A (Completed)**: Perfect code capabilities - search, refactoring, analysis
- **Stage B (Current)**: Expand to general knowledge work - documents, web, data, investment analysis
- **Stage C**: Autonomous workflows across all domains

## Stage B Focus: General-Purpose Agent

Bourbon has evolved from a code specialist to a general-purpose agent capable of:
- **Software Engineering**: Code search, refactoring, analysis (Stage A capabilities)
- **Domain Expertise via Skills**: Investment analysis, project management, and more
- **External Integrations**: MCP Client for databases, APIs, and external tools
- **Knowledge Work**: Documents, web, data analysis
- **Safe Operations**: Sandboxed file operations, risk-based error handling
- **Context Management**: Long session support with compression

### Key Capabilities

1. **Core Tools**: File operations, code search, bash execution, todo management
2. **Skill System**: Agent Skills compatible - progressive disclosure, multi-scope discovery
3. **MCP Integration**: External tool servers for extended capabilities
4. **Eval Framework**: Comprehensive testing for skills, safety, and performance

## Project Structure

- `src/bourbon/`: Main source code
  - `cli.py`: Entry point
  - `config.py`: Configuration management (~/.bourbon/)
  - `llm.py`: Multi-provider LLM client
  - `repl.py`: REPL interface optimized for code
  - `agent.py`: Core agent loop
  - `mcp_client/`: MCP Client implementation
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

## MCP Client Integration

Bourbon integrates the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) to connect with external tool servers.

### Architecture

```
Config ([mcp] section)
       ↓
MCPManager (connect_all)
       ↓
ToolRegistry (register MCP tools with server: prefix)
       ↓
Agent (transparent tool usage)
```

### MCP Configuration

Add to `~/.bourbon/config.toml`:

```toml
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

MCP tools are registered with the format: `{server_name}:{tool_name}`

Example:
- Server: `fetch`
- Tool: `fetch_url`
- Registered name: `fetch:fetch_url`

### Risk Level

All MCP tools default to `RiskLevel.MEDIUM` since they are external operations.

### Implementation Notes

- `MCPManager` is initialized in `Agent.__init__()`
- `Agent.initialize_mcp()` must be called to establish connections
- Connection results are stored and can be viewed with `/mcp` command
- Failed connections don't block other servers from connecting

### Testing

```bash
# Run MCP-specific tests
pytest tests/test_mcp_config.py tests/test_mcp_manager.py -v
```

## Adding New Tools

1. Define tool schema in `tools/__init__.py`
2. Implement handler in appropriate module
3. Register in tool registry
4. Add tests

## Adding MCP Servers

MCP servers provide external tools without code changes:

1. Install the MCP server (e.g., `npm install -g @github/mcp-server`)
2. Add configuration to `~/.bourbon/config.toml`
3. Restart Bourbon
4. Use tools with `server:tool` syntax

---

## Stage B Capabilities (General Assistant)

Bourbon has expanded from code specialist to general knowledge worker with new Stage B capabilities:

### New Tools and Skills

| Domain | Tool | Skill | Description |
|--------|------|-------|-------------|
| **Web** | `fetch_url` | `web-fetch` | Fetch content from URLs with safety limits |
| **Data** | `csv_analyze`, `json_query` | `data-analysis` | Analyze CSV/JSON with statistics |
| **Documents** | `pdf_to_text`, `docx_to_markdown` | `document-parse` | Extract text from PDF/Word |
| **Writing** | - | `report-gen` | Generate markdown reports from templates |

### Usage Examples

```bash
# Fetch web content
> skill("web-fetch", url="https://example.com")

# Analyze CSV file
> skill("data-analysis", file="sales.csv", operations=["summary", "groupby:product"])

# Extract PDF text
> skill("document-parse", file="report.pdf", type="pdf")

# Generate report
> skill("report-gen", title="Sales Analysis", data=sales_data)
```

### Mixed Workflow Example

```python
# Complete workflow: Analyze CSV → Fetch web data → Generate report
sales = skill("data-analysis", file="sales.csv", operations=["summary"])
competitor = skill("web-fetch", url="https://competitor.com/pricing")
report = skill("report-gen", 
               title="Competitive Analysis",
               sections=[
                   {"heading": "Our Sales", "content": str(sales['stats'])},
                   {"heading": "Competitor Pricing", "content": competitor['text'][:1000]}
               ])
```

### Tool Reference

**Web Tools** (`src/bourbon/tools/web.py`):
- `fetch_url(url, timeout=30, max_length=100000)` - Fetch URL with safety limits

**Data Tools** (`src/bourbon/tools/data.py`):
- `csv_analyze(file_path, operations=["summary"])` - Analyze CSV statistics
- `json_query(file_path, query="path.to.value")` - Query JSON with dot notation

**Document Tools** (`src/bourbon/tools/documents.py`):
- `pdf_to_text(file_path, page_range=None)` - Extract PDF text
- `docx_to_markdown(file_path)` - Convert Word to markdown

### Installation

Stage B requires additional dependencies:

```bash
uv pip install -e ".[stage-b]"
```

This installs: pandas, pypdf, python-docx, jinja2, aiohttp, beautifulsoup4

---

## Investment Skill Optimization

The investment-agent skill has been optimized for **50-100x performance improvement**.

### Performance Results

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Fund Monitor (12 funds) | 120-180s | **0.6s** | **200-300x** |
| Single fund query | 10-15s | **0.1s** | **100x** |
| Batch 3 funds | 30-45s | **0.2s** | **150x** |
| Cache hit | N/A | **<0.01s** | **1000x** |

### Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Fast API      │────▶│  Fund Monitor    │◀────│  Playwright     │
│  (83% coverage) │     │   (Optimized)    │     │  (17% fallback) │
│   0.1s/fund     │     │                  │     │   5-10s/fund    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌──────────────────┐
│ HTTP Direct     │     │ Hybrid Collector │
│ No browser      │     │ Smart fallback   │
└─────────────────┘     └──────────────────┘
```

### Key Optimizations

1. **Fast Collector** (`collectors/fast_collector.py`)
   - HTTP API direct access (replaces Playwright)
   - Concurrent fetching with ThreadPoolExecutor
   - Automatic caching with `@cached` decorator

2. **Hybrid Collector** (`collectors/hybrid_collector.py`)
   - Fast API first (83% of funds)
   - Playwright fallback for edge cases (17% of funds)
   - Transparent to calling code

3. **Optimized Fund Monitor** (`skills/fund_monitor/__init__.py`)
   - Uses Fast Collector for batch operations
   - Reduced from 34s to 0.6s for 12 funds

### Coverage Analysis

- **Fast API works for**: 10/12 portfolio funds (83%)
- **Playwright needed for**: 2/12 funds (17%)
  - `019455` - 华泰柏瑞中韩半导体ETF联接C
  - `007910` - 大成有色金属期货ETF联接A

These funds return empty data from the JSONP API but have data on the HTML page.

### Usage

```python
# Fast Collector - for 83% of funds
from collectors.fast_collector import fetch_funds_batch
funds = fetch_funds_batch(['000216', '013402', ...])  # ~0.1s per fund

# Hybrid Collector - for 100% coverage
from collectors.hybrid_collector import fetch_funds
funds = fetch_funds(['019455', '000216', ...])  # Auto-fallback
```

### Documentation

- `evals/INVESTMENT_SKILL_PERFORMANCE_ANALYSIS.md` - Detailed analysis
- `evals/INVESTMENT_SKILL_OPTIMIZATION_PATCH.md` - Implementation guide
- `apply_investment_optimization.sh` - One-click apply script
