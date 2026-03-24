# Bourbon Sandbox 设计规格

## 概述

为 Bourbon agent 引入分层安全机制，通过构建来理解 sandbox 的核心概念。设计遵循费曼学习法——每一层对应一个独立的安全知识单元，可单独构建和验证。

### 设计原则

- **概念边界清晰**：Access Control、Sandbox Runtime、Audit 是三个独立机制，不混为一谈
- **配置即策略**：安全规则在 TOML 中定义，不改代码就能调整
- **可插拔隔离后端**：SandboxProvider 接口统一，Local/Bubblewrap/Seatbelt/Docker 各自实现
- **渐进式学习路径**：每个阶段可运行、可验证，做完就能看到效果

## 概念边界

### 两个独立的安全机制

**Access Control（访问控制）**— 工具调用层面的权限检查

- 对象：所有工具
- 问题："这个工具调用是否被允许？"
- 属于 agent 自身的决策逻辑
- 替代现有的 `RiskLevel` + `is_high_risk_operation()` 硬编码检查

**Sandbox Runtime（沙箱运行时）**— 执行层面的隔离环境

- 对象：只有能产生任意副作用的工具（bash、代码执行）
- 问题："这段代码/命令在什么环境中运行？"
- 文件系统隔离、网络隔离、凭证隔离、进程隔离都在这里
- 属于操作系统/基础设施层面的强制约束

**为什么不能合并：**

- Access Control 即使没有 sandbox 也有意义（阻止 agent 调用危险命令）
- Sandbox 即使没有 access control 也有意义（命令被允许执行，但限制爆炸半径）
- 研究报告指出"只做执行隔离，不做输入治理"和"只做策略检查，不做执行隔离"都是常见陷阱

### 工具分流

```
工具调用
├── 不需要 sandbox 的工具：read_file, search, skill → Access Control 检查后直接执行
│     （它们本身就是受控的 Python 函数，safe_path 已经足够）
│
└── 需要 sandbox 的工具：bash, code_execute → Access Control 检查后进入 Sandbox Runtime
      （它们能产生任意副作用：写任意文件、发网络请求、装包、起进程）
```

## 架构

### 整体流程

```
Agent._execute_tools()
    │
    ├─ read_file("src/main.py")
    │    → AccessController.evaluate() → Allow
    │    → 直接执行
    │    → AuditLogger.record(tool_call)
    │
    └─ bash("pip install flask && python app.py")
         → AccessController.evaluate() → NeedApproval → 用户确认 → Allow
         → SandboxManager.execute(command, context)
              ├─ CredentialManager.clean_env()
              ├─ Provider.execute(command, sandbox_context)
              └─ AuditLogger.record(sandbox_exec)
```

### 目录结构

```
src/bourbon/
├── access_control/
│   ├── __init__.py           # AccessController — 策略评估协调器
│   ├── policy.py             # PolicyEngine — 从 TOML 加载规则，评估策略
│   └── capabilities.py       # CapabilityType 定义 + 动态推断逻辑
│
├── sandbox/
│   ├── __init__.py           # SandboxManager — provider 选择、context 构建
│   ├── runtime.py            # SandboxProvider 抽象接口 + SandboxContext/SandboxResult
│   ├── credential.py         # CredentialManager — 凭证清洗、环境变量过滤
│   └── providers/
│       ├── __init__.py       # provider 注册与 auto 选择逻辑
│       ├── local.py          # LocalProvider — 纯 Python（subprocess + env 清洗）
│       ├── bubblewrap.py     # BwrapProvider — Linux namespace 隔离
│       ├── seatbelt.py       # SeatbeltProvider — macOS sandbox-exec
│       └── docker.py         # DockerProvider — 容器隔离
│
├── audit/
│   ├── __init__.py           # AuditLogger — JSONL 事件写入与查询
│   └── events.py             # AuditEvent + EventType 定义
│
└── tools/                    # 现有工具（保留，不大改）
```

## Access Control 层

### Capability-based 权限模型

每个工具声明自己需要的能力，策略引擎检查当前会话是否被授予了这些能力。

```python
class CapabilityType(Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    EXEC = "exec"              # bash/code 执行
    NET = "net"                # 网络访问
    SKILL = "skill"            # skill 激活
    MCP = "mcp"                # MCP 工具调用
```

