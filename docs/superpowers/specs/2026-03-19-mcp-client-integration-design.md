# MCP Client 集成设计文档

**Date:** 2025-03-19  
**Author:** Bourbon Team  
**Status:** Approved  
**Approach:** 方案 A - 简单代理模式

---

## 1. 概述

### 1.1 目标

将 Model Context Protocol (MCP) Client 功能集成到 Bourbon 中，使 Bourbon Agent 能够连接并使用外部 MCP Servers 提供的 Tools。

### 1.2 设计原则

1. **简单性优先**：方案 A 的简单代理模式，启动时连接，运行时透明
2. **最小侵入**：不修改现有工具系统，通过 ToolRegistry 动态注册
3. **渐进式采用**：从配置开始，逐步扩展

### 1.3 非目标

- 不支持运行时动态添加/移除 MCP Servers（保持简单）
- 不支持 MCP Resources 和 Prompts（仅 Tools）
- 不支持 MCP Server 模式（仅 Client）

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                       Bourbon Agent                        │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Config     │  │ MCPManager   │  │  ToolRegistry    │  │
│  │  (mcp conf)  │→ │  (connect)   │→ │ (register tools) │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│         ↑                                    ↓              │
│         └────────────────────────────────────┘              │
│                    Agent Loop                               │
└─────────────────────────────────────────────────────────────┘
                              ↓
                    ┌─────────────────┐
                    │   MCP Servers   │
                    │  (stdio/http)   │
                    └─────────────────┘
```

### 2.2 组件职责

| 组件 | 职责 |
|------|------|
| `MCPConfig` | 配置数据类，定义服务器连接参数 |
| `MCPManager` | 管理 MCP 连接生命周期，维护 ClientSession |
| `MCPConnector` | 具体传输实现（stdio / http） |
| `ToolRegistry` | 接收 MCP Tools 注册，统一调度 |

---

## 3. 数据结构

### 3.1 配置结构

```toml
# ~/.bourbon/config.toml

[mcp]
# 全局设置
enabled = true
default_timeout = 30  # 工具调用超时（秒）

# stdio transport - 本地进程通信
[[mcp.servers]]
name = "github"
transport = "stdio"
command = "npx"
args = ["-y", "@github/mcp-server"]
env = { GITHUB_TOKEN = "${GITHUB_TOKEN}" }  # 支持环境变量引用
enabled = true

[[mcp.servers]]
name = "fetch"
transport = "stdio"
command = "uvx"
args = ["mcp-server-fetch"]
enabled = true

# HTTP transport - 远程服务器通信（核心功能）
[[mcp.servers]]
name = "remote-api"
transport = "http"
url = "https://mcp.example.com/mcp"
headers = { Authorization = "Bearer ${API_TOKEN}" }  # 自定义请求头
timeout = 60  # 连接超时（秒）
max_retries = 3  # 连接失败重试次数
retry_delay = 1.0  # 重试间隔（秒）
enabled = true

# 公司内部 MCP 服务
[[mcp.servers]]
name = "company-tools"
transport = "http"
url = "http://internal.company.com:8080/mcp"
max_retries = 5  # 内网服务可能需要更多重试
enabled = true
```

### 3.2 代码数据结构

```python
# src/bourbon/mcp_client/config.py
@dataclass
class MCPServerConfig:
    name: str
    transport: str  # "stdio" | "http"
    enabled: bool = True
    
    # stdio transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    
    # http transport
    url: str | None = None

@dataclass
class MCPConfig:
    enabled: bool = True
    default_timeout: int = 30
    servers: list[MCPServerConfig] = field(default_factory=list)
```

---

## 4. 接口定义

### 4.1 MCPManager

```python
# src/bourbon/mcp_client/manager.py

class MCPManager:
    """Manages MCP server connections and tool registration."""
    
    def __init__(
        self,
        config: MCPConfig,
        tool_registry: ToolRegistry,
        workdir: Path | None = None,
    ):
        """Initialize MCP manager with configuration."""
        ...
    
    async def connect_all(self) -> dict[str, ConnectionResult]:
        """Connect to all enabled MCP servers.
        
        Returns:
            Mapping of server name to connection result (success/error).
        """
        ...
    
    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        ...
    
    def get_connection_status(self, server_name: str) -> ConnectionStatus:
        """Get connection status for a specific server."""
        ...
    
    def list_available_tools(self) -> list[str]:
        """List all available MCP tools (with server prefix)."""
        ...
```

### 4.2 Tool 注册格式

MCP Tools 注册到 ToolRegistry 时，使用命名空间格式：

```python
# 工具名称格式: "{server_name}:{tool_name}"
# 例如: "github:search_issues", "fetch:fetch_url"

