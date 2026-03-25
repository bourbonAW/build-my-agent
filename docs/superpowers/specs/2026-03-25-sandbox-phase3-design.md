# Sandbox Phase 3 设计规格：DockerProvider

## 概述

在 Phase 2（BwrapProvider + SeatbeltProvider）基础上，实现 **DockerProvider**——通过 Docker 容器提供完整的 OS 级隔离，并引入 **CredentialProxy** 凭证代理注入模式。

### 设计原则

- **Docker CLI via subprocess**：与 Bwrap/Seatbelt provider 风格一致，不引入 docker SDK 依赖
- **凭证不入沙箱**：宿主端持有真实凭证，容器通过代理访问外部 API
- **默认最小权限**：`--cap-drop=ALL`、`--security-opt no-new-privileges`、`--user nobody`
- **资源限制真正生效**：`--memory` 和 `--cpus` 由 Docker 通过 cgroup v2 强制执行（Phase 2 未实现）

## 概念铺垫：从 bwrap 到 Docker

### bwrap 和 Docker 都做了 namespace 隔离，但文件系统哲学不同

| 维度 | bwrap (Phase 2) | Docker (Phase 3) |
|------|----------------|-----------------|
| 文件系统根 | 宿主 rootfs（选择性挂载） | 镜像 rootfs（overlay 层叠） |
| `ls /home` 结果 | `ENOENT`（路径不存在，未挂载） | 显示镜像中的 `/home`（通常是空的） |
| 文件系统隔离方式 | mount namespace 选择哪些路径存在 | 独立 rootfs，宿主路径默认不可见 |
| 绕过风险 | 内核漏洞、mount propagation 泄漏 | volume 配置错误、docker socket 挂载 |
| cgroup（内存限制） | 无（Phase 2 限制） | `--memory` 原生支持 |
| capabilities | 全部继承宿主 | `--cap-drop=ALL` 明确移除 |
| 运行用户 | 继承调用进程 UID | 可配置（默认 `nobody`） |
| seccomp | 无 | Docker 默认 seccomp profile |

**类比：bwrap 是毛坯房（你搬家具进去，没搬的东西根本不存在）；Docker 是精装公寓（镜像自带家具，你挂载的是额外的东西）。**

### Docker 新增的隔离层

```
bwrap (Phase 2)
  mount namespace
  PID namespace
  net namespace
  --clearenv

Docker (Phase 3) 在此基础上加了：
  + overlay rootfs（镜像层，宿主文件默认不可见）
  + cgroup v2（--memory, --cpus）
  + --cap-drop=ALL（移除全部 Linux capabilities）
  + --security-opt no-new-privileges（禁止提权）
  + --user nobody（非 root 运行）
  + Docker 默认 seccomp profile（限制危险系统调用）
```

## 架构变更

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/bourbon/sandbox/providers/docker.py` | `DockerProvider` — Docker 容器隔离 |
| `src/bourbon/sandbox/credential_proxy.py` | `CredentialProxy` — 宿主端 HTTP 代理，凭证不入容器 |
| `tests/test_sandbox_docker.py` | DockerProvider 集成测试 |
| `tests/test_credential_proxy.py` | CredentialProxy 单元测试 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `src/bourbon/sandbox/providers/__init__.py` | `select_provider()` 新增 `docker` 选项 |
| `src/bourbon/config.py` | `SandboxConfig` 新增 `docker` 子配置（image, pull_policy, user） |

## DockerProvider 实现设计

### 可用性检测

```python
@classmethod
def is_available(cls) -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False
```

注意：必须检测 daemon 是否运行，仅检测 `docker` binary 是否存在不够。

### 构造函数

```python
class DockerProvider(SandboxProvider):
    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._image: str = cfg.get("image", "python:3.11-slim")
        self._pull_policy: str = cfg.get("pull_policy", "if-not-present")
        self._user: str = cfg.get("user", "nobody")