工具注册时声明所需能力：

```python
@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: ToolHandler
    risk_level: RiskLevel = RiskLevel.LOW
    required_capabilities: list[CapabilityType] = field(default_factory=list)
```

### 动态能力推断

bash 工具的不同输入需要不同能力：

```python
def infer_capabilities(tool_name: str, tool_input: dict) -> list[CapabilityType]:
    """根据工具输入动态推断实际需要的能力"""
    caps = list(tool.required_capabilities)

    if tool_name == "bash":
        command = tool_input.get("command", "")
        if any(p in command for p in ["curl", "wget", "pip install", "git clone"]):
            caps.append(CapabilityType.NET)
        if any(p in command for p in [">", ">>", "tee ", "mv ", "cp "]):
            caps.append(CapabilityType.FILE_WRITE)

    return caps
```

### 策略评估流程

```
工具调用 (tool_name, tool_input)
    │
    ├─ 1. 提取工具所需 capabilities（静态声明 + 动态推断）
    │
    ├─ 2. 对每个 capability 按规则评估：
    │     ├─ mandatory_deny 命中？→ Deny（不可覆盖）
    │     ├─ deny 命中？→ Deny
    │     ├─ allow 命中？→ Allow
    │     ├─ need_approval 命中？→ NeedApproval
    │     └─ 都没命中？→ default_action
    │
    ├─ 3. 合并结果（最严格的胜出）
    │     Deny > NeedApproval > Allow
    │
    └─ 返回 PolicyDecision(action, reason, matched_rule)
```

### 数据模型

```python
class PolicyAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    NEED_APPROVAL = "need_approval"

@dataclass
class PolicyDecision:
    action: PolicyAction
    reason: str              # 人类可读的判定理由
    matched_rule: str | None # 命中了哪条配置规则
    capability: CapabilityType
```

### 与现有代码的关系

| 现有机制 | 改造后 |
|---------|--------|
| `RiskLevel` 枚举 | 保留作为工具元数据，不再直接驱动决策 |
| `is_high_risk_operation()` 模式匹配 | 迁移到 TOML `deny_patterns` / `need_approval_patterns` |
| `run_bash()` 中硬编码 `dangerous` 列表 | 迁移到 `[access_control.command].deny_patterns` |
| `PendingConfirmation` 机制 | 由 `PolicyAction.NEED_APPROVAL` 统一触发 |
| `safe_path()` | 迁移到 `[access_control.file]` 规则 + `mandatory_deny` 保证底线 |

## Sandbox Runtime 层

### SandboxProvider 接口

```python
@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    resource_usage: ResourceUsage  # cpu_time, memory_peak, files_written

class SandboxProvider(ABC):
    @abstractmethod
    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        """在隔离环境中执行命令"""

    @abstractmethod
    def get_isolation_level(self) -> str:
        """返回隔离级别描述，便于审计记录"""
```

### SandboxContext

每次执行时由 SandboxManager 根据 TOML 配置构建：

```python
@dataclass
class SandboxContext:
    workdir: Path
    writable_paths: list[str]
    readonly_paths: list[str]
    deny_paths: list[str]
    network_enabled: bool
    allow_domains: list[str]
    timeout: int
    max_memory: str
    max_output: int
    env_vars: dict[str, str]       # 清洗后的环境变量
```

### Provider 实现矩阵

**LocalProvider（纯 Python，跨平台）**

- 文件系统：Python 层校验路径（增强版 safe_path）
- 网络：不隔离（纯 Python 无法做到）
- 进程：subprocess + timeout + max_output
- 凭证：清洗 env，只传递 passthrough_vars
- 隔离强度：弱，但概念完整
- 学习价值：sandbox 接口设计，凭证清洗的意义

**BwrapProvider（Linux namespace）**

```bash
bwrap \
  --ro-bind /usr /usr \
  --bind /workspace /workspace \
  --unshare-pid \
  --unshare-net \
  --new-session \
  --chdir /workspace \
  bash -c "command"
```

