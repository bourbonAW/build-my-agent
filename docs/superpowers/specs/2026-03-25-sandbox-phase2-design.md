# Sandbox Phase 2 设计规格：OS 级隔离 Provider

## 概述

在 Phase 1（Access Control + Audit + LocalProvider）基础上，实现两个 OS 级隔离 provider：

- **BwrapProvider** — Linux namespace 隔离（bubblewrap）
- **SeatbeltProvider** — macOS sandbox-exec（SBPL profile）

### 设计原则

- **扁平 provider + 共享策略**：不用继承，每个 provider 独立实现 `execute()`，通过 `FilesystemPolicy` 共享路径映射逻辑
- **职责单一**：网络隔离完全下沉到 provider，SandboxManager 不做关键字扫描（LocalProvider 除外）
- **Provider 级违规报告**：每个 provider 自己检测并返回结构化违规信息
- **纯集成测试**：用 `pytest.mark.skipif` 跳过不可用平台，不 mock OS 工具

## 概念铺垫：从 Docker 到裸 namespace

### Docker 做了什么

`docker run --rm -it ubuntu bash` 在底层（通过 runc）大致做了：

```
clone(CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWNET | ...)
  → mount namespace  → pivot_root 到容器镜像的 rootfs
  → PID namespace    → 容器内 PID 1 是你的进程
  → net namespace    → 独立网络栈（需要 veth pair 才能联网）
  → user namespace   → UID 映射
  + seccomp profile → 限制可用系统调用
  + cgroups → 限制 CPU/内存
```

### Bubblewrap (bwrap) — Docker 的"毛坯房"版

bwrap 做的事和 Docker 一样，只是更轻量、更直接：

```bash
bwrap \
  --ro-bind /usr /usr \          # mount namespace: 只读挂载 /usr
  --bind /workspace /workspace \ # mount namespace: 可写挂载
  --unshare-pid \                # PID namespace: 隔离进程视图
  --unshare-net \                # net namespace: 断网（没有 veth = 没有网络）
  --new-session \                # 新 session，防止 TIOCSTI 注入
  --die-with-parent \            # 父进程死了子进程也死
  bash -c "command"
```

关键区别：Docker 给你一个完整的容器（镜像 + namespace + cgroups + 网络），bwrap 只给你 namespace——没有镜像，没有 cgroups，你手动挑选要挂载什么进去。

**类比：Docker 是精装公寓，bwrap 是毛坯房——你自己决定搬什么家具进去。**

### macOS Seatbelt (sandbox-exec) — 完全不同的路

```bash
sandbox-exec -f profile.sb bash -c "command"
```

它不创建新 namespace。进程看到的文件系统、网络栈、PID 空间和宿主完全一样。但内核装了一个"过滤器"（TrustedBSD MAC framework），每次进程做系统调用时检查 SBPL 规则：

```scheme
(version 1)
(deny default)                              ; 默认拒绝一切
(allow file-read* (subpath "/usr"))         ; 允许读 /usr
(allow file-read* file-write* (subpath "/workspace"))
(deny file-read* (subpath "/Users/hf/.ssh")) ; 明确拒绝 .ssh
(deny network*)                             ; 断网
```

**类比：bwrap 是"把你关进一个只有几面墙的房间，房间外的东西你看不到"。Seatbelt 是"你站在整栋楼里，但每扇门上都有锁，你只有部分钥匙"。**

### 两种隔离哲学对比

| 维度 | Bwrap (Linux) | Seatbelt (macOS) |
|------|--------------|-------------------|
| 隔离原理 | 新 namespace，只挂载需要的 | 全局视图 + 内核规则过滤 |
| 看不到 vs 不让碰 | 路径不存在 → `ENOENT` | 路径存在但被拦截 → `EPERM` |
| 网络隔离 | 空的 net namespace = 无网络栈 | `(deny network*)` = 系统调用被拒 |
| 违规可见性 | stderr: "No such file" | stderr: "Operation not permitted" |
| 核心哲学 | **看不到** | **看得到但不让碰** |

