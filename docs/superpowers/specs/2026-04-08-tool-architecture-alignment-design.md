# Bourbon Tool 架构对齐 Claude Code 设计文档

**日期**：2026-04-08  
**状态**：待实施  
**方案**：分层演进（Layered Evolution）

---

## 背景与目标

Bourbon agent 的工具系统与 Claude Code 架构存在以下差距：

1. `Tool` 类缺少 `always_load`、`should_defer`、`is_concurrency_safe`、`is_read_only`、`is_destructive` 等属性
2. 工具命名采用 snake_case（`read_file`、`rg_search`），与 Claude Code PascalCase 风格不一致
3. 所有工具始终全量加载进 prompt，无 deferred 按需发现机制
4. 各工具 handler 通过零散的 `workdir` kwarg 接收上下文，没有统一执行上下文对象
5. 缺少 `Glob` 和 `ToolSearch` 工具

**目标**：参考 Claude Code 架构，全面重构 bourbon 的 built-in tool 系统，包含 Stage-B 工具（web/data/documents）。

---

## 范围

- `src/bourbon/tools/` 目录全部文件
- `src/bourbon/agent.py`（deferred 发现逻辑）
- **不涉及**：并发执行（bourbon 保持同步顺序执行）

---

## 设计方案（分层演进 B）

### 步骤一：Tool 类型系统 & ToolContext

#### 1.1 ToolContext

新增 `ToolContext` 数据类，统一执行上下文，替换各处零散的 `workdir` kwarg：

```python
@dataclass
class ToolContext:
    workdir: Path
    on_tools_discovered: Callable[[set[str]], None] | None = None
```

说明：`on_tools_discovered` 是回调，供 `ToolSearch` 工具在发现新工具后通知 Agent（见步骤三）。

#### 1.2 Tool 新增字段

```python
@dataclass
class Tool:
    # 现有字段（保持）
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler          # 签名统一为 (**kwargs, ctx: ToolContext) -> str
    risk_level: RiskLevel = RiskLevel.LOW
    risk_patterns: list[str] | None = None
    required_capabilities: list[str] | None = None

    # 新增字段
    aliases: list[str] = field(default_factory=list)   # 向后兼容旧工具名
    always_load: bool = True        # False 的工具不默认进入 prompt
    should_defer: bool = False      # True = 需要 ToolSearch 才可用（隐含 always_load=False）
    is_concurrency_safe: bool = False   # 并发安全标注（暂不影响执行）
    is_read_only: bool = False
    is_destructive: bool = False
    search_hint: str | None = None  # ToolSearch 额外匹配关键词（+4 分）
```

**`__post_init__` 中的硬编码工具名修复**：当前 `__post_init__` 用 `self.name == "bash"` 判断是否设置默认 risk_patterns。重构后改为检查 `is_destructive` 属性：

```python
def __post_init__(self):
    if self.risk_patterns is None:
        if self.risk_level == RiskLevel.HIGH and self.is_destructive:
            self.risk_patterns = [...危险命令列表...]
        else:
            self.risk_patterns = []

def is_high_risk_operation(self, tool_input: dict) -> bool:
    if self.risk_level == RiskLevel.HIGH and self.is_destructive:
        command = tool_input.get("command", "")
        return any(pattern in command for pattern in self.risk_patterns)
    return self.risk_level == RiskLevel.HIGH
```

`Bash` 工具注册时显式传入 `is_destructive=True`，不再依赖名称判断。

#### 1.3 register_tool 装饰器更新签名

`register_tool()` 是所有工具注册的唯一入口，需同步新增参数：

```python
def register_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    risk_level: RiskLevel = RiskLevel.LOW,
    risk_patterns: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    # 新增参数
    aliases: list[str] | None = None,
    always_load: bool = True,
    should_defer: bool = False,
    is_concurrency_safe: bool = False,
    is_read_only: bool = False,
    is_destructive: bool = False,
    search_hint: str | None = None,
) -> Callable[[ToolHandler], ToolHandler]: ...
```

#### 1.4 ToolRegistry 重构

新增 `_alias_map` 并在 `register()` 时同步维护：