- 文件系统：mount namespace，--ro-bind / --bind / 不挂载
- 网络：--unshare-net（完全断网）
- 进程：--unshare-pid + --new-session
- 凭证：隔离的 mount namespace 天然看不到宿主文件
- 隔离强度：中，OS 原语级别
- 学习价值：Linux namespace 如何工作，"看不到就无法访问"

**SeatbeltProvider（macOS sandbox-exec）**

从 SandboxContext 生成 SBPL profile：

```scheme
(version 1)
(deny default)
(allow file-read* (subpath "/usr"))
(allow file-read* file-write* (subpath "/workspace"))
(deny file-read* (subpath "/Users/hf/.ssh"))
(deny network*)
(allow process-exec)
(allow process-fork)
(allow sysctl-read)
(allow mach-lookup)
```

执行方式：`sandbox-exec -f profile.sb bash -c "command"`

- 文件系统：规则过滤，deny 的路径访问返回 EPERM
- 网络：(deny network*) 规则级断网
- 违规可见性：系统日志原生记录 violation
- 隔离强度：中，OS 原语级别
- 学习价值：seatbelt 是"看得到但不让碰"，与 namespace "看不到"是两种不同隔离哲学

**DockerProvider（容器隔离）**

- 文件系统：容器文件系统 + volume mount
- 网络：docker network + 代理出网
- 进程：容器边界 + seccomp + --cap-drop=ALL
- 凭证：代理注入模式（凭证在宿主，不进容器）
- 隔离强度：强
- 学习价值：容器隔离完整链路，"凭证不入沙箱"的工程实现

### 两种隔离哲学

| 维度 | Namespace (Linux bwrap) | Seatbelt (macOS sandbox-exec) |
|------|------------------------|-------------------------------|
| 隔离机制 | mount/PID/net namespace | SBPL profile 规则过滤 |
| 文件系统 | 新 mount namespace，只 bind 需要的 | 进程能看到完整 FS，内核拦截违规访问 |
| 网络 | `--unshare-net` 完全断网 | `(deny network*)` 规则级断网 |
| 违规可见性 | 需要 strace 辅助 | 系统日志原生记录 violation |
| 核心哲学 | **看不到** | **看得到但不让碰** |

### 平台自动选择

```toml
[sandbox]
provider = "auto"    # auto / local / bubblewrap / seatbelt / docker
```

当 `provider = "auto"` 时：

```
检测当前平台
├─ Linux  → bubblewrap 可用？→ BwrapProvider / 否则 → LocalProvider
├─ macOS  → SeatbeltProvider（sandbox-exec 系统自带）
└─ 其他   → LocalProvider
```

### 凭证隔离

```python
class CredentialManager:
    SENSITIVE_PATTERNS = [
        "*_KEY", "*_SECRET", "*_TOKEN", "*_PASSWORD",
        "AWS_*", "OPENAI_*", "ANTHROPIC_*",
        "DATABASE_URL", "REDIS_URL",
    ]

    def clean_env(self, passthrough_vars: list[str]) -> dict[str, str]:
        """从 os.environ 中：
        1. 只保留 passthrough_vars 中列出的变量
        2. 额外过滤匹配 SENSITIVE_PATTERNS 的变量
        3. 返回清洗后的 env dict
        """
```

### SandboxManager 协调逻辑

```python
class SandboxManager:
    def __init__(self, config, workdir, audit):
        self.provider = self._select_provider(config.provider)
        self.credential_mgr = CredentialManager(config.credentials)

    def execute(self, command: str) -> SandboxResult:
        context = SandboxContext(
            workdir=self.workdir,
            writable_paths=self.config.filesystem.writable,
            readonly_paths=self.config.filesystem.readonly,
            deny_paths=self.config.filesystem.deny,
            network_enabled=self.config.network.enabled,
            allow_domains=self.config.network.allow_domains,
            timeout=self.config.resources.timeout,
            max_memory=self.config.resources.max_memory,
            max_output=self.config.resources.max_output,
            env_vars=self.credential_mgr.clean_env(),
        )
        return self.provider.execute(command, context)
```

## Audit 层

### 事件模型

