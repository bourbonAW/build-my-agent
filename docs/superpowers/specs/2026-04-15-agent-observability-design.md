# Bourbon Agent Observability 设计

**日期**：2026-04-15  
**状态**：v2，已吸收 2026-04-16 设计审查问题
**范围**：为 Bourbon 接入 OpenTelemetry 标准追踪，对接 Langfuse 等外部平台，实现 agent run 可视化 debug

---

## 背景

Agent 开发的 debug 困难根本上源于**控制流由 LLM 决定**——哪个工具被调用、调用顺序、何时停止，都不是静态 if/else，而是 LLM 的输出。传统断点调试在这里失效：

- 断点无法预知 LLM 下一步调用哪个工具
- 错误往往在第 N 轮工具调用后才浮现，回溯链很长
- 非确定性使 bug 难以稳定复现

社区主流解法是**结构化追踪（Structured Tracing）**：把 agent 执行拍平成 span 树，每个操作（LLM 调用、工具执行）是一个 span，通过 Langfuse、AgentOps 等平台可视化查询。

bourbon 的目标是对接这一生态，而不是重复造轮子。

---

## 设计目标

1. 遵循 **OpenTelemetry GenAI 语义约定**，与任何支持 OTel 的后端兼容（Langfuse、Arize、Jaeger 等）
2. 覆盖**完整用户请求生命周期**：`step()` / `step_stream()` / `resume_permission_request()` 都有 root span
3. 每个 root span 下包含 LLM span 和 tool span；工具执行发生在 LLM 调用返回之后，因此 tool span 是 root span 的子 span，而不是 LLM span 的子 span
4. 保持 observability 代码与业务逻辑分离，但不牺牲正确性：插桩点包括 Agent lifecycle、LLM 调用、queue/direct tool 执行、权限恢复
5. **禁用时接近零开销**：未启用或未安装 OTel SDK 时所有调用都是 no-op
6. **可选依赖**：OTel SDK 不强制安装，只在 `[observability]` extra 里

## 非目标（Non-goals）

- **不支持 Metrics / Logs**：本次只接入 Traces，metrics 与 logs 未来再扩展
- **不支持跨进程分布式 tracing**：当前 Bourbon subagent 是 in-process；未来若 subagent 变成独立进程，需要单独设计 trace context 注入
- **不支持自定义 SpanProcessor**：仅内置 `BatchSpanProcessor`（带安全上限），不提供用户自定义 processor 的扩展点
- **不测试外部平台网络连通性**：Langfuse/Jaeger 等后端的网络测试属于外部服务范围
- **不做 deterministic replay**：本次只记录追踪，不提供回放

---

## 架构总览

```
Agent.__init__
  └─ ObservabilityManager(config.observability)
       └─ self._tracer: BourbonTracer   # per-Agent，不使用可变全局 active tracer

agent.step() / agent.step_stream()
  └─ [root span: invoke_agent bourbon, entrypoint=step|step_stream]
       ├─ system prompt rebuild / context injection / user message save
       ├─ microcompact / maybe_compact
       ├─ [LLM span: chat <model>]
       ├─ _execute_tools()
       │    ├─ queue tool span: execute_tool Read
       │    ├─ queue tool span: execute_tool Bash
       │    ├─ direct tool span: execute_tool compress
       │    └─ direct tool span: execute_tool <denied|unknown|suspended>
       └─ [LLM span: chat <model>]  # 后续轮次

agent.resume_permission_request()
  └─ [root span: invoke_agent bourbon, entrypoint=resume_permission]
       ├─ tool span for approval/rejection result
       ├─ remaining queued/direct tools, if any
       └─ continuation _run_conversation_loop()
```

**Root span 覆盖范围**：root span 从 `step()` / `step_stream()` / `resume_permission_request()` 方法入口开始，覆盖 prompt rebuild、context injection、用户消息持久化、microcompact、maybe_compact、LLM 调用、工具执行和权限恢复后的后续 LLM 轮次。这样 trace 才能匹配“完整用户请求生命周期”的目标。

**Per-Agent tracer**：`Agent.__init__` 创建 `self._obs_manager` 和 `self._tracer`。业务代码使用 `self._tracer`，`ToolExecutionQueue` 通过构造参数接收 tracer。不要使用 module-level mutable active tracer；否则同一进程中 enabled Agent、disabled Agent、subagent/background Agent 会互相污染。`enabled=false` 必须是当前 Agent 的 hard kill switch。

