# MCP Client 实施计划

**Date:** 2025-03-19  
**Status:** Ready for implementation  
**Estimated Effort:** 2-3 days

---

## 阶段 1: 项目准备 (Day 1 Morning)

### 任务 1.1: 添加 MCP SDK 依赖

**文件:** `pyproject.toml`

```toml
[project]
dependencies = [
    # 现有依赖...
    "mcp>=1.0.0",
]
```

**验收标准:**
- [ ] `uv pip install -e ".[dev]"` 成功安装 mcp 包
- [ ] 可以 `import mcp` 无错误

---

### 任务 1.2: 创建目录结构

```bash
mkdir -p src/bourbon/mcp_client
touch src/bourbon/mcp_client/__init__.py
touch src/bourbon/mcp_client/config.py
touch src/bourbon/mcp_client/manager.py
touch src/bourbon/mcp_client/connector.py
touch src/bourbon/mcp_client/utils.py
```

---

## 阶段 2: 配置系统 (Day 1 Morning)

### 任务 2.1: 实现 MCP 配置类

**文件:** `src/bourbon/mcp_client/config.py`

**实现要点:**
- `MCPServerConfig` dataclass
- `MCPConfig` dataclass
- 支持从 dict 解析（用于 toml 配置加载）

**验收标准:**
- [ ] 可以解析设计文档中的示例配置
- [ ] 支持环境变量引用（`${VAR}` 语法）

---

### 任务 2.2: 集成到主配置

**文件:** `src/bourbon/config.py`

**修改内容:**
- 导入 `MCPConfig`
- 在 `Config` 类中添加 `mcp: MCPConfig` 字段
- 更新 `from_dict()` 和 `to_dict()` 方法

**验收标准:**
- [ ] 配置文件可以包含 `[mcp]` 和 `[[mcp.servers]]` 部分
- [ ] `ConfigManager.load_config()` 正确加载 MCP 配置

---

## 阶段 3: MCP 连接管理 (Day 1 Afternoon)

### 任务 3.1: 实现 Connector 基类

**文件:** `src/bourbon/mcp_client/connector.py`

**实现要点:**
- `BaseConnector` 抽象类
- `StdioConnector` 实现
- `HttpConnector` 实现（可选，可先 TODO）

**关键代码:**
```python
class StdioConnector:
    async def connect(self) -> tuple[ReadStream, WriteStream]:
        # 使用 mcp.client.stdio.stdio_client
        ...
```

**验收标准:**
- [ ] 可以启动外部命令并建立 stdio 连接
- [ ] 正确处理进程启动失败

---

### 任务 3.2: 实现 MCPManager

**文件:** `src/bourbon/mcp_client/manager.py`

**实现要点:**
- `__init__`: 接收 config 和 tool_registry
- `connect_all()`: 连接所有启用服务器
- `disconnect_all()`: 清理资源
- 维护 `dict[str, ClientSession]` 映射

**验收标准:**
- [ ] 成功连接配置的 MCP 服务器
- [ ] 失败的服务器记录错误但不中断其他连接
- [ ] 断开连接时正确清理资源

---

## 阶段 4: 工具集成 (Day 2)

### 任务 4.1: 实现工具包装器

**文件:** `src/bourbon/mcp_client/utils.py`

**实现要点:**
- `format_mcp_result()`: 将 MCP 结果转为字符串
- `create_mcp_tool_handler()`: 创建工具处理函数
- 异常处理转换

**验收标准:**
- [ ] MCP 工具结果正确格式化
- [ ] 异常情况返回友好的错误信息

---

### 任务 4.2: 工具注册

**文件:** `src/bourbon/mcp_client/manager.py` (扩展)

**实现要点:**
- 在 `connect_all()` 成功后注册工具
- 工具名称格式: `{server_name}:{tool_name}`
- 描述前缀: `[{server_name} MCP]`
- 风险等级: 默认 MEDIUM

**验收标准:**
- [ ] MCP Tools 出现在 `ToolRegistry.list_tools()`
- [ ] 工具名称包含服务器前缀
- [ ] Agent 可以调用 MCP Tools