```python
class EventType(Enum):
    POLICY_DECISION = "policy_decision"
    SANDBOX_EXEC = "sandbox_exec"
    SANDBOX_VIOLATION = "sandbox_violation"
    TOOL_CALL = "tool_call"

@dataclass
class AuditEvent:
    timestamp: str               # ISO 8601
    event_type: EventType
    tool_name: str
    tool_input_summary: str      # 截断的输入摘要

    # policy_decision 事件
    decision: PolicyAction | None
    matched_rule: str | None
    capabilities_required: list[str] | None

    # sandbox_exec 事件
    provider: str | None
    exit_code: int | None
    timed_out: bool | None
    resource_usage: dict | None

    # sandbox_violation 事件
    violation_type: str | None   # path_denied / net_denied / timeout
    violation_detail: str | None
```

### 事件链示例

一次 bash 调用的完整事件链：

```jsonl
{"timestamp":"2026-03-24T16:00:01Z","event_type":"policy_decision","tool_name":"bash","tool_input_summary":"pip install flask","decision":"need_approval","matched_rule":"access_control.command.need_approval_patterns[0]","capabilities_required":["exec","net"]}
{"timestamp":"2026-03-24T16:00:05Z","event_type":"policy_decision","tool_name":"bash","tool_input_summary":"pip install flask","decision":"allow","matched_rule":"user_approved"}
{"timestamp":"2026-03-24T16:00:05Z","event_type":"sandbox_exec","tool_name":"bash","tool_input_summary":"pip install flask","provider":"local","exit_code":0,"timed_out":false,"resource_usage":{"cpu_time":1.2,"memory_peak":"45M"}}
```

被拒绝的调用：

```jsonl
{"timestamp":"2026-03-24T16:01:00Z","event_type":"policy_decision","tool_name":"bash","tool_input_summary":"cat ~/.ssh/id_rsa","decision":"deny","matched_rule":"access_control.file.mandatory_deny[0]","capabilities_required":["exec","file_read"]}
```

sandbox 内违规：

```jsonl
{"timestamp":"2026-03-24T16:02:00Z","event_type":"sandbox_exec","tool_name":"bash","tool_input_summary":"python app.py","provider":"bubblewrap","exit_code":1,"timed_out":false}
{"timestamp":"2026-03-24T16:02:00Z","event_type":"sandbox_violation","tool_name":"bash","violation_type":"net_denied","violation_detail":"attempted connection to 10.0.0.1:5432, blocked by --unshare-net"}
```

### AuditLogger

```python
class AuditLogger:
    def record(self, event: AuditEvent) -> None:
        """写入 JSONL 文件"""

    def query(self, filters: dict) -> list[AuditEvent]:
        """按条件查询事件"""

    def summary(self) -> dict:
        """本次会话统计"""
```

### 调用关系

```
AccessController.evaluate() → audit.record(PolicyDecision 事件)
SandboxManager.execute()    → audit.record(SandboxExec 事件)
                            → audit.record(Violation 事件)  # 如果有违规
Agent._execute_tools()      → audit.record(ToolCall 事件)   # 非 sandbox 工具
```

Audit 层不做任何决策，只忠实记录。

## Agent 集成

### _execute_tools() 改造

```python
for tool_block in tool_use_blocks:
    tool = get_tool_with_metadata(tool_name)

    # Step 1: Access Control（所有工具都过）
    decision = self.access_controller.evaluate(tool_name, tool_input)
    self.audit.record(decision_event)

    if decision.action == PolicyAction.DENY:
        result = f"Denied: {decision.reason}"
        continue

    if decision.action == PolicyAction.NEED_APPROVAL:
        self.pending_confirmation = ...  # 复用现有机制
        return

    # Step 2: 分流
    if CapabilityType.EXEC in tool.required_capabilities:
        sandbox_result = self.sandbox.execute(tool_input["command"])
        self.audit.record(sandbox_event)
        result = sandbox_result.stdout
    else:
        result = tool.handler(**tool_input)
        self.audit.record(tool_call_event)
```

### 组件初始化

```python
class Agent:
    def __init__(self, config, workdir, ...):
        # ... 现有初始化 ...
        self.audit = AuditLogger(config.audit)
        self.access_controller = AccessController(config.access_control, audit=self.audit)
        self.sandbox = SandboxManager(config.sandbox, workdir=self.workdir, audit=self.audit)
```

## 配置结构