## 架构变更

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/bourbon/sandbox/policy.py` | `FilesystemPolicy` — 中间表示，从 SandboxContext 构建 |
| `src/bourbon/sandbox/providers/bubblewrap.py` | `BwrapProvider` — Linux namespace 隔离 |
| `src/bourbon/sandbox/providers/seatbelt.py` | `SeatbeltProvider` — macOS sandbox-exec |
| `tests/test_filesystem_policy.py` | FilesystemPolicy 单元测试 |
| `tests/test_sandbox_bwrap.py` | BwrapProvider 集成测试 |
| `tests/test_sandbox_seatbelt.py` | SeatbeltProvider 集成测试 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `src/bourbon/sandbox/runtime.py` | 新增 `Violation` 数据类；提取 `BoundedOutput` 为公共工具类；`SandboxProvider` 新增 `is_available()` 类方法；`SandboxResult` 新增 `violations` 字段 |
| `src/bourbon/sandbox/providers/__init__.py` | `select_provider()` 扩展 auto 逻辑 |
| `src/bourbon/sandbox/__init__.py` | 网络关键字扫描限定为 LocalProvider 路径；新增 violations 审计记录 |
| `src/bourbon/sandbox/providers/local.py` | `_BoundedOutput` 提取到 `runtime.py`；改为 import |

## FilesystemPolicy 中间表示

### 为什么需要这一层

`SandboxContext` 的三个列表（`writable_paths`、`readonly_paths`、`deny_paths`）是用户视角的配置。但 bwrap 需要转成 `--bind`/`--ro-bind` 参数，seatbelt 需要转成 SBPL `(allow file-read*)`/`(deny file-read*)` 规则。`FilesystemPolicy` 提供统一的有序规则列表，每个 provider 各自遍历生成自己的格式。

### 数据模型

```python
class MountMode(Enum):
    READ_ONLY = "ro"
    READ_WRITE = "rw"
    DENY = "deny"

@dataclass(slots=True)
class MountRule:
    """单条挂载规则"""
    path: str           # 绝对路径（已展开 ~ 和 {workdir}）
    mode: MountMode     # READ_ONLY / READ_WRITE / DENY

@dataclass(slots=True)
class FilesystemPolicy:
    """文件系统策略中间表示"""
    rules: list[MountRule]

    @classmethod
    def from_context(cls, context: SandboxContext) -> FilesystemPolicy:
        """将 SandboxContext 的三级路径转为有序规则列表。

        优先级：deny > readonly > writable（与 access_control 层一致）。
        workdir 始终作为 READ_WRITE 规则包含（即使未在 writable_paths 中显式声明）。
        所有路径在构建前展开为绝对路径（~ 展开 + symlink 解析）。
        """
```

### 路径处理

所有路径在进入 `FilesystemPolicy` 前必须是绝对路径。`from_context()` 负责：

1. 展开 `~` → `os.path.expanduser()`
2. 解析 symlink → `os.path.realpath()`（防止 symlink 逃逸，尤其是 bwrap 场景）
3. 确保 workdir 始终作为 `READ_WRITE` 规则出现

## Provider 接口扩展

### 新增 Violation 数据类

```python
@dataclass(slots=True)
class Violation:
    """Sandbox 内检测到的违规"""
    type: str       # "path_denied" / "net_denied" / "exec_denied"
    detail: str     # 人类可读的描述
```

### SandboxResult 扩展

```python
@dataclass(slots=True)
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    resource_usage: ResourceUsage
    violations: list[Violation] = field(default_factory=list)  # 新增
```

违规检测不作为独立方法，而是 `execute()` 返回的 `SandboxResult` 直接包含 `violations`。理由：违规检测和执行是同一个流程的产物（stderr、exit code），拆开反而要传递中间状态。

### SandboxProvider 接口扩展

```python
class SandboxProvider(ABC):
    @abstractmethod
    def execute(self, command: str, context: SandboxContext) -> SandboxResult:
        """在隔离环境中执行命令"""

    @abstractmethod
    def get_isolation_level(self) -> str:
        """返回隔离级别描述"""

    @classmethod
    def is_available(cls) -> bool:
        """检测当前环境是否支持此 provider。默认返回 True。"""
        return True
```

`is_available()` 是类方法，因为在实例化之前就要调用（`select_provider()` 用它决定选哪个）。

### BoundedOutput 提取

从 `local.py` 的 `_BoundedOutput` 移到 `runtime.py` 作为公共 `BoundedOutput`，三个 provider 共用。实现不变，去掉下划线前缀。

## BwrapProvider 实现设计

### 可用性检测

```python
@classmethod
def is_available(cls) -> bool:
    return shutil.which("bwrap") is not None
```

### 执行流程

```
execute(command, context)
  → FilesystemPolicy.from_context(context)
  → _build_args(policy, context) → list[str]
  → subprocess.Popen(args, ...) + BoundedOutput + timeout
  → _parse_violations(result)
  → return SandboxResult
