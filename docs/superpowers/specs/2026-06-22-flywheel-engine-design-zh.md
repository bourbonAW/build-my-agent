# Flywheel 引擎设计规格

**日期**: 2026-06-22  
**状态**: 修订草案  
**相关文档**: `docs/superpowers/specs/2026-06-22-flywheel-ui-ux-design.md`

---

## 1. 目标

为 Bourbon 构建一个自托管的 LangSmith Engine 等价物：一个可复用的**评估飞轮**，将真实运行轨迹转化为数据集、校准后的评判器、失败问题、人工评审的改进提案、回归决策，以及更好的测试框架。

飞轮不是一个通用仪表盘。它是一个闭环改进系统：

```
轨迹池
  -> 采样
  -> 错误分析
  -> 数据集构建
  -> 评判器校准
  -> 运行评分
  -> 失败分析
  -> 提案评审
  -> 实现移交
  -> 带有人工/统计门控的回归测试
  -> 新的测试框架基线
```

修订后的设计将数据集构建、评判器校准、脱敏和回归有效性作为核心引擎机制。Langfuse 保留为轨迹和评分的证据存储；Flywheel 拥有工作流状态、数据策划流程、改进提案和发布/回滚决策。

---

## 2. 评审驱动的变更

本修订版整合了对抗性评审的反馈。

| 发现 | 设计变更 |
|---|---|
| 数据集/错误分析缺失 | 在评分和提案生成之前增加了专门的数据与错误分析流水线。 |
| 失败分类是封闭且推测性的 | 用开放编码和轴向聚类驱动的开放分类注册表替换封闭的 `FailureCategory` 枚举。 |
| 评判器校准是运行级别的 | 将校准提升为版本化的 `JudgeVersion` 资产，包含 train/dev/locked-test 分割和明确的阈值。 |
| 回归测试在候选版本漂移后仍信任同一个评判器 | 在发布前增加了通过人工审计样本进行的候选分布复检。 |
| 回归测试缺乏统计严谨性 | 增加了重复采样、置信区间、无显著变化状态和可配置的最小效应门控。 |
| 轨迹属性混用了执行时和事后标注 | 将执行时的 OTel 属性与评分/标注/提案元数据分离。 |
| 脱敏只是一个标志 | 在 UI 显示或 LLM 分析前增加了强制脱敏流水线。 |
| 留出集完整性没有机制保障 | 提案记录 `consumed_case_ids`；回归测试排除这些用例并报告交集检查。 |
| `harness_version = git SHA` 过于狭窄 | 增加了 `harness_fingerprint` 作为复合行为标识。 |
| UI MVP 克隆了标注功能 | MVP 在可能的情况下使用 Langfuse 标注；Flywheel UI 专注于 Langfuse 不拥有的工作流决策和资产。 |

---

## 3. 架构

```
L0 智能体运行时 (需要 OTel)
  发出带有执行时 flywheel.* 身份属性的轨迹
        |
        | OTLP 轨迹和指标，评估轨迹不做头部采样
        v
L2 证据平台
  OTel Collector + Langfuse
  存储轨迹、观测和评分

L1 评估/数据流水线
  采样轨迹 -> 运行开放编码 -> 策划数据集
  运行评判器并通过 Flywheel API 提交评分

L2.5 Flywheel 控制平面
  API + 状态存储 + 轻量 Web UI
  拥有数据集、分类体系、评判器版本、问题、提案、门控、审计

L3 分析引擎
  读取脱敏证据 -> 聚类失败 -> 提出变更
  记录已消费证据 -> 触发回归和发布/回滚门控
```

**证据 vs 控制**:

| 层级 | 拥有 | 不拥有 |
|---|---|---|
| OTel Collector | OTLP 摄取、批处理、路由、完整评估轨迹导出 | Flywheel 工作流逻辑 |
| Langfuse | 原始轨迹、观测、评分、深度轨迹 UI、原生标注 | 提案生命周期、留出策略、发布决策 |
| Flywheel API | 评分桥接、状态转换、授权、幂等性、脱敏强制执行 | 原始轨迹存储 |
| Flywheel 状态存储 | 数据集、分类体系、评判器版本、问题、提案、移交、回归结果 | 长期原始 span 载荷 |
| Flywheel UI | Langfuse 未覆盖的人工工作流和决策 | 轨迹浏览器克隆 |
| Flywheel 引擎 | 错误分析、聚类、提案、回归比较 | 人工审批 |

---

## 4. 仓库范围

| 仓库 | 类型 | 变更 |
|---|---|---|
| `bourbon` | 现有 | 发出 Flywheel OTel 执行属性；暴露测试框架指纹输入。 |
| `intelligent_customer` | 现有 | 仅在存在等价的 OTel 轨迹后才纳入范围。本设计不支持 JSONL 回退。 |
| `flywheel` | 新建 | `sdk/`, `api/`, `engine/`, `ui/`, `infra/`, `datasets/`, `taxonomy/`。 |

