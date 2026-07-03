# Flywheel 实施计划 — 索引（精简修订 2026-06-24）

> **面向 Agent 工作者：** 必需子技能：superpowers:test-driven-development
> 用于 Python 核心；前端使用 Vitest + Testing Library。步骤使用
> 复选框（`- [ ]`）语法。

> **⚠️ 本索引已为精简 MVP 重写。** 之前的版本要求控制平面（State Store、5 个生命周期枚举、Score Bridge、~45 个端点、
> 分类注册表、脱敏管线、保留账本）并指向子计划 03–08。**所有这些已被取代。** 参见 `specs/2026-06-22-flywheel-engine-design.md`
> §0 了解为何削减了约 85%。子计划 **03–08 已被删除** — 其存留内容已合并到计划 01/02 中，其余部分按引擎规格 §8 推迟。
> 下表记录了每个计划的原始内容（git 历史保留了原件）；请勿重新创建或实现它们。这些文档的中文 `-zh` 变体被故意保留未修改，仍描述旧设计 — 也不要根据它们来实现。

**目标：** 让 Bourbon 通过自身的 trace 实现可衡量的改进，使用能闭合循环的最小机制：真实 trace → 查看失败 → 几个可重放的用例 → 评分（judge）→ 改变一件事 → 重新运行，比较，不回退。

**架构：** 一个小型 `flywheel/` Python 包（纯逻辑核心 + 轻量只读 API）加上一个真正的 React+Vite 前端。**Langfuse** 是证据存储，拥有 trace、数据集、分数和标注（不在此重建）。
**OpenTelemetry `gen_ai.*`**（Bourbon 已经在发射）是 trace 约定；唯一的新属性是 `eval.case_id` 和 `eval.run_id`。

**技术栈：** Python 3.13, pydantic v2, FastAPI（只读）, pytest; React +
TypeScript + Vite, React Router, TanStack Query/Table, Recharts, Vitest +
Testing Library, 一个 Playwright 端到端主流程测试。

**父规格：**
- `docs/superpowers/specs/2026-06-22-flywheel-engine-design.md`（精简版）
- `docs/superpowers/specs/2026-06-22-flywheel-ui-ux-design.md`（精简版）

---

## 全局约束

适用于以下所有任务。

- **复用标准，不要重新发明。** 执行时 trace 属性 = OTel
  `gen_ai.*` + `eval.case_id`/`eval.run_id`。数据集、分数、标注、trace
  浏览 = Langfuse 原生功能。不使用私有 `flywheel.*` 约定，不使用 State Store
  对 Langfuse 对象进行重新建模。
- **仅四个身份概念：** `case_id`、`run_id`、`label`（人工标注为
  `pass`/`fail`；judge 裁定以分类形式持久化，也可以是
  `uncertain`；`Label` 类型还携带 `skip` — `skip`/`uncertain` 是
  非成功状态）和 `trace_id`。另加一个最小化的 harness id `git_sha@model` 和一个纯文本
  `judge_version` 字符串。没有 8 部分指纹，没有生命周期枚举。
- **存留的正确性门控**（断言，不是状态机）：`compare()` 在以下任何情况下抛出异常 —
  - *同一 judge：* baseline 和 candidate 必须由同一个 `judge_version` 评分。
  - *同一总体：* baseline 和 candidate 必须覆盖相同的 case id。
  - *完整性：* 比较集必须等于完整声明的回归拆分
    （两次运行都静默丢弃的 case 不得在更简单的子集上通过）。
  - *互斥性：* 回归拆分不得与 judge 验证拆分重叠（完整的 `judge_train ∪ judge_dev ∪ judge_test`）。
  - 加上明确拒绝：`compare()` 在回归集为空或 case id 重复时抛出异常；`validate()` 在 **重复** case id 时抛出异常，但将
    **不足/不均衡** 的验证拆分视为 *未验证*（`passes=false`，
    而非抛出异常 — 证据不足是非验证，不是使用错误）。
- **Judge 是唯一经过验证的资产。** macro-F1 ≥ 0.70 **且** fail 类别 F1 ≥ 0.70
  （高 macro 但对失败视而不见的 judge 不得通过验证）+ 每类别 gold 样本量
  （通过重新运行 `validate.py` 重新计算），而非 6 状态生命周期。
- **回归结果是三值的：** `better | no_change | worse`，由
  **精确双侧配对符号检验**（McNemar 精确检验）对不一致对决定；
  Wilson delta CI 仅作为描述性噪声带报告（在微小不一致计数上它是反保守的）。提案是 git PR；baseline
  是 `main`；"发布"是合并。