```python
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._alias_map: dict[str, str] = {}  # alias -> canonical name

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            self._alias_map[alias] = tool.name   # alias → 主名

    def _resolve(self, name: str) -> Tool | None:
        """按主名或 alias 查找工具。"""
        if name in self._tools:
            return self._tools[name]
        canonical = self._alias_map.get(name)
        return self._tools.get(canonical) if canonical else None

    def call(self, name: str, tool_input: dict, ctx: ToolContext) -> str:
        """调用工具，注入 ToolContext。"""
        tool = self._resolve(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        return tool.handler(**tool_input, ctx=ctx)

    def get_tool_definitions(
        self,
        discovered: set[str] | None = None,
    ) -> list[dict]:
        """
        返回工具定义列表。
        - always_load=True 的工具始终包含
        - should_defer=True 的工具只在 name in discovered 时包含
        """
        discovered = discovered or set()
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
            if t.always_load or t.name in discovered
        ]
```

#### 1.5 Handler 签名统一

所有工具 handler 改为 keyword-only `ctx` 参数：

```python
# 重构前（各不相同）
def bash_tool(command: str, workdir: Path | None = None) -> str: ...
def read_file_tool(path: str, limit: int | None = None, workdir: Path | None = None) -> str: ...

# 重构后（统一 ctx 注入）
def bash_handler(command: str, *, ctx: ToolContext) -> str:
    return run_bash(command, workdir=ctx.workdir)

def read_handler(path: str, limit: int | None = None, *, ctx: ToolContext) -> str:
    return read_file(path, workdir=ctx.workdir, limit=limit)
```

#### 1.6 definitions() 顶层函数更新

```python
def definitions(discovered: set[str] | None = None) -> list[dict]:
    from bourbon.tools import base, search, skill_tool, tool_search  # noqa: F401
    return get_registry().get_tool_definitions(discovered=discovered)
```

---

### 步骤二：工具重命名 & 完整工具集

#### 核心工具（always_load=True）

| 旧名称 | 新名称 | aliases | is_read_only | is_destructive | is_concurrency_safe |
|--------|--------|---------|:------------:|:--------------:|:-------------------:|
| `bash` | `Bash` | `["bash"]` | ❌ | ✅ | ❌ |
| `read_file` | `Read` | `["read_file"]` | ✅ | ❌ | ✅ |
| `write_file` | `Write` | `["write_file"]` | ❌ | ❌ | ❌ |
| `edit_file` | `Edit` | `["edit_file"]` | ❌ | ❌ | ❌ |
| `rg_search` | `Grep` | `["rg_search"]` | ✅ | ❌ | ✅ |
| `ast_grep_search` | `AstGrep` | `["ast_grep_search"]` | ✅ | ❌ | ✅ |
| `skill` | `Skill` | `["skill"]` | ✅ | ❌ | ❌ |
| `skill_read_resource` | `SkillResource` | `["skill_read_resource"]` | ✅ | ❌ | ✅ |
| *(新增)* | `Glob` | — | ✅ | ❌ | ✅ |
| *(新增)* | `ToolSearch` | — | ✅ | ❌ | ✅ |

**新增 `Glob` 工具**（文件模式匹配，对齐 Claude Code GlobTool），新文件不需要单独创建，加入 `search.py`：

```python
# 输入
{ "pattern": "**/*.py", "path": "." }
# 输出：匹配的文件路径列表（换行分隔），超出 100 个截断
```

实现：使用 Python 内置 `pathlib.Path.glob()`，路径相对于 `ctx.workdir`。

#### Stage-B 工具（should_defer=True, always_load=False）

完整的旧名到新名映射：

| 模块 | 旧名称 | 新名称 | aliases |
|------|--------|--------|---------|
| `web.py` | `fetch_url` | `WebFetch` | `["fetch_url"]` |
| `data.py` | `csv_analyze` | `CsvAnalyze` | `["csv_analyze"]` |
| `data.py` | `json_query` | `JsonQuery` | `["json_query"]` |
| `documents.py` | `pdf_to_text` | `PdfRead` | `["pdf_to_text"]` |
| `documents.py` | `docx_to_markdown` | `DocxRead` | `["docx_to_markdown"]` |

所有 Stage-B 工具注册时加 `should_defer=True, always_load=False`。  
导入策略不变：依赖未安装时跳过注册（try/except ImportError）。

---

### 步骤三：Deferred 工具发现机制 & Agent 修改

#### 3.1 ToolSearch 工具