---

### 任务 4.3: 集成到 Agent

**文件:** `src/bourbon/agent.py`

**实现要点:**
- 在 `__init__` 中创建 `MCPManager`
- 在初始化流程中调用 `connect_all()`
- 支持 `async` 初始化（可能需要调整 Agent 创建方式）

**验收标准:**
- [ ] Agent 启动时自动连接 MCP 服务器
- [ ] Agent 可以使用 MCP Tools

---

## 阶段 5: REPL 集成 (Day 2 Afternoon)

### 任务 5.1: 添加 MCP 状态命令

**文件:** `src/bourbon/repl.py`

**实现要点:**
- `/mcp` 命令: 显示 MCP 连接状态和可用工具
- 在欢迎消息或 `/help` 中提及 MCP

**验收标准:**
- [ ] `/mcp` 显示所有服务器连接状态
- [ ] 显示可用的 MCP Tools 列表

---

## 阶段 6: 测试 (Day 3)

### 任务 6.1: 单元测试

**文件:** `tests/test_mcp_config.py`

```python
def test_parse_mcp_config():
    data = {
        "enabled": True,
        "servers": [
            {
                "name": "test",
                "transport": "stdio",
                "command": "echo",
                "args": ["hello"],
            }
        ]
    }
    config = MCPConfig.from_dict(data)
    assert config.enabled is True
    assert len(config.servers) == 1
```

**文件:** `tests/test_mcp_manager.py`

```python
async def test_connect_mock_server():
    # 使用 mock 测试连接逻辑
    ...
```

**验收标准:**
- [ ] 配置解析测试通过
- [ ] Manager 基础功能测试通过

---

### 任务 6.2: 集成测试

**文件:** `tests/test_mcp_integration.py`

**测试 MCP Server:**
```python
# tests/fixtures/mcp_test_server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("test")

@mcp.tool()
def echo(message: str) -> str:
    return f"Echo: {message}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**验收标准:**
- [ ] 可以连接测试服务器
- [ ] 可以调用测试工具
- [ ] 结果正确返回

---

### 任务 6.3: 端到端测试

**手动测试步骤:**
1. 配置 fetch MCP server
2. 启动 Bourbon
3. 询问 "请使用 fetch:fetch_url 获取 https://example.com"
4. 验证工具被调用并返回结果

---

## 阶段 7: 文档 (Day 3 Afternoon)

### 任务 7.1: 更新 README

**内容:**
- MCP 功能简介
- 配置示例
- 可用 MCP Servers 推荐

---

### 任务 7.2: 更新 AGENTS.md

**内容:**
- MCP 配置规范
- 开发注意事项

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| MCP SDK API 变动 | 高 | 锁定版本 `>=1.0.0,<2.0.0` |
| 外部服务器不稳定 | 中 | 实现超时和重试机制 |
| Agent 启动变慢 | 低 | 并行连接服务器，失败不阻塞 |

---

## 提交计划

```bash
# Commit 1: 配置系统
git add src/bourbon/mcp_client/config.py src/bourbon/config.py pyproject.toml
git commit -m "feat: Add MCP configuration system"

# Commit 2: 连接管理
git add src/bourbon/mcp_client/connector.py src/bourbon/mcp_client/manager.py
git commit -m "feat: Add MCP connection management"

# Commit 3: 工具集成
git add src/bourbon/mcp_client/utils.py src/bourbon/agent.py
git commit -m "feat: Integrate MCP tools into Agent"

# Commit 4: REPL 和测试
git add src/bourbon/repl.py tests/
git commit -m "feat: Add MCP commands and tests"

# Commit 5: 文档
git add README.md AGENTS.md
git commit -m "docs: Add MCP documentation"
```

---

## 附录: 最小可行配置

```toml
[mcp]
enabled = true

[[mcp.servers]]
name = "fetch"
transport = "stdio"
command = "uvx"
args = ["mcp-server-fetch"]
```

**测试命令:**
```
> 请使用 fetch:fetch_url 获取 https://example.com 的内容
```