- **没有控制平面。** 没有认证/角色，没有审计日志，没有幂等层，没有
  Score Bridge。只读 API 是只读的；浏览器永远不会收到 Langfuse 写入凭据。

---

## 仓库约定

```
flywheel/
├── pyproject.toml          # package "flywheel" + sibling package "api"
├── flywheel/               # core library (plan 01) + judge/validate/report (plan 02)
│   ├── identity.py metrics.py regression.py
│   └── judge.py validate.py report.py
├── api/                    # thin read-only FastAPI + runs_provider.py (plan 02)
├── scripts/                # Bourbon/Langfuse glue: sample_traces.py, run_harness.py, run_judge.py, validate_judge.py, run_regression.py (plan 02 Task 6)
├── ui/                     # React + Vite frontend (plan 02 Task 5)
├── labels.md               # flat editable failure-label list (plan 01)
└── tests/                  # pytest tree
```

**约定（与 Bourbon 保持一致）：** 同步代码，不使用 asyncio；领域对象使用 `@dataclass`，仅在验证有帮助时使用 pydantic；纯逻辑核心采用 TDD；报告 JSON 端到端使用 camelCase（UI §7），因此只读 API 原样返回。

**测试命令：**
```bash
cd flywheel
uv pip install -e ".[dev]"
pytest
ruff check flywheel api tests
mypy flywheel api
cd ui && npm install && npm run test -- --run && npx playwright test
```

---

## 子计划依赖图（8 个计划 → 2 个）

```
00-index (this doc)
   │
   ▼
01-sdk (core library: identity, metrics, regression)
   │
   ▼
02-control-plane (judge, validate, report, read API, frontend, Bourbon glue)
```

| 计划 | 文件 | 产出 | 规格覆盖 |
|---|---|---|---|
| 01 | `2026-06-23-flywheel-01-sdk.md` | 仓库脚手架、`identity.py`（Harness, Label）、`metrics.py`（P/R/F1, Wilson CI）、`regression.py`（3 值 compare + 门控）、`labels.md` | Engine §4, §5, §7 |
| 02 | `2026-06-23-flywheel-02-control-plane.md` | `judge.py`、`validate.py`、`report.py`、轻量只读 API、React 前端、Bourbon 集成胶水 | Engine §6, §9; UI spec |

> 文件名仍然是 "01-sdk" / "02-control-plane" 以保持 git 连续性，但
> 其**内容是精简重写版** — 既不是 SDK 也不是控制平面。

### 已删除的子计划（不要重新创建）

这些文件在精简修订中**已被删除**（可从 git 历史中恢复）。
每行记录了该计划的内容及其存留范围的去向。

| 文件（已删除） | 原内容 | 处置 |
|---|---|---|
| `2026-06-23-flywheel-03-redaction.md` | 脱敏管线 | 推迟（Engine §8）；单一受信维护者无需脱敏。 |
| `2026-06-23-flywheel-04-data-analysis.md` | 采样器/编码器/分类注册表/数据集拆分 | 数据和标注存储在 Langfuse 中；标签是一个扁平的 `labels.md`。 |
| `2026-06-23-flywheel-05-judge.md` | JudgeVersion 生命周期 + 漂移哨兵 | 被 `validate.py` 取代（macro-F1 ≥ 0.70）。 |
| `2026-06-23-flywheel-06-engine.md` | 分析器/提案器/交接 | 提案是 git PR（Engine §8 添加触发器）。 |
| `2026-06-23-flywheel-07-regression.md` | 保留账本、Bonferroni/FDR、发布/回滚状态 | `regression.py` 3 值结果 + Wilson 噪声带。 |
| `2026-06-23-flywheel-08-ui.md` | 完整 13 路由控制 UI | UI 是计划 02 Task 5（3 个路由）。 |

---

## API 接口（45 → 3，只读）

| 端点 | 方法 | 所属计划 |
|---|---|---|
| `/api/runs` | GET | 02 |
| `/api/runs/{run_id}` | GET | 02 |
| `/api/judges/{judge_version}` | GET | 02 |

旧索引中列出的其他所有内容（分数、标注、数据集、分类、
trace 池、issue、提案、回归、baseline、脱敏）要么是
Langfuse 原生操作，要么是已删除的概念。

---

## 执行顺序

计划 01（纯逻辑，TDD）→ 计划 02（judge/validate/report TDD，然后只读 API，
然后前端，然后 Bourbon 胶水在 Task 6 中）。每个计划内，任务严格有序。将仓库
与 trace→case 链接起来的关键在 **计划 02 Task 6** 中完成（Bourbon span 属性 + `run_harness.py` + `run_judge.py` +
`run_regression.py` + `runs_provider`），而非在纯逻辑任务中。