**OTel Context 传播**：OpenTelemetry Python 使用 `contextvars` 管理 current span，但 `ThreadPoolExecutor` 不会自动把提交线程的 context 复制到 worker 线程。`ToolExecutionQueue.execute_all()` 必须在 root span 内捕获 queue parent context，并在每次 submit/callback 时使用该 context 的副本：

```python
self._parent_context = copy_context()
ctx = self._parent_context.copy()
future = self._thread_pool.submit(ctx.run, self._run_tool, tool)
callback_ctx = self._parent_context.copy()
future.add_done_callback(lambda _future: callback_ctx.run(self._on_tool_done, tool))
```

不能只在 `_process_queue()` 的 submit 点调用 `copy_context()`。并发工具完成后的 `Future.add_done_callback()` 可能在 worker thread 中、且在 `ctx.run()` 已退出后执行；此时 current span context 可能为空，后续被 callback 启动的 serial tool 会丢失 root parent。

**Subagent 关系**：同步 subagent 在 Agent tool span 内创建并运行，因此其 root span 会自然成为 Agent tool span 的子 span。后台 subagent 在线程池中运行，当前版本不保证挂到父 trace 下；父 trace 只记录启动后台 run 的 Agent tool span，后台 run 可作为独立 root trace。

---

## Span 属性（GenAI 语义约定）

遵循 [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)：

### 根 span：`invoke_agent bourbon`

| 属性 | 值 |
|---|---|
| `gen_ai.operation.name` | `"invoke_agent"`（agent orchestration，用 Bourbon 自定义操作名并在本 spec 中记录） |
| `gen_ai.provider.name` | `"bourbon"` |
| `gen_ai.agent.name` | `"bourbon"` |
| `bourbon.agent.workdir` | agent 工作目录绝对路径（Bourbon 自定义属性，不属于 OTel GenAI semconv） |
| `bourbon.agent.entrypoint` | `"step"` / `"step_stream"` / `"resume_permission"` |

### LLM span：`chat <model>`（每轮 LLM 调用一个）

| 属性 | 值 |
|---|---|
| `gen_ai.operation.name` | `"chat"` |
| `gen_ai.provider.name` | 实际 LLM provider（`"anthropic"` / `"openai"` / `"kimi"`） |
| `gen_ai.request.model` | 实际调用模型名 |
| `gen_ai.request.max_tokens` | `64000` |
| `gen_ai.usage.input_tokens` | 实际消耗 |
| `gen_ai.usage.output_tokens` | 实际消耗 |
| `gen_ai.response.finish_reasons` | `["tool_use"]` \| `["end_turn"]` |

### Tool span：`execute_tool <name>`（每次工具调用一个）

| 属性 | 值 |
|---|---|
| `gen_ai.operation.name` | `"execute_tool"` |
| `gen_ai.tool.name` | `"Bash"` / `"Read"` 等 |
| `gen_ai.tool.call.id` | `"toolu_01Abc..."` |
| `bourbon.tool.concurrent` | `true` \| `false`（Bourbon 自定义属性） |
| `bourbon.tool.is_error` | `true` \| `false` |
| `bourbon.tool.suspended` | 仅权限 ASK 暂停时为 `true` |
| `error.type` | 仅错误时设置，值为异常类名或 Bourbon 语义错误类型 |

**Error 标记**：Bourbon 有两类工具错误：

1. **异常错误**：registry/tool handler 抛出异常。调用 `span.record_exception(exc)`，设置 `StatusCode.ERROR` 和 `error.type = type(exc).__name__`。
2. **语义错误**：policy deny、subagent tool denial、unknown tool、用户拒绝权限、sandbox/handler 将错误吞掉并返回结构化错误。调用 `BourbonTracer.mark_error(span, error_type, message)`，设置 `StatusCode.ERROR` 和 `error.type`，不伪造 exception event。

不要靠 output string 前缀（如 `"Error"`）判断工具失败。Bourbon 现有代码明确允许合法工具输出以 `"Error"` 开头；失败状态必须来自结构化 outcome。

---

## 配置

### `~/.bourbon/config.toml`（新增 `[observability]` 节）

```toml
[observability]
enabled = true
service_name = "bourbon"

# OTLP HTTP exporter（Langfuse、Jaeger、任何 OTel 兼容后端）
otlp_endpoint = "https://cloud.langfuse.com/api/public/otel/v1/traces"

# Langfuse 用 HTTP header 传 API key（值为 Base64 编码的 "public_key:secret_key"）
otlp_headers = { Authorization = "Basic <base64(pk:sk)>" }
```

