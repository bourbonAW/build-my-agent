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

**新增 `ToolContext` 数据类**，统一执行上下文，替换各处零散的 `workdir` kwarg：

```python
@dataclass
class ToolContext:
    workdir: Path
    agent_id: str | None = None
```

**`Tool` 新增字段**：

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
    should_defer: bool = False      # True = 需要 ToolSearch 才可用
    is_concurrency_safe: bool = False   # 并发安全标注（暂不影响执行）
    is_read_only: bool = False
    is_destructive: bool = False
```

**Handler 签名统一**：

```python
# 重构前（各不相同）
def bash_tool(command: str, workdir: Path | None = None) -> str: ...
def read_file_tool(path: str, limit: int | None = None, workdir: Path | None = None) -> str: ...

# 重构后（统一 ctx 注入）
def bash_handler(command: str, *, ctx: ToolContext) -> str: ...
def read_handler(path: str, limit: int | None = None, *, ctx: ToolContext) -> str: ...
```

**ToolRegistry 新增方法**：

```python
class ToolRegistry:
    def _resolve(self, name: str) -> Tool | None:
        """按主名或 alias 查找工具。"""
        if name in self._tools:
            return self._tools[name]
        return self._alias_map.get(name)

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

`definitions()` 顶层函数同步更新：

```python
def definitions(discovered: set[str] | None = None) -> list[dict]:
    from bourbon.tools import base, search, skill_tool, tool_search  # noqa: F401
    return get_registry().get_tool_definitions(discovered=discovered)
```

---

### 步骤二：工具重命名 & 完整工具集

#### 核心工具（always_load=True）

| 旧名称 | 新名称 | aliases | is_read_only | is_concurrency_safe |
|--------|--------|---------|:------------:|:-------------------:|
| `bash` | `Bash` | `["bash"]` | ❌ | ❌ |
| `read_file` | `Read` | `["read_file"]` | ✅ | ✅ |
| `write_file` | `Write` | `["write_file"]` | ❌ | ❌ |
| `edit_file` | `Edit` | `["edit_file"]` | ❌ | ❌ |
| `rg_search` | `Grep` | `["rg_search"]` | ✅ | ✅ |
| `ast_grep_search` | `AstGrep` | `["ast_grep_search"]` | ✅ | ✅ |
| `skill` | `Skill` | `["skill"]` | ✅ | ❌ |
| `skill_read_resource` | `SkillResource` | `["skill_read_resource"]` | ✅ | ✅ |
| *(新增)* | `Glob` | — | ✅ | ✅ |
| *(新增)* | `ToolSearch` | — | ✅ | ✅ |

**新增 `Glob` 工具**（文件模式匹配，对齐 Claude Code GlobTool）：

```python
# 输入
{ "pattern": "**/*.py", "path": "." }
# 输出
# 匹配的文件路径列表（换行分隔），超出 100 个截断
```

实现：使用 Python 内置 `pathlib.Path.glob()`。

#### Stage-B 工具（should_defer=True, always_load=False）

| 模块 | 工具名 | should_defer |
|------|--------|:------------:|
| `web.py` | `WebSearch`、`WebFetch` | ✅ |
| `data.py` | `DataQuery`、`DataPlot`（等现有工具） | ✅ |
| `documents.py` | `ReadPDF`、`ReadDocx`（等现有工具） | ✅ |

Stage-B 工具的导入策略：仍保持条件导入（依赖未安装时跳过注册），但注册时标注 `should_defer=True`。

---

### 步骤三：Deferred 工具发现机制

#### ToolSearch 工具

新文件 `src/bourbon/tools/tool_search.py`，注册 `ToolSearch` 工具（`always_load=True`）：

```python
# 输入
{ "query": "web search", "max_results": 5 }

# 输出（文本格式）
Found 2 tools matching "web search":

- WebSearch: Search the web using a query string
- WebFetch: Fetch and extract content from a URL

These tools are now available for use.
```

**评分逻辑**（参考 Claude Code ToolSearchTool）：

- 工具名包含查询词：+10
- `search_hint` 匹配：+4
- description 包含查询词：+2

