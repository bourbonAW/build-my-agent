# Flywheel Engine Design Spec
**Date**: 2026-06-22  
**Status**: Approved

---

## 1. 目标

构建一个属于自己的 LangSmith 等价系统，通过缝合开源组件而非全部自造轮子实现。核心产出是一个可跨 agent 项目复用的 **eval flywheel**——每转一圈，harness 更好、traces 更好、judges 更准。

---

## 2. 宏观架构（已锁定）

```
┌──────────────────────────────────────────────────────────────────┐
│  L0  Agent Runtime（per-project）                                │
│  bourbon: OTel spans (OTLP)                                      │
│  intelligent_customer: workflow_collector.py → Trace JSONL       │
└────────────┬──────────────────────────┬──────────────────────────┘
             │                           │ per-project adapter
┌────────────▼───────────────────────────▼──────────────────────────┐
│  L1  Eval Flywheel（per-project，使用 flywheel/sdk/ skeleton）     │
│  Question Set → Trace Collect → Human Annotate → LLM Judge        │
│  → F1 Validate → push OTel Log Records → L2                       │
└───────────────────────────────┬───────────────────────────────────┘
                                │ OTLP（traces + logs）
┌───────────────────────────────▼───────────────────────────────────┐
│  L2  Trace Platform（自托管 Langfuse + OTel Collector）            │
│  OTel Collector 路由：traces → Langfuse OTLP，logs → Score API     │
│  单一事实来源，跨项目共享                                           │
└───────────────────────────────┬───────────────────────────────────┘
                                │ Langfuse API
┌───────────────────────────────▼───────────────────────────────────┐
│  L3  Analysis Engine（flywheel/engine/）                          │
│  Orchestrator 驱动：读失败 → 聚类+归因 → 改进提案                  │
│  → ⚠️ GATE 1 → coding agent 执行 → ⚠️ GATE 2 → 回归验证 → 写回   │
└───────────────────────────────────────────────────────────────────┘
```

**Flywheel 转动路径**：L1 → L2 → L3 → L0 更新 → L1 重采集 → 循环

---

## 3. 仓库划分

| 仓库 | 类型 | 变化 |
|---|---|---|
| `bourbon` | 现有 | 加 flywheel adapter，emit OTel Log Records |
| `intelligent_customer` | 现有 | 将 `eval/schema.py` 对齐 flywheel 公共 schema |
| `flywheel` | **新建** | L1 skeleton + L3 engine + infra 配置 |

---

## 4. Common Data Contract

### OTel 三种信号分工

| 信号 | 来源 | 内容 |
|---|---|---|
| Traces（Spans） | L0 Agent Runtime | agent 执行轨迹 |
| Logs（Log Records） | L1 Flywheel | eval 标注结果 |
| Metrics（Gauge） | L1 Flywheel | F1、precision、recall |

三种信号共用同一个 OTLP endpoint（`http://otel-collector:4318`），换 backend 只改 Collector 配置。

### OTel Log Record 格式（eval 标注）

```
LogRecord {
    timestamp    : annotated_at（ISO 8601）
    severity     : INFO（pass）| WARN（fail）| DEBUG（skip）
    body         : critique（失败原因，人类可读）
    trace_id     : 关联原始 agent execution span

    attributes: {
        flywheel.project          : str
        flywheel.label            : "pass" | "fail" | "skip"
        flywheel.failure_category : FailureCategory
        flywheel.critique         : str
        flywheel.annotated_by     : str
        flywheel.harness_version  : str  # git commit sha
        flywheel.input            : str
        flywheel.output           : str
    }
}
```

`trace_id` 把标注数据和原始 agent span 串联，是 L3 根因分析的基础。

### FailureCategory 枚举

```python
FailureCategory = Literal[
    "hallucination",   # 输出内容不实
    "context_miss",    # 检索/记忆未命中
    "refusal_fail",    # 错误拒绝
    "tool_misuse",     # 工具调用错误（agent 特有）
    "incomplete",      # 输出不完整
    "off_topic",       # 偏离意图
    "regression",      # 改动后退化（L3 回归检测专用）
    "other",
]
```

---

## 5. L1 Flywheel Skeleton（`flywheel/sdk/`）

### 文件结构

```
flywheel/sdk/
├── schema.py    # FailureCategory + FlywheelAttr 常量（~30 行）
├── adapter.py   # FlywheelAdapter：OTel Log Records emitter
└── metrics.py   # compute_f1()：judge vs human label 对比
```

### `schema.py`（完整内容）

```python
from typing import Literal

FailureCategory = Literal[
    "hallucination", "context_miss", "refusal_fail",
    "tool_misuse", "incomplete", "off_topic", "regression", "other",
]

class FlywheelAttr:
    PROJECT          = "flywheel.project"
    LABEL            = "flywheel.label"
    FAILURE_CATEGORY = "flywheel.failure_category"
    CRITIQUE         = "flywheel.critique"
    ANNOTATED_BY     = "flywheel.annotated_by"
    HARNESS_VERSION  = "flywheel.harness_version"
    INPUT            = "flywheel.input"
    OUTPUT           = "flywheel.output"
```

数据模型由 Langfuse 管理，Python 类型由 Langfuse SDK 提供。`schema.py` 只定义跨项目共享的词汇表和 attribute key 合同。

### `adapter.py`（接口）

```python
class FlywheelAdapter:
    def __init__(self, otlp_endpoint: str, project: str): ...

    def push(self, sample: dict, origin_trace_id: str | None) -> None:
        """emit 一条 OTel Log Record。
        sample 必须包含 FlywheelAttr 中定义的所有 key。
        origin_trace_id 关联原始 agent execution span；
        非 OTel 项目（如 JSONL 采集）传 None，Collector 生成合成 id。
        """
```

