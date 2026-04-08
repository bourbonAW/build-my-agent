# Bourbon Tool 架构对齐 Claude Code 设计文档

**日期**：2026-04-08  
**状态**：待实施  
**方案**：分层演进（Layered Evolution）

> **命名说明**：工具命名参考 Claude Code 风格（PascalCase），但不严格对齐。
> 例如 Claude Code 用 `FileRead`/`FileEdit`/`FileWrite`，本项目用更短的 `Read`/`Edit`/`Write`。
> `is_read_only` 等语义属性与 Claude Code 对齐，不因命名简化而改变。

---

## 背景与目标

Bourbon agent 的工具系统与 Claude Code 架构存在以下差距：

1. `Tool` 类缺少 `always_load`、`should_defer`、`is_concurrency_safe`、`is_read_only`、`is_destructive` 等属性
2. 工具命名采用 snake_case（`read_file`、`rg_search`），与目标 PascalCase 风格不一致
3. 所有工具始终全量加载进 prompt，无 deferred 按需发现机制
4. 各工具 handler 通过零散的 `workdir` kwarg 接收上下文，没有统一执行上下文对象
5. 缺少 `Glob` 和 `ToolSearch` 工具
6. Stage-B 工具（web/data/documents）根本未接入 `definitions()` 链路（不是"依赖安装时进入 prompt"，而是完全不注册）

**目标**：参考 Claude Code 架构，全面重构 bourbon 的 built-in tool 系统，包含 Stage-B 工具（web/data/documents）。

**本期明确排除**：MCP tools 的 deferred 机制（独立后续工作）、并发执行（bourbon 保持同步顺序执行）。

---

## 范围

- `src/bourbon/tools/` 目录全部文件
- `src/bourbon/agent.py`（deferred 发现逻辑、hardcoded 工具名修复）
- `src/bourbon/access_control/`（capabilities.py、`__init__.py`，工具名映射更新）

---

## 设计方案（分层演进 B）

### 步骤一：Tool 类型系统 & ToolContext

#### 1.1 ToolContext

新增 `ToolContext` 数据类，统一执行上下文：

```python
@dataclass
class ToolContext:
    workdir: Path
    skill_manager: Any | None = None          # Agent 级 SkillManager，供 Skill 工具使用
    on_tools_discovered: Callable[[set[str]], None] | None = None  # ToolSearch 回调
```

`skill_manager` 字段解决 skill 工具的双路径问题（见步骤三）。

#### 1.2 Tool 新增字段

```python
@dataclass
class Tool:
    # 现有字段（保持）
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler   # 签名：(**kwargs, ctx: ToolContext) -> str | Awaitable[str]
    risk_level: RiskLevel = RiskLevel.LOW
    risk_patterns: list[str] | None = None
    required_capabilities: list[str] | None = None

    # 新增字段
    aliases: list[str] = field(default_factory=list)   # 向后兼容旧工具名
    always_load: bool = True        # False 的工具不默认进入 prompt
    should_defer: bool = False      # True = 需要 ToolSearch 才可用（隐含 always_load=False）
    is_concurrency_safe: bool = False   # 并发安全标注（暂不影响执行）
    is_read_only: bool = False
    is_destructive: bool = False    # True = 破坏性操作（如 Bash）；影响 sandbox 路由判断
    search_hint: str | None = None  # ToolSearch 额外匹配关键词（评分 +4）
```

#### 1.3 `__post_init__` 和 `is_high_risk_operation` 去除硬编码名称

当前代码用 `self.name == "bash"` 判断是否设置默认 risk_patterns。重构后改为 `is_destructive`：

```python
def __post_init__(self):
    # ...capabilities 验证保持不变...
    if self.risk_patterns is None:
        if self.risk_level == RiskLevel.HIGH and self.is_destructive:
            self.risk_patterns = [
                "pip install", "pip3 install", "pip uninstall", "pip3 uninstall",
                "apt ", "apt-get ", "yum ", "brew ", "pacman ", "dnf ",
                "rm ", "rm -", "rmdir ", "sudo ", "su ",
                "shutdown", "reboot", "halt", "poweroff",
                "mkfs.", "fdisk", "dd ", "> /dev", "> /sys", "> /proc",
                "curl ", "wget ", "| sh", "| bash",
            ]
        else:
            self.risk_patterns = []

def is_high_risk_operation(self, tool_input: dict) -> bool:
    if self.risk_level == RiskLevel.HIGH and self.is_destructive:
        command = tool_input.get("command", "")
        return any(pattern in command for pattern in self.risk_patterns)
    return self.risk_level == RiskLevel.HIGH
```