```

`config` 来自 `~/.bourbon/config.toml` 中的 `[sandbox.docker]` 表，由 `SandboxManager` 传入。

### 执行流程

```
execute(command, context)
  → FilesystemPolicy.from_context(context)
  → 如果 network_enabled 且 allow_domains 非空：启动 CredentialProxy
  → _build_docker_args(policy, context) → list[str]
  → subprocess.Popen(args) + BoundedOutput + timeout
  → _parse_violations(result)
  → finally: 停止 CredentialProxy（如果启动了）
  → return SandboxResult
```

注意：不需要手动 `docker rm -f`，因为所有 `docker run` 都带 `--rm` 标志。

### docker run 参数构建

```python
def _build_docker_args(
    self, policy: FilesystemPolicy, context: SandboxContext,
    proxy_addr: str | None = None,
) -> list[str]:
    args = ["docker", "run", "--rm"]

    # 安全加固
    args += ["--cap-drop=ALL"]
    args += ["--security-opt", "no-new-privileges"]

    # 非 root 运行（默认 nobody）
    args += ["--user", self._user]

    # 资源限制（Phase 2 无法实现的能力）
    args += ["--memory", context.max_memory]  # 如 "512M"
    args += ["--cpus", "1"]

    # 网络
    if not context.network_enabled:
        # 完全断网
        args += ["--network", "none"]
    elif proxy_addr:
        # 有凭证代理：允许网络，通过代理访问（凭证在代理注入）
        args += ["--network", "bridge"]
        args += ["-e", f"http_proxy=http://{proxy_addr}"]
        args += ["-e", f"https_proxy=http://{proxy_addr}"]
        args += ["-e", f"HTTP_PROXY=http://{proxy_addr}"]
        args += ["-e", f"HTTPS_PROXY=http://{proxy_addr}"]
    else:
        # network_enabled=True 但无代理：允许直连（无凭证注入）
        args += ["--network", "bridge"]

    # 文件系统：volume mount（只挂载需要的路径）
    for rule in policy.rules:
        if rule.mode == MountMode.READ_WRITE:
            args += ["-v", f"{rule.path}:{rule.path}:rw"]
        elif rule.mode == MountMode.READ_ONLY:
            args += ["-v", f"{rule.path}:{rule.path}:ro"]
        # DENY: 不挂载，容器内根本看不到

    # 工作目录
    args += ["-w", str(context.workdir)]

    # 环境变量（清洗后的）
    for key, value in context.env_vars.items():
        args += ["-e", f"{key}={value}"]

    # 镜像 + 命令
    args += [self._image]
    args += ["bash", "-c", command]

    return args
```

### 违规检测

Docker 的违规检测比 Phase 2 更可靠，有明确的 exit code 语义：

```python
def _parse_violations(self, result: SandboxResult) -> list[Violation]:
    violations: list[Violation] = []

    # OOM kill：exit code 137（128 + SIGKILL）
    if result.exit_code == 137 and not result.timed_out:
        violations.append(Violation(
            type="oom_killed",
            detail=f"process exceeded memory limit ({self._context_max_memory})",
        ))

    # 网络违规
    stderr_lower = result.stderr.lower()
    if "network is unreachable" in stderr_lower or "connection refused" in stderr_lower:
        violations.append(Violation(
            type="net_denied",
            detail="container network disabled (--network=none)",
        ))

    # capabilities 违规：EPERM from --cap-drop=ALL
    if "operation not permitted" in stderr_lower and result.exit_code != 0:
        violations.append(Violation(
            type="cap_denied",
            detail="operation denied by capability restrictions (--cap-drop=ALL)",
        ))

    return violations
```

### isolation level

```python
def get_isolation_level(self) -> str:
    return f"docker (container isolation, image={self._image})"
```

## CredentialProxy 设计

### 问题与方案

**问题：** 容器需要调用外部 API（pip install 私有仓库、访问 LLM API 等），但凭证（API key、token）不能进入容器——一旦进入，恶意代码可以窃取并通过任意渠道泄漏。

**方案：** 宿主端运行一个轻量 HTTP 代理，容器通过代理访问外部，代理在宿主端注入凭证。

**K8s 类比：** 这就是极简版的 Vault Agent Injector——sidecar 持有 token，主容器通过 localhost/bridge IP 拿到认证，但没有真实 token。

### 威胁模型与防御

```
威胁：恶意代码发现代理地址，尝试非授权访问
防御层：
  1. 代理只接受来自 sandbox 容器 IP 的请求（通过 Docker bridge 网络）
  2. 代理只转发到 allow_domains 白名单中的域名
  3. 请求中注入的凭证在宿主端由 CredentialManager 提供，容器无法直接获取