所有项目必须具备 OTel 能力。`trace_id` 对评估运行绝非可选。

---

## 5. 数据与错误分析流水线

飞轮从数据开始，而非分类。失败标签和数据集必须从真实轨迹中推导出来，才能作为稳定的评估标准。

### 流水线

```
轨迹池
  -> 代表性采样
  -> 开放编码
  -> 轴向聚类
  -> 分类注册表更新
  -> 数据集候选构建
  -> train/dev/locked-test 分割
  -> 评判器校准
  -> 评估运行
```

### 采样

采样必须同时捕获数量和风险：

- 最近的生 产轨迹
- 失败或低置信度轨迹
- 高风险工具/沙箱/凭证路径
- 长对话多轮会话
- 重复用户意图
- 来自先前回归的边缘案例

评估轨迹必须完整导出到 Langfuse。OTel 头部采样不得丢弃带有 `flywheel.eval_run_id` 或 `flywheel.trace_pool_id` 的记录。

轨迹池引用存储在 Langfuse 中的原始轨迹。每个轨迹池必须声明原始证据和脱敏证据视图的保留策略。Flywheel 不应延长原始 PII/秘密的保留期限超过证据平台配置的 TTL。

### 开放编码

评审者检查采样的轨迹批次并附加自由形式的代码，例如：

```text
missing offset explanation
wrong tool arg shape
forgot prior user constraint
unsafe file access not escalated
answer omitted generated artifact
```

开放代码不是稳定的产品标签。它们是原始观察。

### 轴向聚类

引擎将开放代码分组为候选失败标签。评审者可以合并、重命名、拆分或退役标签。一个标签仅在以下条件满足后才成为稳定标签：

- 短 slug
- 人类可读的定义
- 正面和反面示例
- 已知的反例
- 负责人审批
- 版本化包含在分类注册表中

### 开放分类注册表

失败分类是开放且版本化的。SDK 不得硬编码封闭的 `FailureCategory` 枚举。

```yaml
taxonomy_version: 2026-06-22.1
labels:
  - slug: tool_argument_error
    parent: tool_misuse
    definition: "智能体选择了一个合理的工具，但提供了无效、不完整或误导性的参数。"
    examples:
      - case_id: bourbon-read-offset-001
    counterexamples:
      - case_id: bourbon-tool-not-needed-002
    status: active
```

`other` 仅作为临时代码。重复出现的 `other` 聚类必须进行提升、拆分或明确拒绝的评审。

### 分类迁移

分类版本发布后不可变。变更创建新版本加显式迁移映射：

```yaml
from_version: 2026-06-22.1
to_version: 2026-07-01.1
migrations:
  - from: tool_argument_error
    to: invalid_tool_arguments
    kind: rename
  - from: context_miss
    to: [retrieval_miss, memory_miss]
    kind: split
  - from: obsolete_label
    to: null
    kind: retire
```

规则：

- 历史标注保留创建时使用的分类版本。
- UI 通过别名解析旧 slug，显示原始标签和当前映射。
- 数据集用例只能通过创建新数据集版本进行迁移。
- 评判器版本保持与其验证的分类版本绑定。
- 触及已验证评判器所用标签的分类迁移将该评判器标记为 `recheck_required`。

### 数据集构建

每个数据集用例必须携带足够的信息用于重放、评分和回归完整性。

```python
@dataclass
class DatasetCase:
    dataset_id: str
    dataset_version: str
    case_id: str
    task_family: str
    source_trace_ids: list[str]
    intent_summary: str
    input_messages_ref: str
    expected_outcome: str
    acceptance_criteria: list[str]
    risk_tags: list[str]
    failure_labels: list[str]
    split: Literal["train", "dev", "locked_test", "regression_holdout"]
    created_from: Literal["production_trace", "synthetic", "manual"]
```

分割必须不相交：

```
train ∩ dev ∩ locked_test ∩ regression_holdout = ∅
```

`locked_test` 验证评判器版本。`regression_holdout` 验证候选测试框架。它们绝不能共享用例。混合任务数据集仅在每个用例声明 `task_family` 且运行选择单个任务家族或使用为每个包含的家族验证的评判器版本时才允许。

数据集应通过策划批次增长，而非盲目评分所有流量。早期目标规模：

| 数据集阶段 | 目标 |
|---|---|
| 种子集 | 20-50 个代表性用例 |
| 首个稳定评判器 | 100+ 用例，包含少数失败标签 |
| 回归留出集 | 30+ 用例或按风险层级的配置最小值 |

### 采样与成本预算

每次运行必须在开始前有明确的预算：

```python
@dataclass
class EvalBudget:
    max_cases: int
    max_repeats_per_case: int
    max_judge_calls: int
    max_curation_llm_calls: int
    max_drift_sentinel_cases: int
    max_analysis_traces: int
    max_total_cost_usd: float
    max_wall_clock_minutes: int
```

预算策略应优先选择代表性样本而非全量流量。引擎应报告：