新文件 `src/bourbon/tools/tool_search.py`，注册 `ToolSearch` 工具（`always_load=True`）：

```python
# 输入
{ "query": "web search", "max_results": 5 }

# 输出（文本格式）
Found 2 tools matching "web search":

- WebFetch: Fetch and extract content from a URL

These tools are now available for use.
```

**评分逻辑**（参考 Claude Code ToolSearchTool，仅搜索 `should_defer=True` 的工具）：

- 工具名包含查询词：+10
- `search_hint` 匹配：+4
- description 包含查询词：+2

**副作用**：调用 `ctx.on_tools_discovered(matched_names)` 通知 Agent：

```python
def tool_search_handler(query: str, max_results: int = 5, *, ctx: ToolContext) -> str:
    registry = get_registry()
    deferred = [t for t in registry.list_tools() if t.should_defer]
    scored = [(score(t, query), t) for t in deferred]
    matches = [t for _, t in sorted(scored, reverse=True) if _ > 0][:max_results]
    
    if ctx.on_tools_discovered and matches:
        ctx.on_tools_discovered({t.name for t in matches})
    
    if not matches:
        return f"No tools found matching '{query}'"
    
    lines = [f"Found {len(matches)} tools matching '{query}':\n"]
    for t in matches:
        lines.append(f"- {t.name}: {t.description}")
    lines.append("\nThese tools are now available for use.")
    return "\n".join(lines)
```

#### 3.2 Agent 修改

**新增 `_discovered_tools` 状态**：

```python
class Agent:
    def __init__(self, ...):
        self._discovered_tools: set[str] = set()
```

**`_make_tool_context()` 方法**：

```python
def _make_tool_context(self) -> ToolContext:
    return ToolContext(
        workdir=self.workdir,
        on_tools_discovered=self._discovered_tools.update,
    )
```

**`_execute_tools()` 改为通过 registry 调用**：

```python
def _execute_tools(self, tool_calls: list[dict]) -> list[dict]:
    ctx = self._make_tool_context()
    results = []
    for call in tool_calls:
        result = get_registry().call(call["name"], call["input"], ctx)
        results.append({"tool_use_id": call["id"], "content": result})
    return results
```

**`definitions()` 调用点**（agent.py 中有 3 处，行号约 461、465、680，全部更新）：

```python
# 改前
from bourbon.tools import definitions
tools = definitions()

# 改后
from bourbon.tools import definitions
tools = definitions(discovered=self._discovered_tools)
```

**hardcoded 工具名检查修复**（agent.py 中 4 处）：

```python
# 行 868：bash 沙箱路由
# 改前：if tool_name == "bash" and ...
# 改后：通过 tool.is_destructive 判断，或通过 _resolve 检查
tool = get_registry()._resolve(tool_name)
if tool and tool.is_destructive and getattr(self.sandbox, "enabled", False):
    ...

# 行 884：路由到沙箱的工具类型
# 改前：if tool_name in {"bash", "read_file", "write_file", "edit_file"}:
# 改后：if tool and not tool.is_read_only:  # 非只读工具走沙箱路由
    ...

# 行 947：skill 工具的手动分支（backward-compat 路径）
# 该分支在 aliases 机制生效后可以删除，重构时一并移除
# 确认 Skill 工具通过 registry 正常路由即可

# 行 1002：bash 风险检查
# 改前：if tool_name == "bash":
# 改后：通过 tool.is_high_risk_operation(tool_input) 直接判断（Tool 方法，不依赖名称）
if tool and tool.is_high_risk_operation(tool_input):
    ...

# 行 1024：_generate_options() 中的错误提示生成
# 改前：elif tool_name in ("write_file", "edit_file"):
# 改后：elif tool and not tool.is_read_only and not tool.is_destructive:
# 该处影响用户看到的错误提示文案，重命名后必须同步，否则 Write/Edit 工具报错时退化为通用提示
```

#### 3.3 完整调用流程

```
会话开始
└── _discovered_tools = set()

第 1 轮 LLM 调用
└── prompt 工具 = always_load 工具（10 个）
    [Bash, Read, Write, Edit, Grep, AstGrep, Glob, Skill, SkillResource, ToolSearch]

模型调用 ToolSearch(query="fetch web page")
└── 搜索 should_defer=True 的工具
└── 返回 [WebFetch] 及描述
└── ctx.on_tools_discovered({"WebFetch"})
└── _discovered_tools = {"WebFetch"}

第 2 轮 LLM 调用
└── prompt 工具 = always_load + _discovered_tools（11 个）
    [... + WebFetch]
└── 模型现在可以调用 WebFetch
```