```

### 网络拓扑

```
容器 (bridge network)
  → http_proxy=http://172.17.0.1:PORT
  → CredentialProxy 监听 172.17.0.1:PORT（宿主 docker0 接口）
  → 检查请求来源 IP 是否为已知容器 IP
  → 检查目标域名是否在 allow_domains 中
  → 如果通过：注入凭证头，转发到真实目标
  → 返回响应给容器
```

注意：
- Linux：宿主 docker0 桥接 IP 通常是 `172.17.0.1`，可通过 `docker network inspect bridge` 获取
- Docker Desktop（macOS/Windows）：使用 `host.docker.internal` 解析
- 代理地址在 `docker run` 时通过环境变量传入容器（`http_proxy`、`https_proxy`）

### 数据模型

```python
class CredentialProxy:
    """Host-side HTTP proxy for credential injection.

    Runs as a thread in the agent process. Container connects via
    http_proxy/https_proxy environment variables.

    The container never receives the actual credentials — the proxy
    intercepts requests and injects Authorization headers on the host side.
    """

    def __init__(
        self,
        credential_mgr: CredentialManager,
        allow_domains: list[str],
        host_ip: str = "127.0.0.1",
        port: int = 0,  # 0 = OS 随机分配
    ) -> None:
        self.credential_mgr = credential_mgr
        self.allow_domains = allow_domains
        self.host_ip = host_ip
        self._server: HTTPServer | None = None
        self._thread: Thread | None = None
        self._actual_port: int = 0

    def start(self) -> str:
        """Start proxy server. Returns 'host_ip:port' address."""

    def stop(self) -> None:
        """Stop proxy server and thread."""

    @property
    def address(self) -> str:
        """Returns 'ip:port' for container to connect to."""
        return f"{self.host_ip}:{self._actual_port}"

    def _is_domain_allowed(self, target: str) -> bool:
        """Check if target matches allow_domains list.

        Matching rules:
        - Exact match: "api.example.com" matches only "api.example.com"
        - Wildcard prefix: "*.example.com" matches "api.example.com" and "cdn.example.com"
          but NOT "example.com" itself
        - No regex, no IP ranges (Phase 3 scope)
        """

    def _handle_request(self, request) -> None:
        """Validate domain, inject credentials, forward request."""
```

### 实现细节

```python
class _ProxyHandler(BaseHTTPRequestHandler):
    """HTTP request handler for CredentialProxy."""

    def do_CONNECT(self) -> None:
        """Handle HTTPS CONNECT tunnel requests."""
        # HTTPS 隧道：代理在宿主端解密，注入凭证，再加密发送
        # Phase 3 简化：只支持 HTTP，HTTPS 通过转发头部实现

    def do_GET(self) -> None:
        self._handle_proxy_request()

    def do_POST(self) -> None:
        self._handle_proxy_request()

    def _handle_proxy_request(self) -> None:
        # 1. 解析目标 URL
        # 2. 检查域名白名单
        if not self.server.proxy.is_domain_allowed(target_host):
            self.send_response(403)
            return
        # 3. 从 CredentialManager 获取凭证
        creds = self.server.proxy.credential_mgr.get_for_domain(target_host)
        # 4. 注入 Authorization header
        # 5. 转发请求
        # 6. 返回响应
```

### 已知限制（Phase 3 scope）

- **HTTP only**：Phase 3 代理只处理 HTTP（`http://` 和 `https://`），不做 TLS 中间人（MITM）。实际的 pip install 通常走 HTTP 代理的 CONNECT 方法。完整 TLS 支持推迟。
- **凭证类型简单**：Phase 3 只注入 `Authorization: Bearer <token>`，不支持复杂的 OAuth 流程