- 运行开始前的预期评判器调用次数
- 运行后的实际模型调用和成本
- 因预算跳过的用例
- 采样的分析轨迹 vs 可用量
- 策划、聚类、脱敏和漂移哨兵调用计入同一预算族
- 统计置信度是否受预算限制

如果预算阻碍有效的回归决策，结果是 `needs_more_data` 或 `no_significant_change`，而非发布。

---

## 6. 身份与语义契约

OTel 是传输和关联基础。Flywheel 在 `flywheel.*` 下定义小型语义约定。

### 执行时 OTel 属性

这些属性在智能体执行期间设置。它们必须在根 span 上可用，并在需要查询能力的地方传播。

| 属性 | 类型 | 用途 |
|---|---|---|
| `flywheel.project` | string | 项目命名空间，例如 `bourbon`。 |
| `flywheel.environment` | string | `dev`、`ci`、`staging` 或 `prod`。 |
| `flywheel.trace_pool_id` | string | 用于采样和开放编码的轨迹池，非评估运行时。 |
| `flywheel.eval_run_id` | string | 一次评估运行的稳定 ID。 |
| `flywheel.dataset_id` | string | 版本化数据集 ID。 |
| `flywheel.dataset_version` | string | 本次运行使用的数据集版本。 |
| `flywheel.case_id` | string | 数据集内的稳定用例 ID。 |
| `flywheel.sample_id` | string | 重复运行的尝试/样本 ID。 |
| `flywheel.harness_fingerprint` | string | 复合行为指纹。 |
| `flywheel.session_id` | string | 对话/会话 ID（适用时）。 |
| `flywheel.turn_index` | int | 多轮任务的轮次索引，单轮为 `0`。 |

`trace_id` 和 `span_id` 是证据指针，非评估身份。同一个 `case_id` 可以在基线、候选和重复样本中产生不同的轨迹。

### 测试框架指纹

`harness_fingerprint` 必须包含影响行为的输入，不仅是 git SHA：

- 测试框架 git SHA
- 提示词和技能版本
- 工具模式版本
- 与运行相关的内存/索引配置
- 模型提供商和模型快照（可用时）
- 解码参数
- 依赖锁定哈希
- 环境/运行时配置哈希

原始组件应存储在状态存储中。指纹是紧凑的可比较 ID。

### 事后评分和标注元数据

这些字段不是执行时轨迹属性。它们存储在 Langfuse 评分中并镜像到 Flywheel 状态存储。

| 字段 | 类型 | 用途 |
|---|---|---|
| `flywheel.label` | `pass | fail | skip | uncertain` | 人工、评判器、规则或系统标签。 |
| `flywheel.failure_labels` | list[string] | 开放分类标签。 |
| `flywheel.critique` | string | 人类可读的原因。 |
| `flywheel.confidence` | float | 评审者或评判器置信度，0 到 1。 |
| `flywheel.annotation_source` | `human | judge | rule | system` | 标签来源。 |
| `flywheel.annotated_by` | string | 评审者 ID、评判器 ID 或系统 ID。 |
| `flywheel.annotation_rubric_version` | string | 标注准则版本。 |
| `flywheel.judge_version` | string | 评判器输出的提示词/模型/配置版本。 |
| `flywheel.redaction_state` | `raw | redacted | blocked` | 强制脱敏流水线的结果。 |

### 分析和提案元数据

| 字段 | 类型 | 用途 |
|---|---|---|
| `flywheel.issue_id` | string | L3 生成的稳定失败问题 ID。 |
| `flywheel.cluster_id` | string | 分析运行内的失败聚类 ID。 |
| `flywheel.proposal_id` | string | 改进提案 ID。 |
| `flywheel.proposal_state` | `ProposalState` | 第 12 节中的权威提案生命周期状态之一。 |
| `flywheel.regression_status` | `RegressionStatus` | 回归运行的执行状态。 |
| `flywheel.regression_outcome` | `RegressionOutcome` | 最终回归决策（可用时）。 |
| `flywheel.baseline_fingerprint` | string | 基线测试框架指纹。 |
| `flywheel.candidate_fingerprint` | string | 候选测试框架指纹。 |

---

## 7. L1 Flywheel SDK (`flywheel/sdk/`)

SDK 是一个轻量集成层。它验证身份上下文、构建 OTel 属性、通过 Flywheel API 提交评分，并计算本地指标。它不拥有 UI、分类治理、评判器准则或轨迹存储。

```
flywheel/sdk/
├── schema.py       # Label, AnnotationSource, FlywheelAttr, 类型别名
├── context.py      # FlywheelContext 验证和 OTel 属性构建器
├── fingerprint.py  # 测试框架指纹助手
├── score_client.py # 通过 Flywheel API 提交评判器/规则评分
└── metrics.py      # F1、精确率、召回率、置信区间
```

`failure_labels` 是针对当前分类注册表验证的字符串。未知标签只能在数据/错误分析期间作为开放代码提交，不能作为稳定的回归类别。