`Bash` 工具注册时显式传入 `is_destructive=True`，不再依赖名称判断。

#### 1.4 register_tool 装饰器更新签名

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

#### 1.5 ToolRegistry 重构

新增 `_alias_map`，在 `register()` 时同步维护；所有查找路径（包括顶层 `handler()`、`get_tool_with_metadata()`）改为经过 `_resolve()`：

```python
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._alias_map: dict[str, str] = {}  # alias → canonical name

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        for alias in (tool.aliases or []):
            self._alias_map[alias] = tool.name

    def _resolve(self, name: str) -> Tool | None:
        """按主名或 alias 查找工具。"""
        if name in self._tools:
            return self._tools[name]
        canonical = self._alias_map.get(name)
        return self._tools.get(canonical) if canonical else None

    def get(self, name: str) -> Tool | None:
        return self._resolve(name)        # 改为 alias-aware

    def get_handler(self, name: str) -> ToolHandler | None:
        tool = self._resolve(name)        # 改为 alias-aware
        return tool.handler if tool else None

    def get_tool(self, name: str) -> Tool | None:
        return self._resolve(name)        # 改为 alias-aware

    def call(self, name: str, tool_input: dict, ctx: ToolContext) -> str:
        """调用工具，注入 ToolContext。支持 async handler（用 asyncio.run 包装）。"""
        tool = self._resolve(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        result = tool.handler(**tool_input, ctx=ctx)
        # 支持 async handler（如 WebFetch）
        if inspect.isawaitable(result):
            import asyncio
            result = asyncio.run(result)
        return result

    def get_tool_definitions(self, discovered: set[str] | None = None) -> list[dict]:
        discovered = discovered or set()
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
            if t.always_load or t.name in discovered
        ]
```

#### 1.6 顶层函数同步更新

```python
def handler(name: str) -> ToolHandler | None:
    _ensure_imports()
    return get_registry().get_handler(name)   # 已 alias-aware

def get_tool_with_metadata(name: str) -> Tool | None:
    _ensure_imports()
    return get_registry().get_tool(name)      # 已 alias-aware

def definitions(discovered: set[str] | None = None) -> list[dict]:
    _ensure_imports()
    return get_registry().get_tool_definitions(discovered=discovered)

def _ensure_imports():
    """懒加载所有工具模块，触发注册。"""
    from bourbon.tools import base, search, skill_tool, tool_search  # noqa: F401
    # Stage-B 工具：依赖安装时注册（should_defer=True，不进入默认 prompt）
    try:
        from bourbon.tools import web      # noqa: F401
    except ImportError:
        pass
    try:
        from bourbon.tools import data     # noqa: F401
    except ImportError:
        pass
    try:
        from bourbon.tools import documents  # noqa: F401
    except ImportError:
        pass
```

---

### 步骤二：工具重命名 & 完整工具集 & 权限链更新

#### 核心工具（always_load=True）

| 旧名称 | 新名称 | aliases | is_read_only | is_destructive | is_concurrency_safe |
|--------|--------|---------|:------------:|:--------------:|:-------------------:|
| `bash` | `Bash` | `["bash"]` | ❌ | ✅ | ❌ |
| `read_file` | `Read` | `["read_file"]` | ✅ | ❌ | ✅ |
| `write_file` | `Write` | `["write_file"]` | ❌ | ❌ | ❌ |
| `edit_file` | `Edit` | `["edit_file"]` | ❌ | ❌ | ❌ |
| `rg_search` | `Grep` | `["rg_search"]` | ✅ | ❌ | ✅ |
| `ast_grep_search` | `AstGrep` | `["ast_grep_search"]` | ✅ | ❌ | ✅ |
| `skill` | `Skill` | `["skill"]` | ❌ | ❌ | ❌ |
| `skill_read_resource` | `SkillResource` | `["skill_read_resource"]` | ✅ | ❌ | ✅ |
| *(新增)* | `Glob` | — | ✅ | ❌ | ✅ |
| *(新增)* | `ToolSearch` | — | ✅ | ❌ | ✅ |