```

### 参数构建

```python
def _build_args(self, policy: FilesystemPolicy, context: SandboxContext) -> list[str]:
    args = ["bwrap"]

    # 基础系统路径（命令能运行的最小依赖）
    # 这组路径硬编码在 provider 中，不暴露给用户配置
    args += ["--ro-bind", "/usr", "/usr"]
    args += ["--ro-bind", "/lib", "/lib"]       # 动态链接器
    args += ["--ro-bind", "/lib64", "/lib64"]   # x86_64 兼容
    args += ["--ro-bind", "/bin", "/bin"]
    args += ["--ro-bind", "/sbin", "/sbin"]
    args += ["--proc", "/proc"]
    args += ["--dev", "/dev"]                   # /dev/null, /dev/zero, /dev/urandom

    # 用户配置的文件系统规则
    for rule in policy.rules:
        if rule.mode == MountMode.DENY:
            pass  # 不挂载 = namespace 中看不到
        elif rule.mode == MountMode.READ_ONLY:
            args += ["--ro-bind", rule.path, rule.path]
        elif rule.mode == MountMode.READ_WRITE:
            args += ["--bind", rule.path, rule.path]

    # 网络隔离
    if not context.network_enabled:
        args += ["--unshare-net"]

    # 进程隔离
    args += ["--unshare-pid"]
    args += ["--new-session"]       # 防止 TIOCSTI 终端注入
    args += ["--die-with-parent"]   # 父进程退出时清理子进程

    # 环境变量（清洗后的）
    args += ["--clearenv"]
    for key, value in context.env_vars.items():
        args += ["--setenv", key, value]

    # 工作目录 + 命令
    args += ["--chdir", str(context.workdir)]
    args += ["--", "bash", "-c", command]

    return args
```

### deny 路径的子路径覆盖

当 deny 路径是 writable 路径的子路径时（如 workdir 可写但 `workdir/.git/hooks` 要 deny），bwrap 支持在 `--bind` 之后用 `--tmpfs` 覆盖子路径，使其变成空的临时文件系统：

```bash
--bind /workspace /workspace       # workdir 可写
--tmpfs /workspace/.git/hooks      # 子路径覆盖为空 tmpfs
```

`_build_args()` 在处理 DENY 规则时检测：如果 deny 路径是某个已挂载路径的子路径，则追加 `--tmpfs` 覆盖。

### 违规检测

```python
def _parse_violations(self, result: SandboxResult) -> list[Violation]:
    """从 stderr 推断违规（尽力而为）。

    bwrap namespace 中，被隔离的路径不存在——"No such file or directory"
    既可能是真的不存在，也可能是 namespace 隔离导致的，无法精确区分。
    网络违规更容易检测：空 net namespace 中的网络调用返回特定错误。
    """
    violations = []
    if "Network is unreachable" in result.stderr:
        violations.append(Violation(
            type="net_denied",
            detail="network isolated by namespace (--unshare-net)"
        ))
    return violations
```

### isolation level

```python
def get_isolation_level(self) -> str:
    return "bubblewrap (Linux namespace)"
```

## SeatbeltProvider 实现设计

### 可用性检测

```python
@classmethod
def is_available(cls) -> bool:
    return sys.platform == "darwin"
```

`sandbox-exec` 是 macOS 系统自带的，不需要额外安装检测。

### 执行流程

```
execute(command, context)
  → FilesystemPolicy.from_context(context)
  → _build_profile(policy, context) → str (SBPL 文本)
  → 写入临时 .sb 文件
  → subprocess.Popen(["sandbox-exec", "-f", profile_path, "bash", "-c", command])
  → BoundedOutput + timeout
  → _parse_violations(result)
  → finally: 清理临时文件
  → return SandboxResult