---

## 8. L2 证据平台 (`flywheel/infra/`)

### 组件

- **Langfuse**: 自托管轨迹存储、评分存储、原生轨迹 UI、原生标注（有用时）。
- **OTel Collector**: 接收 OTLP 轨迹/指标并导出到 Langfuse 或其他配置的后端。
- **指标后端**: 可选的长期成本、延迟和运行指标接收器。

### 路由规则

```
OTLP 轨迹  -> OTel Collector -> Langfuse OTLP 端点
OTLP 指标 -> OTel Collector -> 指标后端
评分       -> Flywheel API Score Bridge -> Langfuse Score API
```

Collector 路由不得包含 Flywheel 工作流逻辑。评分写入通过 Flywheel API 以便验证、去重、重试、审计和授权。

---

## 9. Flywheel 控制平面 (`flywheel/api/` + 状态存储)

```
flywheel/api/
├── server.py          # HTTP API（面向 UI、L1 和引擎作业）
├── schemas.py         # API 请求/响应模型
├── state_store.py     # 数据集、分类、评判器、运行、问题、提案
├── score_bridge.py    # 幂等 Langfuse Score API 写入
├── redaction.py       # 脱敏转换和强制执行
├── auth.py            # 本地认证/会话边界和角色检查
└── audit.py           # 仅追加的决策和变更日志
```

### 状态存储对象

| 对象 | 用途 |
|---|---|
| `TracePool` | 可用于采样和开放编码的源轨迹。 |
| `TracePoolRetentionPolicy` | 原始轨迹 TTL、脱敏视图 TTL 和删除/审计策略。 |
| `OpenCodeBatch` | 错误分析期间应用的人工/原始代码。 |
| `TaxonomyLabel` | 版本化的开放失败标签，含示例和状态。 |
| `TaxonomyMigration` | 分类版本间的别名、重命名、拆分、合并和退役映射。 |
| `Dataset` / `DatasetCase` | 策划的用例和分割元数据。 |
| `JudgeVersion` | 评判器提示词/模型/配置加验证指标。 |
| `JudgeDriftCheck` | 评判器/任务家族的周期性生产漂移哨兵结果。 |
| `Baseline` | 项目测试框架基线生成、指纹、血缘和当前指针状态。 |
| `EvalRun` | 运行状态、数据集、测试框架指纹、进度、聚合指标。 |
| `Annotation` | 人工、评判器、规则或系统标签加元数据。 |
| `FailureIssue` | 聚类的、命名的失败模式，含证据链接。 |
| `ImprovementProposal` | 提议的变更、已消费证据和评审状态。 |
| `Handoff` | Markdown 移交、编码智能体运行、PR/diff 链接。 |
| `RegressionResult` | 基线 vs 候选比较和决策。 |
| `RegressionHoldoutLedger` | 独立留出假设暴露、原始运行计数、冷用例刷新元数据、多重比较策略。 |
| `BaselineRevertDecision` | 人工审批的发布后回滚决策和证据。 |
| `AuditEvent` | 仅追加的变更和审批历史。 |

### 幂等性

所有变更端点必须支持幂等性：

- `POST /api/runs`: 服务器可生成 `eval_run_id`；客户端提供的 ID 必须每个项目唯一。
- `POST /api/scores`: 幂等键为 `eval_run_id + case_id + sample_id + source + judge_version`。
- `POST /api/annotations`（启用自定义标注时）: 幂等键为 `annotation_item_id + annotator_id + rubric_version`。
- 提案审批、拒绝、发布和回滚是比较并设置的状态转换。

---

## 10. 脱敏与证据访问

脱敏是强制的流水线步骤，不是显示标志。

```
Langfuse 原始轨迹
  -> EvidenceReader
  -> RedactionService
  -> 策略决策: 脱敏证据 | 阻止证据
  -> UI 和/或 LLM 分析
```

规则：

- L3 分析器和提案生成器绝不能直接接收原始轨迹载荷。
- `blocked` 证据对 UI 隐藏并排除在 LLM 分析之外。
- `redacted` 证据可用于 UI 和 LLM 分析，附带脱敏元数据。
- 脱敏失败时采用安全失败（fail closed）。
- 状态存储记录哪个脱敏策略和版本生成了证据视图。

这是必需的，因为 Bourbon 轨迹可能包含凭证、文件系统路径、用户数据或沙箱策略详情。

脱敏也可能移除根本原因分析所需的证据。每个分析报告必须包含：

- 脱敏的 token/字段数
- 阻止的证据数
- 脱敏后的证据覆盖率
- 人工标记为过度脱敏无法诊断的过屏蔽评审数
- 脱敏策略版本

如果脱敏覆盖率过低，分析可产生 `needs_more_data` 但绝不能绕过脱敏。

---

## 11. 评判器版本生命周期

评判器校准是版本化资产，不是每次运行的强制循环。

### JudgeVersion