**副作用**：`ToolSearch` 工具调用后，把匹配的工具名通过 `ctx` 反向通知 Agent 加入 `_discovered_tools`。

实现方式：`ToolContext` 增加可选的回调字段：

```python
@dataclass
class ToolContext:
    workdir: Path
    agent_id: str | None = None
    on_tools_discovered: Callable[[set[str]], None] | None = None
```

`ToolSearch` handler 内调用 `ctx.on_tools_discovered(matched_names)` 通知 Agent。

#### Agent 状态管理

```python
class Agent:
    def __init__(self, ...):
        self._discovered_tools: set[str] = set()

    def _make_tool_context(self) -> ToolContext:
        return ToolContext(
            workdir=self.workdir,
            on_tools_discovered=self._discovered_tools.update,
        )

    def _get_tool_definitions(self) -> list[dict]:
        from bourbon.tools import definitions
        return definitions(discovered=self._discovered_tools)

    def _execute_tools(self, tool_calls: list[dict]) -> list[dict]:
        ctx = self._make_tool_context()
        results = []
        for call in tool_calls:
            result = get_registry().call(call["name"], call["input"], ctx)
            results.append({"tool_use_id": call["id"], "content": result})
        return results
```

#### 完整调用流程

```
会话开始
└── _discovered_tools = set()

第 1 轮 LLM 调用
└── prompt 工具 = always_load 工具
    [Bash, Read, Write, Edit, Grep, AstGrep, Glob, Skill, SkillResource, ToolSearch]

模型调用 ToolSearch(query="web search")
└── 返回匹配的 deferred 工具列表
└── _discovered_tools += {"WebSearch", "WebFetch"}

第 2 轮 LLM 调用
└── prompt 工具 = always_load + _discovered_tools
    [... + WebSearch, WebFetch]
└── 模型现在可以调用 WebSearch
```

---

## 文件结构变化

```
src/bourbon/tools/
├── __init__.py          # 重构：Tool+ToolContext 新字段，ToolRegistry.call()，definitions(discovered=)
├── base.py              # 重命名：Read/Write/Edit/Bash，handler 签名改为 ctx
├── search.py            # 重命名：Grep/AstGrep，新增 Glob
├── skill_tool.py        # 重命名：Skill/SkillResource，handler 签名改为 ctx
├── tool_search.py       # 新建：ToolSearch 工具
├── web.py               # 标注 should_defer=True，重命名工具
├── data.py              # 标注 should_defer=True，重命名工具
└── documents.py         # 标注 should_defer=True，重命名工具

src/bourbon/agent.py
└── 加 _discovered_tools，改 _execute_tools，改 definitions() 调用
```

---

## 向后兼容策略

1. **aliases 机制**：旧工具名（`read_file`、`bash` 等）注册为 aliases，`_resolve()` 先查主名再查 alias map。现有使用旧工具名的测试无需修改。
2. **Stage-B 行为变化**：原来 Stage-B 工具通过条件 import 控制是否注册；重构后始终注册（若依赖已装），但 `should_defer=True` 使其不进入默认 prompt。这是正向改进，不是退化。
3. **`definitions()` 默认行为**：`discovered=None` 时只返回 `always_load=True` 的工具，与旧行为（只有核心工具+已安装 Stage-B）相比更保守、更合理。

---

## 测试策略

| 测试类型 | 覆盖内容 |
|----------|----------|
| 单元测试 | `ToolRegistry._resolve()` 别名查找；`get_tool_definitions(discovered=...)` 过滤逻辑 |
| 集成测试 | ToolSearch 工具触发后 `_discovered_tools` 正确更新；Stage-B 工具在发现前不出现在 prompt |
| 回归测试 | 现有所有工具测试通过（旧名 aliases 保证） |

---

## 实施顺序（三步可独立验证）

1. **Step 1**：重构 `__init__.py`（Tool 新字段、ToolContext、ToolRegistry.call()）→ 所有现有测试仍通过
2. **Step 2**：重命名工具 + 新增 Glob → aliases 保证旧测试通过，新测试验证新名称
3. **Step 3**：新增 `tool_search.py`、修改 Agent → 集成测试验证 deferred 发现流程