```toml
# Access Control — 所有工具的权限策略
[access_control]
default_action = "allow"

[access_control.file]
allow = ["{workdir}/**"]
deny = ["~/.ssh/**", "~/.aws/**"]
mandatory_deny = ["~/.ssh/**"]

[access_control.command]
deny_patterns = ["rm -rf /", "sudo *"]
need_approval_patterns = ["pip install *", "apt *"]

# Sandbox Runtime — 仅 bash/code 执行的隔离环境
[sandbox]
provider = "auto"           # auto / local / bubblewrap / seatbelt / docker

[sandbox.filesystem]
writable = ["{workdir}"]
readonly = ["/usr", "/lib"]
deny = ["~/.ssh", "~/.aws", "**/.git/hooks"]

[sandbox.network]
enabled = false
allow_domains = []

[sandbox.resources]
timeout = 120
max_memory = "512M"
max_output = 50000

[sandbox.credentials]
clean_env = true
passthrough_vars = ["PATH", "HOME", "LANG"]

# Audit — 记录一切
[audit]
enabled = true
log_dir = "~/.bourbon/audit/"
format = "jsonl"
record_tool_input = true
record_tool_output = true
```

## 学习路径

### 阶段一：Access Control + Audit + LocalProvider

构建内容：

- `access_control/policy.py` — TOML 规则加载 + 策略评估
- `access_control/capabilities.py` — 能力定义 + 动态推断
- `audit/events.py` + `audit/__init__.py` — 事件模型 + JSONL 记录
- `sandbox/providers/local.py` — 增强版 subprocess（凭证清洗 + 资源限制）
- Agent 集成

学到什么：

- 权限模型核心：default deny vs default allow
- 策略评估链：mandatory_deny > deny > allow 的优先级
- 能力模型：工具声明需要什么，运行时检查有没有
- 凭证清洗：为什么 subprocess 的 env 参数重要
- 审计事件：结构化证据 vs 随意日志

验证方式：

- `bash("cat ~/.ssh/id_rsa")` → deny，审计有记录
- `bash("pip install flask")` → need_approval，用户确认后执行
- `bash("ls -la")` → allow，在 local sandbox 中执行
- 查看 `~/.bourbon/audit/` 下的 JSONL 事件链

### 阶段二：BwrapProvider（Linux）或 SeatbeltProvider（macOS）

构建内容：

- `sandbox/providers/bubblewrap.py` — namespace 隔离
- `sandbox/providers/seatbelt.py` — SBPL profile 生成

学到什么：

- Linux namespace：`--unshare-net` 后 curl 直接失败
- macOS seatbelt：`(deny network*)` 后看到系统日志中的 violation
- 两种隔离哲学："看不到" vs "看得到但拦截"
- 文件系统隔离：mount namespace 下 `ls ~/.ssh` 返回空 vs seatbelt 下返回 EPERM

验证方式：

- `bash("curl example.com")` → 断网 sandbox 中执行，失败
- `bash("cat /etc/passwd")` → readonly sandbox 中执行，成功
- `bash("echo hacked > /etc/passwd")` → 被文件系统隔离阻止
- 对比 local vs bwrap/seatbelt 的审计日志差异

### 阶段三：DockerProvider

构建内容：

- `sandbox/providers/docker.py` — 容器隔离
- `sandbox/credential.py` 扩展 — 代理注入模式

学到什么：

- 容器沙箱完整链路：镜像 → 挂载 → seccomp → capabilities → 网络
- "凭证不入沙箱"的代理注入实现
- `--cap-drop=ALL` 到底 drop 了什么
- 容器 vs OS 原语的开销和能力差异

验证方式：

- 同一命令分别用 local / bwrap / docker 执行，对比行为
- docker sandbox 中尝试访问宿主文件系统，失败
- 三种 provider 审计日志格式一致，isolation_level 不同

### 阶段四：红队验证与策略回归

构建内容：

- `evals/cases/sandbox/` 下的测试用例

学到什么：

- 间接提示注入如何绕过 access control
- 策略配置错误导致的安全漏洞（mandatory_deny 的意义）
- 把安全性变成可回归的自动化测试

验证方式：

- evals 中加入 sandbox 测试用例：exfiltration, path traversal, privilege escalation
- 每种 provider 跑相同用例，对比结果