```python
@dataclass
class JudgeVersion:
    judge_version: str
    project: str
    task_family: str
    model: str
    prompt_version: str
    taxonomy_version: str
    train_dataset_id: str
    dev_dataset_id: str
    locked_test_dataset_id: str
    status: Literal[
        "draft",
        "calibrating",
        "validated",
        "validated_limited",
        "rejected",
        "recheck_required",
    ]
    metrics: dict[str, float]
```

### 校准协议

默认门控：

- 存在 train/dev/locked-test 分割。
- 锁定测试未用于评判器提示词调优。
- 锁定测试用例与回归留出用例不相交。
- 整体 F1 至少 `0.70`，除非项目策略定义了不同阈值。
- 少数失败标签有明确的精确率/召回率报告。
- 多评审者标注同一集合时测量评审者间一致性。
- 单一领域负责人解决最终准则争议以保证一致性。

评审者间一致性的重叠策略：

- 至少 10% 的校准用例或每个任务家族 20 个用例进行双标签（取较小但非零）
- 每次重大准则、分类或评判器变更时重复重叠采样
- 与人工-评判器一致性分开跟踪一致性

评估运行引用已验证的 `judge_version`。如果评判器未针对数据集的任务家族验证，运行可收集评分但不能触发自动提案生成。

### 锁定测试轮换

同一锁定测试集不得在重大评判器迭代中无限期复用。每个任务家族需要未曾用于选择先前评判器版本的冷用例储备。

规则：

- 小的评判器提示词编辑可在有限次数尝试中复用同一锁定测试集。
- 重大的提示词/模型/分类变更需要刷新的锁定测试集或冷用例补充。
- 验证报告必须显示多少先前评判器版本使用了相同的锁定用例。
- 如果复用超过项目策略，评判器可标记为 `validated_limited` 用于人工分析，但不能用于自动提案生成。

### 候选漂移复检

测试框架变更后，回归必须包含候选输出的小规模人工审计：

- 至少 10 个候选用例或 10% 的候选失败（取较大且可行者）
- 包含新的失败模式和变更输出用例
- 计算候选人工-评判器一致性

如果候选一致性低于评判器门控，发布被阻止，评判器对该任务家族进入 `recheck_required`。

### 生产漂移哨兵

已验证的评判器发布后必须监控：

- 按固定周期采样小批量生产或评估批次
- 收集新鲜的人工标签或专家评审
- 计算人工-评判器一致性和少数标签精确率/召回率
- 比较当前输入/输出分布与评判器验证集
- 当一致性或分布漂移超过策略阈值时标记评判器 `recheck_required`

此哨兵与候选回归分离。它在未来提案依赖过时评判器评分之前，检测来自流量变化、提供商/模型变化和分类漂移的基线漂移。

当哨兵将评判器标记为 `recheck_required` 时，每个依赖该评判器版本的进行中回归如果当前处于 `regression_running` 或 `regression_review` 状态，必须进入 `blocked_on_judge_recheck`。依赖该评判器的自动提案生成和发布动作暂停，直到评判器再次验证或被迁移的评判器版本替换。

---

## 12. 权威提案和回归生命周期

这些枚举是数据库行、API 载荷、引擎作业和前端类型的单一事实来源。UI 图表可呈现更友好的标签，但不得引入额外的生命周期状态。

### 基线

基线是一等对象，因为它是飞轮的持久输出。

```python
@dataclass
class Baseline:
    project: str
    generation: int
    fingerprint: str
    produced_by_proposal_id: str | None
    previous_generation: int | None
    published_at: str
    status: Literal["current", "superseded", "reverted"]
    revert_reason: str | None = None
    reverted_at: str | None = None
```

规则：

- 每个项目恰好有一个 `current` 基线。
- 发布提案创建新的基线生成并将先前的当前生成标记为 `superseded`。
- 提案和回归上的 `baseline_generation` 引用此对象，非隐式计数器。
- 基线血缘必须可查询：当前生成、先前生成、产生提案、发布时间和回滚历史。
- 发布后生产漂移、在线回归或人工事件评审可请求基线回滚。
- 回滚是人工门控：当前基线标记为 `reverted`，选定的先前生成变为 `current`，基于回滚生成的进行中提案变为 `baseline_stale`。

发布后回滚与发布前 `rolled_back` 分离。`rolled_back` 表示候选从未成为基线。`reverted` 表示已发布的基线后来从当前服务中移除。

```python
ProposalState = Literal[
    "draft",
    "under_review",
    "rejected",
    "deferred",
    "approved",
    "handoff_ready",
    "implementing",
    "diff_review",
    "revising",
    "regression_running",
    "regression_review",
    "blocked_on_judge_recheck",
    "blocked_on_judge_migration",
    "baseline_stale",
    "validated",
    "rolled_back",
    "no_significant_change",
    "abandoned",
]

RegressionStatus = Literal[
    "not_started",
    "running",
    "waiting_for_judge_recheck",
    "waiting_for_judge_migration",
    "ready_for_review",
    "complete",
]

RegressionOutcome = Literal[
    "published",
    "rolled_back",
    "no_significant_change",
    "revise",
    "abandoned",
    "judge_recheck_required",
    "judge_migration_required",
    "baseline_stale",
]
```