注：`Skill` 的 `is_read_only=False`（Claude Code 明确 Skill 不是只读操作）。

**新增 `Glob` 工具**（加入 `search.py`）：

```python
# 输入
{ "pattern": "**/*.py", "path": "." }
# 输出：匹配的文件路径列表，换行分隔，超出 100 个截断
```

实现：使用 `pathlib.Path.glob()`，路径相对于 `ctx.workdir`。

#### Stage-B 工具（should_defer=True, always_load=False）

完整旧名到新名映射：

| 模块 | 旧名称 | 新名称 | aliases |
|------|--------|--------|---------|
| `web.py` | `fetch_url` | `WebFetch` | `["fetch_url"]` |
| `data.py` | `csv_analyze` | `CsvAnalyze` | `["csv_analyze"]` |
| `data.py` | `json_query` | `JsonQuery` | `["json_query"]` |
| `documents.py` | `pdf_to_text` | `PdfRead` | `["pdf_to_text"]` |
| `documents.py` | `docx_to_markdown` | `DocxRead` | `["docx_to_markdown"]` |

`WebFetch` 的 handler 保持 `async def`，由 `ToolRegistry.call()` 的 `asyncio.run()` 包装统一处理。

#### access_control 同步更新

`src/bourbon/access_control/capabilities.py` 中的工具名映射（行 25、79）需同步改为新名称：

```python
# 改前
"bash": CapabilityType.EXEC,
"read_file": CapabilityType.FILE_READ,
"rg_search": CapabilityType.FILE_READ,
# ...

# 改后
"Bash": CapabilityType.EXEC,
"Read": CapabilityType.FILE_READ,
"Grep": CapabilityType.FILE_READ,
# ...
```

`src/bourbon/access_control/__init__.py`（行 26）中同样的旧名引用一并更新。

由于 `required_capabilities` 仍挂在 `Tool` 上（通过属性传递），此处只需同步字符串键名，不影响 capability 推断逻辑本身。

---

### 步骤三：Deferred 工具发现机制 & Agent 修改

#### 3.1 ToolSearch 工具

新文件 `src/bourbon/tools/tool_search.py`，注册 `ToolSearch` 工具（`always_load=True`）：

```python
# 输入
{ "query": "fetch web page", "max_results": 5 }

# 输出
Found 1 tool matching "fetch web page":

- WebFetch: Fetch and extract content from a URL

These tools are now available for use.
```

**评分逻辑**（仅搜索 `should_defer=True` 的工具）：

- 工具名包含查询词：+10
- `search_hint` 匹配：+4
- description 包含查询词：+2

**实现**：

```python
def tool_search_handler(query: str, max_results: int = 5, *, ctx: ToolContext) -> str:
    registry = get_registry()
    deferred = [t for t in registry.list_tools() if t.should_defer]
    
    def score(t: Tool) -> int:
        q = query.lower()
        s = 0
        if q in t.name.lower(): s += 10
        if t.search_hint and q in t.search_hint.lower(): s += 4
        if q in t.description.lower(): s += 2
        return s
    
    scored = sorted(deferred, key=score, reverse=True)
    matches = [t for t in scored if score(t) > 0][:max_results]
    
    if ctx.on_tools_discovered and matches:
        ctx.on_tools_discovered({t.name for t in matches})
    
    if not matches:
        return f"No tools found matching '{query}'"
    
    lines = [f"Found {len(matches)} tool(s) matching '{query}':\n"]
    for t in matches:
        lines.append(f"- {t.name}: {t.description}")
    lines.append("\nThese tools are now available for use.")
    return "\n".join(lines)
```

#### 3.2 Agent 修改

**新增状态与方法**：

```python
class Agent:
    def __init__(self, ...):
        self._discovered_tools: set[str] = set()

    def _make_tool_context(self) -> ToolContext:
        return ToolContext(
            workdir=self.workdir,
            skill_manager=self.skills,           # 传入 Agent 级 SkillManager
            on_tools_discovered=self._discovered_tools.update,
        )
```