---

## 文件结构变化

```
src/bourbon/tools/
├── __init__.py          # 重构：ToolContext、Tool 新字段、ToolRegistry._alias_map + call()、
│                        #        register_tool 新参数、definitions(discovered=)
├── base.py              # 重命名：Bash/Read/Write/Edit，handler 改为 ctx，is_destructive=True for Bash
├── search.py            # 重命名：Grep/AstGrep，新增 Glob
├── skill_tool.py        # 重命名：Skill/SkillResource，handler 改为 ctx
├── tool_search.py       # 新建：ToolSearch 工具
├── web.py               # 重命名：WebFetch，should_defer=True，handler 改为 ctx
├── data.py              # 重命名：CsvAnalyze/JsonQuery，should_defer=True，handler 改为 ctx
└── documents.py         # 重命名：PdfRead/DocxRead，should_defer=True，handler 改为 ctx

src/bourbon/agent.py
├── 新增 _discovered_tools: set[str]
├── 新增 _make_tool_context() 方法
├── 改 _execute_tools() → 通过 registry.call() 注入 ctx
├── 改 3 处 definitions() 调用 → definitions(discovered=self._discovered_tools)
├── 改 4 处 hardcoded 工具名检查 → 通过 Tool 属性判断
└── 删除 skill 手动分支（行 947 附近）
```

---

## 向后兼容策略

1. **aliases 机制**：旧工具名（`read_file`、`bash` 等）注册为 aliases，`_resolve()` 先查主名再查 alias map。现有使用旧工具名的测试无需修改。
2. **hardcoded 名称替换为属性判断**：`agent.py` 中 4 处字符串比较改为基于 `Tool.is_destructive` / `tool.is_high_risk_operation()` 的逻辑，使名称重构对 agent 逻辑透明。
3. **skill 手动分支删除**：alias 机制生效后，`tool_name == "skill"` 的手动路由可安全删除。
4. **Stage-B 行为变化**：原来 Stage-B 工具仅在依赖安装时进入 prompt；重构后改为注册但 `should_defer=True`，需要 ToolSearch 才进入 prompt。这是正向改进。

---

## 测试策略

| 测试类型 | 覆盖内容 |
|----------|----------|
| 单元测试 | `ToolRegistry._resolve()` 别名查找；`get_tool_definitions(discovered=...)` 过滤逻辑；`is_high_risk_operation()` 基于 `is_destructive` |
| 集成测试 | ToolSearch 触发后 `_discovered_tools` 正确更新；Stage-B 工具在发现前不出现在 prompt；发现后出现 |
| 回归测试 | 现有所有工具测试通过（旧名 aliases 保证）；agent.py 的 4 处逻辑修改后行为不变 |

---

## 实施顺序（三步可独立验证）

1. **Step 1**：重构 `__init__.py`
   - `ToolContext` 新数据类
   - `Tool` 新字段（aliases、always_load、should_defer、is_destructive 等）
   - `ToolRegistry._alias_map`、`_resolve()`、`call()`
   - `register_tool()` 新参数
   - `__post_init__` 和 `is_high_risk_operation` 改为基于 `is_destructive`
   - `definitions(discovered=)` 参数
   - ✅ 验证：所有现有测试通过

2. **Step 2**：重命名工具 + 新增 Glob
   - `base.py`、`search.py`、`skill_tool.py` 工具重命名，handler 改 ctx
   - `web.py`、`data.py`、`documents.py` 重命名 + should_defer=True
   - `search.py` 新增 Glob
   - ✅ 验证：旧名 aliases 保证测试通过，新测试验证新名称

3. **Step 3**：Deferred 发现 + Agent 修改
   - 新建 `tool_search.py`（ToolSearch 工具）
   - `agent.py`：`_discovered_tools`、`_make_tool_context()`、3 处 definitions() 调用、4 处 hardcoded 名称、删除 skill 手动分支
   - ✅ 验证：集成测试验证 deferred 发现流程