```

### SBPL Profile 生成

```python
def _build_profile(self, policy: FilesystemPolicy, context: SandboxContext) -> str:
    """将 FilesystemPolicy 转为 SBPL (Sandbox Profile Language) 文本。

    SBPL 是 Scheme-like DSL，macOS 内核编译为过滤规则。
    当多条规则匹配同一路径时，最后添加（最靠后）的规则胜出。
    因此我们先生成 allow 规则，再生成 deny 规则——deny 写在后面，
    确保 deny 路径即使被更宽的 allow 覆盖也能拦截。
    """
    lines = [
        "(version 1)",
        "(deny default)",  # 默认拒绝一切——白名单模式
        "",
        "; === 基础系统权限（命令能运行的最小集）===",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",            # Mach IPC，macOS 上很多操作依赖
        "(allow ipc-posix-shm-read*)",    # POSIX 共享内存（部分工具需要）
        "(allow ipc-posix-shm-write*)",
        "(allow signal (target self))",   # 允许向自己发信号
        "",
        "; === /dev 访问 ===",
        '(allow file-read* file-write* (subpath "/dev"))',
        "",
        "; === 文件系统规则（allow 先写，deny 后写覆盖）===",
    ]

    # allow 规则
    for rule in policy.rules:
        if rule.mode == MountMode.READ_WRITE:
            lines.append(
                f'(allow file-read* file-write* (subpath "{rule.path}"))'
            )
        elif rule.mode == MountMode.READ_ONLY:
            lines.append(
                f'(allow file-read* (subpath "{rule.path}"))'
            )

    # deny 规则最后写，优先级最高
    for rule in policy.rules:
        if rule.mode == MountMode.DENY:
            lines.append(
                f'(deny file-read* file-write* (subpath "{rule.path}"))'
            )

    # 网络（显式规则，不依赖 deny default 的隐式行为）
    lines.append("")
    if context.network_enabled:
        lines.append("(allow network*)")
    else:
        lines.append("(deny network*)")

    return "\n".join(lines)
```

### 基础权限说明

| 权限 | 用途 |
|------|------|
| `process-exec` / `process-fork` | bash 能启动子进程 |
| `sysctl-read` | 读取系统信息（很多工具依赖） |
| `mach-lookup` | Mach IPC，macOS 上 `ls`、`env` 等基础命令都依赖 |
| `ipc-posix-shm-*` | POSIX 共享内存，部分工具需要 |
| `signal (target self)` | 允许进程向自己发信号（正常进程生命周期） |
| `/dev` 子路径 | `/dev/null`、`/dev/zero`、`/dev/urandom`，很多命令和库依赖 |

### 违规检测

```python
def _parse_violations(self, result: SandboxResult) -> list[Violation]:
    """从 stderr 检测 sandbox 违规。

    sandbox-exec 违规时进程收到 EPERM，stderr 出现
    "Operation not permitted"。Phase 2 先从 stderr 推断，保持简单。
    """
    violations = []
    if "Operation not permitted" in result.stderr:
        violations.append(Violation(
            type="path_denied",
            detail="filesystem access denied by seatbelt profile"
        ))
    # 网络违规也表现为 "Operation not permitted"，
    # 但通常伴随 "network" 或 "connect" 关键词
    stderr_lower = result.stderr.lower()
    if ("network" in stderr_lower or "connect" in stderr_lower) and "denied" in stderr_lower:
        violations.append(Violation(
            type="net_denied",
            detail="network access denied by seatbelt profile"
        ))
    return violations
```

### 临时文件管理

`sandbox-exec -f` 需要文件路径，不能从 stdin 读。用 `tempfile.NamedTemporaryFile` 写入后执行，`finally` 中 `os.unlink()` 清理。

### isolation level

```python
def get_isolation_level(self) -> str:
    return "seatbelt (macOS sandbox-exec)"
```

## SandboxManager 修改

### 网络检查下沉

```python
def execute(self, command: str, tool_name: str = "bash") -> SandboxResult:
    # ... 构建 context ...

    # 网络关键字扫描只在 LocalProvider 路径生效
    # Phase 2 provider 有 OS 级网络隔离，不需要预检查
    if (
        not context.network_enabled
        and isinstance(self.provider, LocalProvider)
        and self._contains_network_activity(command)
    ):
        # ... 返回 violation result（现有逻辑不变）...

    result = self.provider.execute(command, context)

    # 记录 provider 返回的 violations 到审计日志
    for v in result.violations:
        self.audit.record(
            AuditEvent.sandbox_violation(
                tool_name=tool_name,
                tool_input_summary=command[:200],
                reason=f"{v.type}: {v.detail}",
            )
        )

    # ... 记录 sandbox_exec 事件（现有逻辑不变）...
    return result