**`_execute_tools()` 改为通过 `registry.call()` 注入 ctx**：

```python
def _execute_tools(self, tool_calls: list[dict]) -> list[dict]:
    ctx = self._make_tool_context()
    results = []
    for call in tool_calls:
        result = get_registry().call(call["name"], call["input"], ctx)
        results.append({"tool_use_id": call["id"], "content": result})
    return results
```

**3 处 `definitions()` 调用（行约 461、465、680）全部更新**：

```python
# 改前
tools = definitions()
# 改后
tools = definitions(discovered=self._discovered_tools)
```

**5 处 hardcoded 工具名修复**：

```python
# 行 868：bash 沙箱路由
# 改前：if tool_name == "bash" and getattr(self.sandbox, "enabled", False):
# 改后：
tool_meta = get_registry()._resolve(tool_name)
if tool_meta and tool_meta.is_destructive and getattr(self.sandbox, "enabled", False):
    ...

# 行 884：沙箱路由的工具集
# 改前：if tool_name in {"bash", "read_file", "write_file", "edit_file"}:
# 改后（sandbox 只处理 shell command，只有 Bash/is_destructive 走这条路）：
if tool_meta and tool_meta.is_destructive:
    ...

# 行 947：skill 手动分支 → 删除
# 该分支在 aliases 机制 + ToolContext.skill_manager 生效后可以安全删除。
# Skill 工具通过 registry 路由，从 ctx.skill_manager 获取 Agent 级 SkillManager，
# 与 skill_tool.py 的全局 _skill_manager 统一到同一状态源。
# skill_tool.py 的 get_skill_manager() 改为优先使用 ctx.skill_manager（通过 handler 参数传入）。

# 行 1002：bash 风险检查
# 改前：if tool_name == "bash":
# 改后：
if tool_meta and tool_meta.is_high_risk_operation(tool_input):
    ...

# 行 1024：_generate_options() 中的错误提示
# 改前：elif tool_name in ("write_file", "edit_file"):
# 改后：
elif tool_meta and not tool_meta.is_read_only and not tool_meta.is_destructive:
    ...
```

#### 3.3 skill_tool.py 双路径统一

删除 agent.py 的 skill 手动分支后，`skill_tool.py` 的 handler 改为从 `ctx.skill_manager` 获取状态：

```python
def skill_handler(name: str, *, ctx: ToolContext) -> str:
    manager = ctx.skill_manager or get_skill_manager()   # 优先 Agent 级，降级到全局
    ...
```

全局 `_skill_manager` 保留作降级路径（非 Agent 直接调用时），无需删除。

#### 3.4 完整调用流程

```
会话开始
└── _discovered_tools = set()

第 1 轮 LLM 调用
└── prompt 工具（10 个）= always_load 工具
    [Bash, Read, Write, Edit, Grep, AstGrep, Glob, Skill, SkillResource, ToolSearch]

模型调用 ToolSearch(query="fetch web page")
└── 搜索 should_defer=True 的工具（WebFetch/CsvAnalyze/JsonQuery/PdfRead/DocxRead）
└── 匹配 WebFetch，返回描述
└── ctx.on_tools_discovered({"WebFetch"})
└── _discovered_tools = {"WebFetch"}

第 2 轮 LLM 调用
└── prompt 工具（11 个）= always_load + _discovered_tools
└── 模型现在可以调用 WebFetch（async handler 由 asyncio.run 透明包装）
```

---

## 文件结构变化