tool = Tool(
    name=f"{server_name}:{mcp_tool.name}",
    description=f"[{server_name} MCP] {mcp_tool.description}",
    input_schema=mcp_tool.inputSchema,
    handler=wrap_mcp_handler(session, mcp_tool.name),
    risk_level=RiskLevel.MEDIUM,  # 默认 MEDIUM，可配置
)
```

### 4.3 MCP 工具调用包装器

```python
async def wrap_mcp_handler(
    session: ClientSession,
    tool_name: str,
    timeout: int,
) -> Callable[..., str]:
    """Create a handler function for an MCP tool."""
    
    async def handler(**kwargs) -> str:
        try:
            result = await session.call_tool(
                tool_name,
                arguments=kwargs,
                timeout=timeout,
            )
            return format_mcp_result(result)
        except McpError as e:
            return f"Error: MCP tool failed - {e}"
        except TimeoutError:
            return f"Error: MCP tool timeout ({timeout}s)"
        except Exception as e:
            return f"Error: Unexpected error - {e}"
    
    return handler
```

---

## 5. 错误处理

### 5.1 连接阶段错误

| 场景 | 处理策略 |
|------|----------|
| 服务器启动失败 | 记录警告，跳过该服务器，继续启动 |
| 初始化超时 | 记录错误，标记为断开状态 |
| 协议版本不匹配 | 记录错误，跳过该服务器 |
| HTTP 连接失败 | 自动重试（指数退避），最多 `max_retries` 次 |
| HTTP 身份验证失败 | 立即失败，提示检查 headers/token |

### 5.2 运行时错误

| 场景 | 处理策略 |
|------|----------|
| 工具调用超时 | 返回错误信息，不中断其他工具 |
| 服务器进程退出 | 该服务器的工具失效，返回错误 |
| 无效参数 | 返回 MCP 错误详情 |

### 5.3 风险等级

- **默认**: 所有 MCP Tools 标记为 `RiskLevel.MEDIUM`
- **理由**: 外部工具可能产生副作用，需要用户确认
- **未来扩展**: 配置中支持按工具覆盖风险等级

---

## 6. 实现细节

### 6.1 文件结构

```
src/bourbon/mcp_client/
├── __init__.py          # 导出 MCPManager
├── config.py            # MCPConfig, MCPServerConfig
├── manager.py           # MCPManager 主类
├── connector.py         # StdioConnector, HttpConnector
└── utils.py             # 辅助函数 (format_mcp_result, etc.)
```

### 6.2 配置集成

修改 `src/bourbon/config.py`：

```python
@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)  # 新增
```

### 6.3 Agent 集成

修改 `src/bourbon/agent.py`：

```python
class Agent:
    def __init__(...):
        # 现有初始化...
        
        # 新增 MCP 初始化
        self.mcp_manager = MCPManager(
            config=config.mcp,
            tool_registry=get_registry(),
            workdir=self.workdir,
        )
        # 连接 MCP 服务器
        await self.mcp_manager.connect_all()
```

### 6.4 传输方式选择指南

| 场景 | 推荐传输 | 原因 |
|------|---------|------|
| 本地工具 (`uvx`, `npx`) | stdio | 简单、快速、无需网络配置 |
| 远程服务 | **HTTP** | **核心功能**，支持跨网络访问 |
| 公司内部服务 | HTTP | 可配置认证 headers，支持重试 |
| Docker 容器 | stdio | 本地进程管理 |

**HTTP 传输特有配置**：
- `url`: MCP 服务端点（必需）
- `headers`: 自定义 HTTP 头（如认证 token）
- `timeout`: 连接超时覆盖
- `max_retries`: 连接失败重试次数
- `retry_delay`: 基础重试间隔（实际使用指数退避）

---

## 7. 测试策略

### 7.1 单元测试

- `test_mcp_config.py`: 配置解析测试
- `test_mcp_manager.py`: 连接管理测试
- `test_mcp_connector.py`: 传输层测试（使用 mock）

### 7.2 集成测试

- 使用简单的 echo MCP server 测试端到端流程
- 测试工具注册和调用

### 7.3 测试工具

```python
# 简单的测试 MCP Server
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("test")

@mcp.tool()
def echo(message: str) -> str:
    """Echo a message."""
    return f"Echo: {message}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

---

## 8. 限制与未来扩展

### 8.1 当前限制

1. 仅支持 Tools，不支持 Resources/Prompts
2. 启动时连接，不支持运行时动态管理
3. 仅支持 Client 模式

### 8.2 未来扩展方向

1. **Resources 支持**: 将 MCP Resources 映射到 Bourbon 的 `read_file` 等工具
2. **动态管理**: 添加 `mcp_connect`/`mcp_disconnect` 工具
3. **Server 模式**: 让 Bourbon 本身成为 MCP Server

---

## 9. 参考

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-06-18)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Agent Skills Specification](https://agentskills.io/specification)