```

## Provider 自动选择

```python
def select_provider(name: str) -> SandboxProvider:
    normalized = name.lower()

    if normalized == "bubblewrap":
        if not BwrapProvider.is_available():
            raise SandboxProviderNotFound(
                "bubblewrap not found. Install it or set provider = \"auto\""
            )
        return BwrapProvider()

    if normalized == "seatbelt":
        if not SeatbeltProvider.is_available():
            raise SandboxProviderNotFound(
                "seatbelt requires macOS. Set provider = \"auto\""
            )
        return SeatbeltProvider()

    if normalized == "local":
        return LocalProvider()

    if normalized == "auto":
        if sys.platform == "linux" and BwrapProvider.is_available():
            return BwrapProvider()
        if sys.platform == "darwin":
            return SeatbeltProvider()
        return LocalProvider()

    raise SandboxProviderNotFound(f"Unknown provider: {name}")
```

显式指定但不可用 → 报错（不静默降级）。`auto` → 按平台选最强可用的。

## 已知限制（Phase 2 scope）

### max_memory 未强制执行

- bwrap 本身不限制内存，需要 cgroup v2 配合
- seatbelt 没有内存策略能力
- `SandboxContext.max_memory` 在 Phase 2 仅由 LocalProvider 的 timeout 间接限制
- 真正的内存限制推迟到 Phase 3（Docker provider 通过 `--memory` 原生支持）

### 违规检测是尽力而为

- bwrap 的文件路径违规无法精确检测（`ENOENT` 无法区分"真的不存在"和"被隔离了"）
- seatbelt 的违规检测基于 stderr 关键词匹配，不是 100% 可靠
- 两者都是审计辅助信息，不是安全决策依据

### allow_domains 未实现

- `SandboxContext.allow_domains` 在 Phase 2 不生效
- bwrap `--unshare-net` 是全有或全无（完全断网或完全联网）
- 细粒度域名控制需要额外的网络代理层，推迟到 Phase 3

## 测试策略

纯集成测试 + `pytest.mark.skipif`：

```python
# tests/test_sandbox_bwrap.py
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bwrap") is None,
    reason="requires Linux with bubblewrap installed"
)

class TestBwrapProvider:
    def test_basic_execution(self):
        """命令能在 bwrap 中正常执行"""

    def test_filesystem_isolation(self):
        """deny 路径在 namespace 中不存在（ENOENT）"""

    def test_readonly_enforcement(self):
        """readonly 路径不可写"""

    def test_network_isolation(self):
        """--unshare-net 后网络不可用"""

    def test_workdir_writable(self):
        """工作目录可读写"""

    def test_env_clean(self):
        """只有 passthrough 的环境变量可见"""

    def test_timeout(self):
        """超时后进程被终止"""

    def test_die_with_parent(self):
        """父进程退出后子进程被清理"""
```

```python
# tests/test_sandbox_seatbelt.py
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="requires macOS"
)

class TestSeatbeltProvider:
    def test_basic_execution(self):
        """命令能在 sandbox-exec 中正常执行"""

    def test_filesystem_deny(self):
        """deny 路径访问返回 EPERM"""

    def test_readonly_enforcement(self):
        """readonly 路径不可写"""

    def test_network_isolation(self):
        """deny network* 后网络不可用"""

    def test_profile_cleanup(self):
        """执行后临时 .sb 文件被清理"""

    def test_violation_detection(self):
        """violations 列表中包含结构化违规信息"""
```

```python
# tests/test_filesystem_policy.py — 纯单元测试，无平台依赖
class TestFilesystemPolicy:
    def test_from_context_ordering(self):
        """deny 规则优先级最高"""

    def test_workdir_always_included(self):
        """workdir 始终作为 READ_WRITE 规则出现"""

    def test_path_expansion(self):
        """~ 和 symlink 被正确展开"""

    def test_empty_paths(self):
        """所有路径列表为空时仍包含 workdir"""
```

## 学习验证

Phase 2 完成后应能亲手验证：

| 验证 | Linux (bwrap) | macOS (seatbelt) |
|------|--------------|------------------|
| `bash("ls ~/.ssh")` | `No such file or directory` | `Operation not permitted` |
| `bash("curl example.com")` 断网 | `Network is unreachable` | `Operation not permitted` |
| `bash("echo test > /usr/test")` | `Read-only file system` | `Operation not permitted` |
| `bash("env")` | 只有 PATH, HOME, LANG | 只有 PATH, HOME, LANG |
| 审计日志 `violations` | `net_denied` + namespace detail | `path_denied` + seatbelt detail |

**费曼检验：** 能向别人解释——"bwrap 用 Linux namespace 让进程看不到被隔离的资源（ENOENT），sandbox-exec 让进程看到但通过内核 MAC 框架拦截访问（EPERM）。前者构造一个最小世界，后者在完整世界中加锁。"