### 各项目边界

| 由 sdk/ 提供 | 由各项目自己实现 |
|---|---|
| schema.py（共享枚举和 key 名） | Trace Collector |
| adapter.py（OTel Log emitter） | Human Annotation UI |
| metrics.py（F1 计算） | LLM Judge 维度定义 |

UI 和 judge 维度不可复用，不进 sdk。

---

## 6. L2 Trace Platform（`flywheel/infra/`）

### 组件

- **Langfuse**：自托管，trace 存储 + Score API + Dataset API + UI
- **OTel Collector**：路由层，唯一知道 Langfuse 私有 API 的地方

### OTel Collector 路由规则

```
OTLP traces → passthrough → Langfuse OTLP endpoint
OTLP logs   → filter(flywheel.* attributes) → Langfuse Score API
```

应用层（L0/L1）只打 OTLP，不感知 Langfuse。换 backend 只改 Collector 配置。

---

## 7. L3 Analysis Engine（`flywheel/engine/`）

### 模块结构

```
flywheel/engine/
├── orchestrator.py   # 主循环驱动，触发管理
├── reader.py         # 从 Langfuse API 读 annotated failures
├── analyzer.py       # 失败聚类 + 根因归因（LLM 驱动）
├── proposer.py       # 生成结构化 ImprovementProposal
├── executor.py       # 驱动 coding agent，handoff 文档生成
├── validator.py      # 触发 L1 重采集，回归对比
└── writer.py         # 将结果写回 L2（Langfuse scores/dataset）
```

### Orchestrator 执行流（一圈 flywheel）

```
trigger_fired(project, since_version)
    │
    ├─ reader.fetch_failures()           # 从 L2 拉 annotated failures
    ├─ analyzer.cluster()                # 按 failure_category 聚类
    ├─ analyzer.attribute_root_causes()  # LLM 分析 → 根因报告
    ├─ proposer.generate()               # 生成 ImprovementProposal
    │
    ├─ ⚠️ GATE 1：人工审核提案
    │   $ flywheel proposals list --project <name>
    │   $ flywheel proposals approve --id <prop-id>
    │
    ├─ executor.apply(approved)          # 生成 handoff 文档 → 调 coding agent
    │
    ├─ ⚠️ GATE 2：人工 diff review → merge（GitHub PR 流程）
    │
    ├─ validator.trigger_recollection()  # 通知 L1 重跑 eval suite
    ├─ validator.compare_regression()    # 新旧 harness_version 对比
    └─ writer.publish_results()          # 写回 L2
```

### ImprovementProposal 结构

```python
@dataclass
class ProposedChange:
    change_type: Literal["prompt", "tool_definition", "workflow", "config"]
    target_file: str       # 具体到文件路径
    description: str
    rationale: str         # 为什么改这里（关联 failure cluster）
    suggested_diff: str    # 供 coding agent 参考，可为空

@dataclass
class ImprovementProposal:
    proposal_id: str
    project: str
    baseline_version: str  # git sha，回归对比基准
    failure_clusters: list[dict]
    proposed_changes: list[ProposedChange]
    created_at: str
```

### Executor：Coding Agent 接入

Executor 生成 **handoff 文档**交给 coding agent（MVP 使用 Claude Code CLI）：

```markdown
# Flywheel Improvement Handoff

## Baseline: bourbon@abc1234
## Failure Summary
- 12/50 traces failed (24%)
- Top cluster: tool_misuse (8/12)
- Root cause: system prompt missing offset param description

## Proposed Changes
1. FILE: src/bourbon/prompt/sections.py
   CHANGE: Add offset param docs to Read tool description
   RATIONALE: 8 failures traced to missing parameter guidance
```

### 触发策略

| 模式 | 阶段 |
|---|---|
| 手动 `$ flywheel run --project <name>` | MVP |
| 定时（cron） | Phase 2 |
| 失败率阈值（fail_rate > 0.30） | Phase 2 |

### 分阶段实现

| 阶段 | 包含 | 排除 |
|---|---|---|
| **MVP** | 手动触发、reader、analyzer、proposer、生成 Markdown 报告 | executor 自动执行、validator 自动重采集 |
| **Phase 2** | executor + coding agent、validator 自动触发 | 阈值触发 |
| **Phase 3** | 定时触发、阈值触发、Web UI | — |

MVP 的核心价值：**分析报告本身就值得构建**，人工读报告再手动改，flywheel 第一圈就能转。

---

## 8. 设计决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| eval 数据无 OTel 标准 | 用 OTel Log Records + 自定义 flywheel.* attributes | transport 层标准，只有 Collector 知道 Langfuse |
| eval 独立层 vs 消融进 trace | 消融：eval = trace + OTel Log annotation | GEPA/HALO/RHO 最新思路，trace 已含全部信息 |
| schema 设计 | 只定义 FailureCategory 枚举 + FlywheelAttr key 常量 | 数据模型由 Langfuse 管，无需自建 TypedDict |
| 仓库数量 | 1 new repo（flywheel） | sdk/ + engine/ schema 共享，MVP 阶段不需要跨 repo 版本管理 |
| L1 skeleton 复用边界 | schema + adapter + F1，UI 和 judge 不复用 | intelligent_customer 和 bourbon trace 结构差异太大 |
| L3 自动化程度 | MVP 只出报告，人工执行改动 | 防 agent slop，人工 gate 是护城河 |