```
src/bourbon/tools/
├── __init__.py          # 重构：ToolContext（+skill_manager）、Tool 新字段、
│                        #        ToolRegistry（_alias_map, _resolve, call+asyncio.run）
│                        #        register_tool 新参数、_ensure_imports()（含 Stage-B try/except）
│                        #        get/get_handler/get_tool 改为 alias-aware
├── base.py              # 重命名：Bash(is_destructive=True)/Read/Write/Edit，handler→ctx
├── search.py            # 重命名：Grep/AstGrep，新增 Glob
├── skill_tool.py        # 重命名：Skill/SkillResource，handler 改 ctx，优先 ctx.skill_manager
├── tool_search.py       # 新建：ToolSearch 工具
├── web.py               # 重命名：WebFetch(should_defer=True)，保持 async handler
├── data.py              # 重命名：CsvAnalyze/JsonQuery(should_defer=True)，handler→ctx
└── documents.py         # 重命名：PdfRead/DocxRead(should_defer=True)，handler→ctx

src/bourbon/agent.py
├── 新增 _discovered_tools: set[str]
├── 新增 _make_tool_context()（传入 self.skills 和 on_tools_discovered）
├── 改 _execute_tools() → registry.call(name, input, ctx)
├── 改 3 处 definitions() → definitions(discovered=self._discovered_tools)
├── 改 5 处 hardcoded 工具名 → 基于 Tool 属性判断
└── 删除 skill 手动分支（行 947）

src/bourbon/access_control/
├── capabilities.py      # 工具名映射：旧名 → 新名（Bash/Read/Grep 等）
└── __init__.py          # 同步工具名引用
```

---

## 向后兼容策略

1. **aliases + alias-aware 查找**：所有查找路径（`get`、`get_handler`、`get_tool`、`_resolve`）均经过 alias map，旧工具名的测试代码和历史对话无需修改。
2. **access_control 同步**：工具名映射改为新名，alias 机制保证运行时路由正确，不影响 capability 推断逻辑。
3. **async handler 透明包装**：`registry.call()` 用 `inspect.isawaitable + asyncio.run()` 包装，调用方无感知。
4. **Stage-B 行为改进**：原来 Stage-B 根本未注册；重构后注册但 `should_defer=True`，需 ToolSearch 才进 prompt，是正向改进。
5. **skill_manager 降级**：`ctx.skill_manager` 有值时用 Agent 级，无值时降级到全局 `_skill_manager`，测试中直接调用 `skill_handler` 不受影响。

---

## 测试策略

| 测试类型 | 覆盖内容 |
|----------|----------|
| 单元：registry | `_resolve()` alias 查找；`get_tool_definitions(discovered=...)` 过滤；async handler 包装 |
| 单元：access_control | 新工具名的 capability 推断正确 |
| 单元：tool_search | 评分逻辑；`on_tools_discovered` 回调触发 |
| 集成：deferred 流程 | ToolSearch 触发 → `_discovered_tools` 更新 → 下次 prompt 包含新工具 |
| 集成：Stage-B | WebFetch/CsvAnalyze 等在发现前不出现在 prompt；发现后可调用；async 结果正确 |
| 回归 | 现有所有工具测试通过（aliases 保证）；agent 5 处逻辑修改后行为不变 |

---

## 实施顺序（三步可独立验证）

1. **Step 1**：重构 `src/bourbon/tools/__init__.py`
   - `ToolContext`（含 `skill_manager`、`on_tools_discovered`）
   - `Tool` 新字段、`__post_init__` 改 `is_destructive`
   - `ToolRegistry`：`_alias_map`、`_resolve()`、`call()`（asyncio.run 包装）、`get_tool_definitions`
   - `register_tool()` 新参数
   - 顶层函数 alias-aware + `_ensure_imports()`（含 Stage-B try/except）
   - ✅ 验证：所有现有测试通过

2. **Step 2**：重命名工具 + 新增 Glob + access_control 同步
   - `base.py`、`search.py`、`skill_tool.py` 重命名，handler 改 ctx，skill_tool 改用 ctx.skill_manager
   - `web.py`、`data.py`、`documents.py` 重命名 + `should_defer=True`
   - `search.py` 新增 `Glob`
   - `access_control/capabilities.py`、`access_control/__init__.py` 工具名更新
   - ✅ 验证：旧名 aliases 保证回归测试通过；新名 + access_control 单元测试通过

3. **Step 3**：Deferred 发现 + Agent 修改
   - 新建 `tool_search.py`（ToolSearch 工具）
   - `agent.py`：`_discovered_tools`、`_make_tool_context()`、3 处 `definitions()`、5 处 hardcoded 名称、删除 skill 手动分支
   - ✅ 验证：集成测试验证完整 deferred 发现流程