### 生命周期规则

```
draft -> under_review
under_review -> rejected | deferred | approved
approved -> handoff_ready -> implementing -> diff_review
diff_review -> revising | abandoned | regression_running
revising -> implementing
regression_running -> regression_review
regression_review + published -> validated
regression_review + rolled_back -> rolled_back -> revising | abandoned
regression_review + no_significant_change -> no_significant_change -> deferred | abandoned
regression_review + revise -> revising
regression_review + abandoned -> abandoned
regression_review + judge_recheck_required -> blocked_on_judge_recheck
regression_review + judge_migration_required -> blocked_on_judge_migration
regression_review + baseline_stale -> baseline_stale
blocked_on_judge_recheck -> regression_running（评判器版本再次验证后）
blocked_on_judge_migration -> regression_review（基线用候选评判器版本重新评分后）
baseline_stale -> under_review（针对当前基线变基后）
deferred -> under_review（新证据、预算或产品优先级恢复时）
```

回归结果是决策事件，不是独立的提案状态（除非上文明确映射）。`judge_recheck_required`、`judge_migration_required` 和 `baseline_stale` 阻止或重定向提案通过权威生命周期，而非创建并行的仅 UI 状态。

`rejected` 对该提案 ID 是终态。如果想法后来应重新考虑，创建链接到原始拒绝原因的新提案。`deferred` 是有意可恢复的。

---

## 13. L3 分析引擎 (`flywheel/engine/`)

```
flywheel/engine/
├── sampler.py       # 错误分析的代表性轨迹采样
├── coder.py         # 开放编码支持和代码规范化
├── taxonomy.py      # 轴向聚类和分类注册表更新
├── dataset.py       # 数据集构建和分割强制执行
├── reader.py        # 从 Langfuse + 状态存储读取脱敏证据
├── analyzer.py      # 失败聚类和根因归因
├── proposer.py      # ImprovementProposal 生成
├── handoff.py       # 编码智能体移交文档
├── validator.py     # 回归、统计、候选评判器复检
└── writer.py        # 状态、评分和审计写入
```

### 分析流程

```
trigger_analysis(project, eval_run_id)
    |
    |-> 断言数据集和 judge_version 有效
    |-> reader.fetch_redacted_failed_evidence()
    |-> analyzer.cluster_failures()
    |-> analyzer.attribute_root_causes()
    |-> proposer.generate()
    |-> writer.store_proposal(consumed_case_ids, evidence_trace_ids)
    |
    |-> 门控 1: 人工提案评审
    |-> handoff.generate_for_coding_agent()
    |-> 门控 2: 人工 diff 或 PR 评审
    |-> validator.trigger_regression()
    |-> validator.compare_with_stats()
    |-> validator.run_candidate_judge_recheck()
    |-> 门控 3: 发布、回滚、修订、放弃或阻塞等待评判器复检
```

### 聚类要求

不要仅按顶层标签聚类。使用：

- 开放代码和分类标签
- 工具名称、工具错误和决定性 span
- 用例意图和数据集分割
- 评审意见相似性
- 测试框架指纹
- 重复轨迹特征
- 脱敏状态

每个 `FailureIssue` 应包含证据、反例、受影响标签和置信度。

### ImprovementProposal

```python
@dataclass
class ProposedChange:
    change_type: Literal["prompt", "tool_definition", "workflow", "config", "code"]
    target_file: str
    description: str
    rationale: str
    evidence_trace_ids: list[str]
    evidence_case_ids: list[str]
    suggested_diff: str
    risk_level: Literal["low", "medium", "high"]

@dataclass
class ImprovementProposal:
    proposal_id: str
    project: str
    baseline_fingerprint: str
    baseline_generation: int
    candidate_hypothesis_id: str
    source_eval_run_id: str
    taxonomy_version: str
    failure_issues: list[str]
    proposed_changes: list[ProposedChange]
    target_files: list[str]
    consumed_case_ids: list[str]
    consumed_trace_ids: list[str]
    proposer_id: str
    expected_metric_delta: dict[str, float]
    rollback_plan: str
    created_at: str
```

`consumed_case_ids` 记录提案生成器可见的每个用例，不仅是最终理由中展示的示例。

`candidate_hypothesis_id` 标识在回归留出集上测试的统计假设。默认身份是 `proposal_id + candidate_fingerprint`。因重试、评判器迁移或基线重新评分而重新运行同一候选不创建新假设。实质性改变候选指纹的实现修订为留出账本会计创建新假设。

`expected_metric_delta` 是预测，非证据。回归结果必须存储实际增量并与提案的预期增量比较。Flywheel 应跟踪长期提案生成器校准，以便重复过度乐观的提案来源可被降权或要求更多评审。