### 环境变量覆盖（标准 OTel，优先级高于 config.toml）

```bash
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1/traces
OTEL_EXPORTER_OTLP_TRACES_HEADERS=Authorization=Basic <base64(pk:sk)>
OTEL_SERVICE_NAME=bourbon
```

### 优先级

```
config.toml `enabled = false` > trace-specific 环境变量 > generic 环境变量 > config.toml 非开关字段 > 默认值（disabled）
```

`enabled` 默认 `false`，并作为当前 Agent 的 hard kill switch：即使环境变量配置了 endpoint，只要 `enabled = false`，该 Agent 的 `self._tracer` 仍是 no-op，业务插桩不会产生 span。启用后，优先读取 `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`，再读取 `OTEL_EXPORTER_OTLP_ENDPOINT` 并追加 `/v1/traces`，最后使用 config.toml 的 `otlp_endpoint`。

**Endpoint 规则**：`otlp_endpoint` 保存最终 traces endpoint（通常以 `/v1/traces` 结尾）。这是因为 OpenTelemetry Python 只有在使用 generic env var fallback 时才自动追加 traces path；代码显式传入 `OTLPSpanExporter(endpoint=...)` 时不会自动追加。

---

## 模块结构

### 新增文件

```
src/bourbon/observability/
├── __init__.py      # 导出 BourbonTracer / ObservabilityManager / no-op helpers
├── manager.py       # ObservabilityManager：初始化 OTel SDK，读取配置，flush/shutdown
└── tracer.py        # BourbonTracer：span context manager + error helpers
```

`ToolExecutionOutcome` 放在 `src/bourbon/tools/execution_queue.py`，因为它是 queue 和 Agent tool execution contract 的一部分。

### `BourbonTracer` 接口

```python
class BourbonTracer:
    def agent_step(self, workdir: str, entrypoint: str = "step") -> ContextManager[Span]:
        """根 span，包裹一个 Agent entrypoint。"""

    def llm_call(self, model: str, max_tokens: int, provider: str = "anthropic") -> ContextManager[Span]:
        """LLM span，包裹单次 llm.chat() / llm.chat_stream() 调用。"""

    def tool_call(self, name: str, call_id: str, concurrent: bool) -> ContextManager[Span]:
        """Tool span，包裹单次工具执行。"""

    def record_error(self, span: Any, exc: Exception) -> None:
        """记录异常型错误。"""

    def mark_error(self, span: Any, error_type: str = "tool_error", message: str = "") -> None:
        """记录语义型/已吞掉的错误，不伪造 exception event。"""
```

### 核心文件改动

```python
# agent.py — Agent.__init__
self._obs_manager = ObservabilityManager(config.observability)
self._tracer = self._obs_manager.get_tracer()

# agent.py — step()/step_stream()/resume_permission_request() 入口
with self._tracer.agent_step(workdir=str(self.workdir), entrypoint="step"):
    ...

with self._tracer.agent_step(workdir=str(self.workdir), entrypoint="resume_permission"):
    ...

# agent.py — _run_conversation_loop_stream() 和 _run_conversation_loop() 每轮 LLM 调用前
# streaming 路径和非 streaming 路径均需插桩
with self._tracer.llm_call(
    model=getattr(self.llm, "model", ""),
    max_tokens=64000,
    provider=self.config.llm.default_provider,
) as llm_span:
    event_stream = self.llm.chat_stream(...)
    # stream 结束后，用 OTel 原生 API 设置 token 属性：
    llm_span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    llm_span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    llm_span.set_attribute("gen_ai.response.finish_reasons", [stop_reason])

# agent.py — queue receives the per-Agent tracer and structured outcome callback
queue = ToolExecutionQueue(
    execute_fn=lambda block: self._execute_regular_tool_outcome(...),
    tracer=self._tracer,
)

# execution_queue.py — execute_all() 捕获 queue parent context，_run_tool() 工具执行前
with self._tracer.tool_call(name=name, call_id=tool.block.get("id",""), concurrent=tool.concurrent):
    raw_output = self._execute_fn(tool.block)
```

### 可选依赖

```toml
# pyproject.toml
[project.optional-dependencies]
observability = [
    "opentelemetry-sdk>=1.20",
    "opentelemetry-exporter-otlp-proto-http>=1.20",
]
```

