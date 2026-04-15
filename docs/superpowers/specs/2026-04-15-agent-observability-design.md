# Bourbon Agent Observability 设计

**日期**：2026-04-15  
**范围**：为 bourbon 接入 OpenTelemetry 标准追踪，对接 Langfuse 等外部平台，实现完整 agent run 可视化 debug

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
2. 覆盖**完整 agent run**：根 span → LLM span → Tool span，形成完整树
3. **核心文件改动最小**（仅 3 处插桩点），observability 代码与业务逻辑分离
4. **不启用零开销**：未配置时所有调用都是 no-op
5. **可选依赖**：OTel SDK 不强制安装，只在 `[observability]` extra 里

---

## 架构总览

```
用户请求
  │
  ▼
agent.step()  ──────────────────────────────── [根 span: gen_ai.agent.step]
  │
  ├─ llm.chat_stream()  ──────────────────── [LLM span: gen_ai.chat]
  │      attrs: model, input_tokens, output_tokens, stop_reason
  │
  ├─ _execute_tools()
  │      ├─ _run_tool(Read)  ────────────── [Tool span: gen_ai.tool.Read]
  │      ├─ _run_tool(Bash)  ────────────── [Tool span: gen_ai.tool.Bash]
  │      └─ ...（并发工具各自一个 span）
  │
  └─ llm.chat_stream()  ──────────────────── [LLM span: gen_ai.chat]（下一轮）
```

**OTel Context 传播**：使用 Python `contextvars`（OTel SDK 默认机制）。span 父子关系自动跨线程传递，`ThreadPoolExecutor` 里并发执行的工具 span 会自动挂在正确的 tool round 下，无需手动传递 context。

---

## Span 属性（GenAI 语义约定）

遵循 [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)：

### 根 span：`gen_ai.agent.step`

| 属性 | 值 |
|---|---|
| `gen_ai.system` | `"bourbon"` |
| `gen_ai.agent.workdir` | agent 工作目录绝对路径 |
| `gen_ai.agent.tool_rounds` | 本次 step 完成的工具轮次数 |

### LLM span：`gen_ai.chat`（每轮 LLM 调用一个）

| 属性 | 值 |
|---|---|
| `gen_ai.system` | `"anthropic"` |
| `gen_ai.request.model` | `"claude-sonnet-4-6"` |
| `gen_ai.request.max_tokens` | `64000` |
| `gen_ai.usage.input_tokens` | 实际消耗 |
| `gen_ai.usage.output_tokens` | 实际消耗 |
| `gen_ai.response.stop_reason` | `"tool_use"` \| `"end_turn"` |

### Tool span：`gen_ai.tool.<name>`（每次工具调用一个）

| 属性 | 值 |
|---|---|
| `gen_ai.tool.name` | `"Bash"` / `"Read"` 等 |
| `gen_ai.tool.call.id` | `"toolu_01Abc..."` |
| `gen_ai.tool.concurrent` | `true` \| `false` |
| `gen_ai.tool.is_error` | `true` \| `false` |

**Error 标记**：工具或 LLM 调用出错时，使用标准 OTel `span.set_status(StatusCode.ERROR, description)` + `span.record_exception(exc)`，Langfuse 会自动将其高亮为红色 span。

---

## 配置

### `~/.bourbon/config.toml`（新增 `[observability]` 节）

```toml
[observability]
enabled = true
service_name = "bourbon"

# OTLP HTTP exporter（Langfuse、Jaeger、任何 OTel 兼容后端）
otlp_endpoint = "https://cloud.langfuse.com/api/public/otel"

# Langfuse 用 HTTP header 传 API key（值为 Base64 编码的 "public_key:secret_key"）
otlp_headers = { Authorization = "Basic <base64(pk:sk)>" }
```

### 环境变量覆盖（标准 OTel，优先级高于 config.toml）

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64(pk:sk)>
OTEL_SERVICE_NAME=bourbon
```

### 优先级

```
环境变量 > config.toml [observability] > 默认值（disabled）
```

`enabled` 默认 `false`。未设置 endpoint 或 `enabled = false` 时，`ObservabilityManager` 初始化为 no-op 模式，不加载 OTel SDK。

---

## 模块结构

### 新增文件

```
src/bourbon/observability/
├── __init__.py      # 导出 get_tracer()
├── manager.py       # ObservabilityManager：初始化 OTel SDK，读取配置
└── tracer.py        # BourbonTracer：封装 span 创建，提供语义化 API
```

### `BourbonTracer` 接口

```python
class BourbonTracer:
    def agent_step(self, workdir: str) -> ContextManager[Span]:
        """根 span，包裹整个 agent.step() 调用。"""

    def llm_call(self, model: str, max_tokens: int) -> ContextManager[Span]:
        """LLM span，包裹单次 llm.chat() / llm.chat_stream() 调用。"""

    def tool_call(self, name: str, call_id: str, concurrent: bool) -> ContextManager[Span]:
        """Tool span，包裹单次工具执行。"""
```

### 核心文件改动（仅 3 处）

```python
# agent.py — step() 入口
with get_tracer().agent_step(workdir=str(self.workdir)):
    ...

# agent.py — _run_conversation_loop_stream() 和 _run_conversation_loop() 每轮 LLM 调用前
# streaming 路径和非 streaming 路径均需插桩
with get_tracer().llm_call(model=config.model, max_tokens=64000) as llm_span:
    event_stream = self.llm.chat_stream(...)
    # stream 结束后，用 OTel 原生 API 设置 token 属性：
    llm_span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    llm_span.set_attribute("gen_ai.usage.output_tokens", output_tokens)

# execution_queue.py — _run_tool() 工具执行前
with get_tracer().tool_call(name=name, call_id=tool.block.get("id",""), concurrent=tool.concurrent):
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

---

## 测试策略

### 单元测试（`tests/test_observability.py`）

- `ObservabilityManager` 在 `enabled=false` 时返回 no-op tracer，不抛异常
- `BourbonTracer` 在 OTel SDK 未安装时优雅降级（`ImportError` 捕获，返回 no-op）
- span attribute 映射正确（用 OTel `InMemorySpanExporter` 捕获 span 断言属性值）
- 并发工具执行时各 span 的父子关系正确（tool span 挂在对应 LLM span 下）

### 集成验证（手动步骤）

```bash
# 1. 配置 config.toml（使用 Langfuse cloud 或本地 docker）
# 2. 运行一个简单任务
python -m bourbon
> 帮我列出当前目录的文件

# 3. 在 Langfuse UI 里验证：
#    - 根 span "gen_ai.agent.step" 存在，duration 合理
#    - 子 span "gen_ai.chat" 有 input_tokens / output_tokens 数据
#    - 子 span "gen_ai.tool.Bash" 有 tool_name、call_id、concurrent 属性
#    - 出错的工具 span 显示为红色
```

不测试 Langfuse/外部平台的网络连通性（属于外部服务范围）。

---

## 社区背景参考

本设计参考以下社区实践和标准：

- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) — span attribute 命名规范
- [OWASP Agent Observability Standard (AOS)](https://aos.owasp.org/) — 安全视角的 agent 追踪规范，扩展了 OTel
- [Langfuse Agent Observability](https://langfuse.com/blog/2024-07-ai-agent-observability-with-langfuse) — OTel 接入参考实现
- [LangGraph Time Travel](https://blog.langchain.com/langgraph-studio-the-first-agent-ide/) — checkpoint 回放机制（未来可参考扩展）
- [Deterministic Replay for AI Agents](https://www.sakurasky.com/blog/missing-primitives-for-trustworthy-ai-part-8/) — record/replay 调试模式（未来方向）