### 基线并发和变基

多个提案可同时进行，但只有一个基线是当前的。发布候选会递增 `baseline_generation` 并更改项目基线指纹。

规则：

- 提案仅在 `baseline_fingerprint` 和 `baseline_generation` 匹配当前项目 `Baseline` 时才能进入回归。
- 候选发布时，所有基于旧代的非终态提案标记为 `baseline_stale`。
- 过时提案必须针对新基线变基后才能返回 `under_review` 或 `regression_running`。
- 触及重叠 `target_files` 的提案不能并发发布。后来的提案等待变基或显式冲突解决。
- 回归报告必须显示自提案起草以来是否有任何目标文件发生了变化。

`target_files` 是保守近似，非语义独立性的证明。它可能过度阻塞大型提示词文件不同部分的独立编辑，也可能低估跨文件的耦合变更（如工具模式加引用该工具的提示词）。提案可添加 `target_symbols`、`prompt_sections` 或 `semantic_dependencies` 以改进冲突评审，但高风险冲突在 MVP 中仍是人工门控。

---

## 14. 回归门控

回归决定候选测试框架是否可以成为新基线。它必须防范噪声、泄露和评判器漂移。

### 机械化留出完整性

回归运行器必须计算：

```
consumed = proposal.consumed_case_ids
candidate_holdout = dataset.regression_holdout_cases - consumed
```

回归仅使用 `regression_holdout` 用例。它不得使用用于调优或验证评判器的 `train`、`dev` 或 `locked_test` 用例。

报告必须显示：

- `consumed_case_ids ∩ regression_holdout_cases`
- `regression_holdout_cases ∩ train_cases`
- `regression_holdout_cases ∩ dev_cases`
- `regression_holdout_cases ∩ locked_test_cases`

任何非空交集阻止发布。

### 留出复用和多重比较

随着候选反复针对相同用例测试，回归留出完整性衰减。Flywheel 必须跟踪留出暴露：

```python
@dataclass
class RegressionHoldoutLedger:
    dataset_id: str
    dataset_version: str
    holdout_case_ids: list[str]
    tested_hypothesis_ids: list[str]
    distinct_hypothesis_count: int
    raw_regression_run_count: int
    published_candidate_count: int
    last_cold_case_refresh_at: str
    multiple_comparison_policy: Literal["none", "bonferroni", "fdr"]
```

规则：

- 每次回归运行递增 `raw_regression_run_count` 用于可观测性。
- 多重比较校正使用 `distinct_hypothesis_count`，非原始运行计数。
- 假设每个留出版本计数一次，以 `candidate_hypothesis_id` 为键。
- 重试、评判器迁移、基线重新评分或基础设施故障后重新运行同一假设不得增加多重比较惩罚。
- 实质性变更的候选指纹或新提案 ID 创建新假设并添加到 `tested_hypothesis_ids`。
- 随着独立留出假设增加，发布阈值变得更严格，使用配置的多重比较策略。
- 当复用超过项目策略时，发布被阻止直到留出获得冷用例或轮换到新的留出版本。
- 回归报告必须显示独立假设计数、原始运行计数、冷用例覆盖率和任何阈值调整。
- 新基线应保留一些从未使用的冷用例用于未来回归检查。
- 如果冷用例耗尽，默认策略是阻止基线晋升。项目所有者可记录手动实验性发布，但在策划新鲜生产用例、轮换留出或显式降级统计门控并附带审计原因前，不得推进当前基线。

### 比较身份

```
基线:  dataset_id + case_id + sample_id + baseline_fingerprint + judge_version
候选: dataset_id + case_id + sample_id + candidate_fingerprint + judge_version
```

基线和候选必须使用相同的 `judge_version` 评分。来自旧评判器的缓存基线评分不可比较。回归比较前：

- 用候选的评判器版本重新评分基线留出用例，或
- 将结果标记为 `judge_migration_required` 并阻止发布。

显式的评判器迁移说明可解释历史指标为何变化，但不允许跨不同评判器直接进行基线/候选发布比较。

### 统计要求

默认策略：

- 预算允许时，非确定性用例至少重复 3 次
- 报告通过率和关键失败标签的置信区间
- 在候选可被称为胜利前定义有意义的最小增量
- 将噪声带内的小增量分类为 `no_significant_change`
- 发布要求无关键安全回归

### 回归结果

| 结果 | 含义 |
|---|---|
| `published` | 候选改善有意义指标并通过安全/评判器门控。 |
| `rolled_back` | 候选更差或引入关键回归。 |
| `no_significant_change` | 增量在噪声内；无基线变化。 |
| `revise` | 候选修复了某些问题但需要另一次提案迭代。 |
| `abandoned` | 提案路径不值得继续。 |
| `judge_recheck_required` | 候选分布使当前评判器失效。 |
| `judge_migration_required` | 基线和候选未使用相同评判器版本评分。 |
| `baseline_stale` | 提案进行期间项目基线已变化。 |