安装：`uv pip install -e ".[observability]"`

OTel SDK 未安装时，`ObservabilityManager` 捕获 `ImportError`，降级为 no-op tracer，不影响正常运行。

**生命周期管理**：`ObservabilityManager` 可以复用进程级 OTel `TracerProvider`，但不能复用进程级 active `BourbonTracer`。每个 Agent 都持有自己的 `BourbonTracer` 实例。

Shutdown 规则：

- `Agent.shutdown_observability()` 调用 `self._obs_manager.shutdown()`，只做 `force_flush()`，安全可重复调用
- 进程退出时通过一个 idempotent `atexit` handler 调用 provider shutdown
- 不注册裸 `provider.shutdown` 多次，避免手动 flush 后 atexit double shutdown
- 不需要在 shutdown 时重置 module-level tracer，因为设计没有 module-level active tracer

---

## 测试策略

### 单元测试（`tests/test_observability.py`）

- `ObservabilityConfig` defaults/from_dict/to_dict
- `BourbonTracer` 在 no-op 模式无 OTel SDK 也不抛异常
- `BourbonTracer.mark_error()` 和 `record_error()` 设置 status/attributes 正确
- `ObservabilityManager(enabled=false)` 返回 no-op tracer，即使 endpoint env var 存在
- 两个 Agent 分别 enabled/disabled 时，disabled Agent 不复用 enabled Agent tracer
- `Agent.step()` root span 覆盖 prompt/context/session/compaction 和 conversation loop
- `Agent.step_stream()` root span 覆盖 streaming conversation
- `Agent.resume_permission_request()` root span 覆盖 reject/approve/remaining tools/continuation LLM
- `ToolExecutionQueue` 并发工具、并发后串行工具都保留 root parent
- `_execute_regular_tool_outcome()` 对 registry exception 返回结构化 error outcome，不靠字符串判断
- `_execute_tools()` direct paths 都创建 tool span：subagent denial、compress、policy DENY、permission ASK、unknown tool
- `resume_permission_request()` 的 approve/reject/subagent-denial 都创建 tool span

### 集成验证（手动步骤）

```bash
# 1. 配置 config.toml（使用 Langfuse cloud 或本地 docker）
# 2. 运行一个简单任务
python -m bourbon
> 帮我列出当前目录的文件

# 3. 在 Langfuse UI 里验证：
#    - 根 span "invoke_agent bourbon" 存在，duration 合理
#    - 根 span 有 bourbon.agent.entrypoint
#    - prompt/context/compaction 延迟包含在 root duration 内
#    - 子 span "chat <model>" 有 input_tokens / output_tokens 数据
#    - 子 span "execute_tool Bash" 有 tool_name、call_id、concurrent、is_error 属性
#    - tool deny/unknown/reject/handler exception 显示为 error span
```

不测试 Langfuse/外部平台的网络连通性（属于外部服务范围）。

---

## 审查修正记录

v2 修正以下 v1 设计问题：

- root span 从 conversation loop 上移到 Agent entrypoint，真正覆盖完整用户请求生命周期
- 增加 `resume_permission_request()` root/tool span 设计，避免审批恢复链路脱离 trace
- 移除 module-level mutable active tracer，改为 per-Agent tracer，保证 `enabled=false` hard kill switch 不被旧 tracer 污染
- queue context 捕获改为 `execute_all()` 级 parent context，并在 submit/callback 使用副本，修复并发后串行工具丢 parent 的问题
- 增加结构化 `ToolExecutionOutcome`，避免被 `_execute_regular_tool()` 吞掉的异常误报为成功
- direct tool paths 和 permission resume paths 都要求真实测试覆盖，不接受 source inspection 作为验收

---

## 社区背景参考

本设计参考以下社区实践和标准：

- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) — span attribute 命名规范
- [OWASP Agent Observability Standard (AOS)](https://aos.owasp.org/) — 安全视角的 agent 追踪规范，扩展了 OTel
- [Langfuse Agent Observability](https://langfuse.com/blog/2024-07-ai-agent-observability-with-langfuse) — OTel 接入参考实现
- [LangGraph Time Travel](https://blog.langchain.com/langgraph-studio-the-first-agent-ide/) — checkpoint 回放机制（未来可参考扩展）
- [Deterministic Replay for AI Agents](https://www.sakurasky.com/blog/missing-primitives-for-trustworthy-ai-part-8/) — record/replay 调试模式（未来方向）