## 镜像配置

```toml
# ~/.bourbon/config.toml
[sandbox.docker]
image = "python:3.11-slim"      # 默认镜像
pull_policy = "if-not-present"  # never | always | if-not-present
user = "nobody"                 # 容器内运行用户
```

| pull_policy | 行为 |
|------------|------|
| `never` | 镜像不存在 → 报错 |
| `always` | 每次执行前 pull |
| `if-not-present` | 镜像不存在时 pull，存在则跳过（默认） |

## 与 Phase 2 的差异对比

| 特性 | BwrapProvider | SeatbeltProvider | DockerProvider |
|------|-------------|-----------------|----------------|
| 文件系统 | mount namespace（宿主 rootfs） | 宿主 rootfs + MAC 过滤 | overlay rootfs（镜像层） |
| 内存限制 | 无 | 无 | `--memory` via cgroup |
| 非 root | 无（继承调用方） | 无 | `--user nobody` |
| capabilities | 继承宿主 | 继承宿主 | `--cap-drop=ALL` |
| 凭证代理 | 无 | 无 | CredentialProxy（可选） |
| 启动开销 | ~50ms | ~10ms | ~1-2s（镜像加载） |
| `ls /home` 断网模式 | ENOENT | ENOENT/EPERM | 镜像中的空目录 |

## 测试策略

纯集成测试 + skipif：

```python
# tests/test_sandbox_docker.py
pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="requires Docker",
)

class TestDockerProvider:
    def test_basic_execution(self): ...
    def test_filesystem_isolation(self):
        """路径未挂载时容器内不存在（不是 ENOENT，而是镜像中的空目录）"""
    def test_readonly_enforcement(self): ...
    def test_network_isolation(self):
        """--network=none 时网络不可用"""
    def test_memory_limit(self):
        """内存超限时 OOM kill（exit 137）"""
    def test_env_clean(self): ...
    def test_timeout(self): ...
    def test_nonroot_user(self):
        """容器内以 nobody 运行，whoami 返回 nobody"""
    def test_cap_drop(self):
        """--cap-drop=ALL 后 chmod +s 等 setuid 操作失败"""
    def test_isolation_level(self): ...
    def test_is_available_without_docker(self): ...

# tests/test_credential_proxy.py（无平台依赖，纯单元测试）
class TestCredentialProxy:
    def test_start_stop(self): ...
    def test_domain_allow(self): ...
    def test_domain_deny(self): ...
    def test_credential_injection(self): ...
    def test_address_format(self): ...
```

## 学习验证

Phase 3 完成后应能亲手验证：

| 验证 | 预期 |
|------|------|
| `bash("ls ~/.ssh")` | 容器内无此路径（镜像中没有 ~/.ssh） |
| `bash("curl example.com")` 断网 | `network is unreachable` |
| `bash("python -c 'x=[0]*10**9'")` 内存限制 | OOM killed (exit 137) |
| `bash("whoami")` | `nobody` |
| `bash("chmod +s /bin/bash")` | `Operation not permitted`（cap_denied） |
| `bash("env")` | 无 ANTHROPIC_API_KEY 等宿主凭证 |
| 通过凭证代理 pip install | 成功，容器内无 token，代理注入了 Authorization |

**费曼检验：** 能解释"为什么 Docker 比 bwrap 更安全但也更慢"——Docker 用镜像 rootfs 取代宿主 rootfs（宿主文件默认完全不可见），加上 cgroup 内存限制和 capabilities 清零，代价是需要启动和管理容器进程，约多 1-2 秒的开销。

## 已知限制（Phase 3 scope）

- **allow_domains 精细控制**：CredentialProxy 实现域名白名单，但不支持 IP 范围过滤
- **TLS MITM**：凭证代理不做完整 TLS 解密/重加密，只支持 HTTP 和 CONNECT 隧道
- **Docker Desktop 差异**：`host.docker.internal` 在 Linux 需要额外配置（`--add-host`），在 Docker Desktop 内置支持
- **镜像安全**：镜像本身的安全性不在 Phase 3 scope（镜像扫描等推迟）