回归结果必须存储实际指标增量以及提案的预期增量。UI 应显示预期 vs 实际并记录比较用于提案生成器校准。

---

## 15. 实现阶段

对抗性评审有意优化正确性。MVP 仍须将硬正确性门控与可先手动或仅接口的机制分离。

### 第一天硬门控

这些是 Flywheel 安全发布新基线前的必需条件：

| 门控 | 第一天要求 |
|---|---|
| OTel 身份 | 评估轨迹存在 `trace_id`、数据集 id/version、case id、sample id 和测试框架指纹。 |
| 脱敏 | 展示给 UI 或 LLM 分析的证据通过脱敏；阻止的证据不能用于提案。 |
| 数据集分割 | `train`、`dev`、`locked_test` 和 `regression_holdout` 机械不相交。 |
| 评判器有效性 | 自动提案生成需要针对相关任务家族的已验证评判器。 |
| 同评判器比较 | 基线和候选回归评分使用相同的 `judge_version`；否则阻止发布。 |
| 回归留出 | 回归仅使用 `regression_holdout` 用例，排除已消费用例，并记录留出账本暴露。 |
| 基线对象 | 每个项目恰好有一个当前 `Baseline`，具有血缘和生成/指纹真相。 |
| 人工门控 | 提案审批、diff 评审、发布、回滚和发布后回滚需要显式人工动作。 |
| 权威生命周期 | DB、API、引擎和 UI 使用第 12 节的状态，无并行词汇表。 |
| 回滚路径 | 已发布基线可通过人工门控审计决策回滚到先前生成。 |

### 阶段 1.5 机制

这些机制在 MVP 中应有 schema/API 占位符，但可先手动或部分自动化：

| 机制 | MVP 立场 | 后续自动化 |
|---|---|---|
| 多重比较校正 | 存储 `RegressionHoldoutLedger` 并显示调整后的阈值输入。 | 自动用 Bonferroni/FDR 策略调整发布阈值。 |
| 生产漂移哨兵 | 定义周期、样本量和状态转换。 | 定时采样、评分和自动评判器复检传播。 |
| 基线变基 | 标记 `baseline_stale` 并要求手动变基评审。 | 自动检测低风险变基和冲突。 |
| 评判器迁移 | 阻止发布并要求同评判器基线重新评分。 | 排队基线重新评分作业并将候选返回 `regression_review`。 |
| 冲突检测 | 使用 `target_files` 加人工评审。 | 添加符号/段落/依赖图和冲突置信度。 |
| 脱敏分析 | 记录脱敏状态和阻止证据计数。 | 跟踪过屏蔽/欠屏蔽指标和策略建议。 |
| 成本治理 | 强制运行预算。 | 预测和分配跨项目的策划、漂移和聚类支出。 |

### 路线图

| 阶段 | 包含 | 不包含 |
|---|---|---|
| MVP | 仅 OTel 契约、Score Bridge、状态存储、数据/错误分析工作流、开放分类注册表、Langfuse 标注同步、已验证 `JudgeVersion`、失败问题、提案评审、移交 Markdown、带留出/统计门控的回归报告 | 自定义轨迹标注 UI、自动编码智能体执行、定时触发器 |
| 阶段 2 | 编码智能体执行器、PR/diff 链接、仅在 Langfuse 不足时的自定义标注工作流、候选审计工作流、更丰富的脱敏策略 UI | 全自动合并或发布 |
| 阶段 3 | 定时/阈值触发器、多项目趋势分析、长期分类漂移分析 | 自主部署 |

MVP 故意比完整的 LangSmith 克隆更小。它验证核心飞轮：数据策划、评判器资产质量、提案评审和回归决策。

---

## 16. 设计决策

| 决策 | 选择 | 原因 |
|---|---|---|
| 项目兼容性 | 需要 OTel | Flywheel 需要轨迹/span 关联和查询语义。 |
| 轨迹采样 | 评估轨迹完整导出 | 缺失 span 使评分/证据评审无效。 |
| 失败分类 | 开放版本化注册表 | 失败模式必须从数据中涌现，而非仅来自封闭枚举。 |
| 评判器校准 | 版本化评判器资产 | 评判器信任是任务/评判器特定的，非每次运行的状态。 |
| 评分摄取 | Flywheel API Score Bridge | 验证、重试、授权和审计属于服务端。 |
| 证据访问 | UI/LLM 使用前的脱敏流水线 | 防止轨迹中的秘密/PII 泄露。 |
| 证据存储 | Langfuse | 避免重建轨迹存储和轨迹 UI。 |
| 工作流存储 | Flywheel 状态存储 | Langfuse 评分不对数据集、分类、提案和发布门控建模。 |
| UI 时机 | MVP 中轻量 UI | 人工评审是核心，但轨迹标注最初可使用 Langfuse。 |
| 自动化级别 | 实现和发布前的人工门控 | 防止智能体垃圾并保留问责制。 |
