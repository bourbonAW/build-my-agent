# Flywheel 实现计划 — 索引

> **对于智能体工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现每个子计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 构建两份父规格中描述的自托管 Flywheel 控制平面 + 引擎 + UI：一个闭环评估改进系统，将真实运行轨迹转化为数据集、校准后的评判器、失败问题、人工评审的提案、回归决策和发布的测试框架基线。

**架构：** 新建 `flywheel/` 仓库，包含 Python 控制平面/引擎（FastAPI + 文件/SQLite 状态存储，同步，匹配 Bourbon 风格）和 React+TypeScript+Vite UI。Langfuse + OTel Collector 是证据存储（不在此构建，仅集成）。浏览器仅与 Flywheel API 通信，从不接收 Langfuse 写凭证。

**技术栈：** Python 3.13, FastAPI, pydantic v2, httpx, SQLite (stdlib `sqlite3`), pytest; React 18 + TypeScript + Vite, React Router, TanStack Query, TanStack Table, shadcn/ui, lucide-react, Recharts, Vitest + Testing Library + Playwright。

**父规格：**
- `docs/superpowers/specs/2026-06-22-flywheel-engine-design.md`
- `docs/superpowers/specs/2026-06-22-flywheel-ui-ux-design.md`

---

## 全局约束

这些约束适用于**每个**子计划和任务。值直接从规格复制。

- **OTel 必需。** `trace_id` 对评估运行绝非可选。每个项目必须具备 OTel 能力。不支持 JSONL 回退。
- **评估轨迹不做头部采样。** 带有 `flywheel.eval_run_id` 或 `flywheel.trace_pool_id` 的轨迹必须完整导出到 Langfuse。
- **分割必须机械不相交：** `train ∩ dev ∩ locked_test ∩ regression_holdout = ∅`。`locked_test` 验证评判器；`regression_holdout` 验证候选测试框架；它们绝不能共享用例。
- **脱敏失败时采用安全失败。** L3 分析器/提案生成器绝不能接收原始轨迹载荷。`blocked` 证据对 UI 隐藏并排除在 LLM 分析之外。状态存储记录产生每个证据视图的脱敏策略 + 版本。
- **同评判器比较。** 基线和候选回归评分必须使用相同的 `judge_version`；否则发布被阻止（`judge_migration_required`）。
- **权威生命周期状态。** DB、API、引擎和 UI 逐字使用第 12 节的 `ProposalState`、`RegressionStatus`、`RegressionOutcome`、`RunState`、`JudgeState` 枚举。无并行词汇表。`RegressionStatus` 是从 `ProposalState` **派生**的，从不独立持久化。
- **人工门控。** 提案审批、diff 评审、发布、回滚和发布后回滚需要显式人工动作。无全自动审批或发布。
- **所有变更的幂等性。** 重复提交返回现有对象。键：
  - `POST /api/scores`: `eval_run_id + case_id + sample_id + source + judge_version`
  - `POST /api/annotations`: `annotation_item_id + annotator_id + rubric_version`
  - 提案审批/拒绝/发布/回滚是比较并设置转换。
- **浏览器从不接收 Langfuse 写凭证。** 评分写入仅通过 Flywheel API Score Bridge。
- **每个项目一个当前基线**，具有可查询的血缘（当前/先前生成、产生提案、发布时间、回滚历史）。
- **开放分类注册表。** 任何地方不得硬编码封闭的 `FailureCategory` 枚举。分类版本发布后不可变；变更创建新版本 + 迁移映射。
- **授权角色：** 数据集策划者、评判器负责人、测试框架负责人、平台维护者。发布、回滚、发布后回滚、脱敏策略变更和提案审批需要显式角色检查。
- **所有变更返回** 更新后的对象**以及**一个仅追加的审计事件 ID。

---

## 仓库约定

```
flywheel/
├── pyproject.toml          # Python 包 "flywheel"，依赖，ruff/mypy/pytest 配置
├── sdk/                    # L1 SDK（计划 01）
├── api/                    # 控制平面：服务器、状态存储、Score Bridge、认证、审计、脱敏（计划 02、03）
├── engine/                 # L3：采样器、编码器、分类、数据集、读取器、分析器、提案生成器、移交、验证器、写入器（计划 04–07）
├── infra/                  # Langfuse + OTel Collector 的 docker-compose（参考，非编码计划）
├── datasets/               # 策划的数据集 YAML/JSON 制品
├── taxonomy/               # 分类注册表 YAML 制品
├── ui/                     # React 应用（计划 08）
└── tests/                  # pytest 树镜像包布局
```

**Python 约定（匹配 Bourbon）：**
- 同步代码。引擎/状态存储逻辑中无 asyncio。FastAPI 路由处理器可以是 `def`（同步）—— FastAPI 在线程池中运行它们。
- 引擎领域对象使用 `@dataclass`；API 请求/响应模式使用 pydantic `BaseModel`。
- 文件优先状态存储：磁盘上的 JSON/JSONL 位于 `~/.flywheel/<project>/`，使用 SQLite 索引进行可查询列表。崩溃安全 = 返回前追加到磁盘。
- 测试：`pytest`。Lint：`ruff check sdk api engine tests`。类型：`mypy sdk api engine`。

**测试命令：**
```bash
cd flywheel
uv pip install -e ".[dev]"
pytest                       # 全部
pytest tests/sdk -v          # 一个子系统
ruff check sdk api engine tests
mypy sdk api engine
# UI:
cd flywheel/ui && npm install && npm run test && npm run test:e2e
```

---

## 子计划 DAG

按依赖顺序执行。每个子计划以可工作的、可独立测试的软件结束。

```
00-index（本文档）
   │
   ▼
01-sdk ──────────────► 02-control-plane ──┬──► 03-redaction ──┐
                                          │                   │
                                          ├──► 04-data-analysis│
                                          │         │         │
                                          │         ▼         ▼
                                          │      05-judge ◄────┘
                                          │         │
                                          │         ▼
                                          │      06-engine ◄── 03
                                          │         │
                                          │         ▼
                                          │      07-regression
                                          │         │
                                          └─────────┴──► 08-ui（消费所有 API）
```

| 计划 | 文件 | 产出 | 规格覆盖 |
|---|---|---|---|
| 01 | `2026-06-23-flywheel-01-sdk.md` | 仓库脚手架、`flywheel.schema`、`FlywheelContext`、指纹、`ScoreClient`、指标 | 引擎 §6, §7 |
| 02 | `2026-06-23-flywheel-02-control-plane.md` | FastAPI 服务器、状态存储对象、Score Bridge、认证/角色、审计、幂等性、基线对象 | 引擎 §9, §12（基线）, UI §10, §11 |
| 03 | `2026-06-23-flywheel-03-redaction.md` | `RedactionService`、`EvidenceReader`、失败关闭流水线、脱敏分析 | 引擎 §10, UI §13 |
| 04 | `2026-06-23-flywheel-04-data-analysis.md` | 采样器、编码器、分类注册表+迁移、数据集构建+分割强制执行、预算 | 引擎 §5, §13（采样器/编码器/分类/数据集） |
| 05 | `2026-06-23-flywheel-05-judge.md` | `JudgeVersion` 生命周期、校准协议、锁定测试轮换、候选漂移复检、漂移哨兵 | 引擎 §11 |
| 06 | `2026-06-23-flywheel-06-engine.md` | 读取器集成、分析器（聚类+根因）、提案生成器、移交 Markdown、FailureIssue/ImprovementProposal | 引擎 §13（分析器/提案生成器/移交） |
| 07 | `2026-06-23-flywheel-07-regression.md` | 验证器：留出完整性、留出账本、统计/置信区间/噪声带、候选评判器复检、发布/回滚/无显著变化/回退 | 引擎 §12, §14 |
| 08 | `2026-06-23-flywheel-08-ui.md` | React 应用：所有 MVP 路由 + 阶段 2 路由、决策表单、API 客户端、Playwright 循环测试 | UI 规格（全部） |

---

## 阶段映射（覆盖 = 完整：MVP + 阶段 2/3）

根据引擎规格 §15，每个子计划用其满足的阶段标记任务：

- **第一天硬门控** — OTel 身份（01,02）、脱敏（03）、数据集分割（04）、评判器有效性（05）、同评判器比较（07）、回归留出（07）、基线对象（02,07）、人工门控（02,08）、权威生命周期（02）、回滚路径（02,07）。
- **阶段 1.5 机制** — 多重比较校正（07）、漂移哨兵（05）、基线变基（07）、评判器迁移（07）、冲突检测（06,07）、脱敏分析（03）、成本治理（04）。MVP 立场 = schema/API 占位符 + 手动；后续自动化按任务注明。
- **阶段 2** — 编码智能体执行器 + PR/diff 链接（06,08）、自定义标注工作流（08）、候选审计工作流（05,08）、更丰富的脱敏策略 UI（03,08）。
- **阶段 3** — 定时/阈值触发器、多项目趋势分析、长期分类漂移分析（作为最终任务添加到 04、05、07、08，标记为阶段 3）。

---

## API 端点所有权（UI §10）

每个 UI §10 端点恰好分配给一个子计划。计划 02 实现运行和基线端点，并用 501 占位所有其他端点。

| 端点 | 方法 | 所有者计划 |
|---|---|---|
| `/api/runs` | GET, POST | 02 |
| `/api/runs/{run_id}` | GET | 02 |
| `/api/runs/{run_id}/scores` | POST | 02（占位） → 04 连接分类验证 |
| `/api/runs/{run_id}/sync-labels` | POST | 06 |
| `/api/runs/{run_id}/analysis` | POST | 06 |
| `/api/baselines` | GET, POST | 02 |
| `/api/baselines/{generation}` | GET | 02 |
| `/api/baselines/{generation}/revert` | POST | 02 |
| `/api/projects` | GET | 04 |
| `/api/datasets`, `/api/datasets/{id}` | GET | 04 |
| `/api/datasets/{dataset_id}/cases` | POST | 04 |
| `/api/taxonomy` | GET | 04（标签+迁移聚合；UI §10） |
| `/api/taxonomy/labels`, `/api/taxonomy/migrations` | GET, POST | 04 |
| `/api/taxonomy/propose-update` | POST | 04 |
| `/api/trace-pools` | GET | 04 |
| `/api/trace-pools/{pool_id}/sample` | POST | 04 |
| `/api/open-code-batches/{batch_id}` | GET | 04 |
| `/api/open-code-batches/{batch_id}/codes` | POST | 04 |
| `/api/judges`, `/api/judges/{version}` | GET | 05 |
| `/api/judges` | POST | 05 |
| `/api/judges/{judge_version}/validate` | POST | 05 |
| `/api/annotations`, `/api/annotations/{id}` | GET, POST | 05 |
| `/api/issues`, `/api/issues/{issue_id}` | GET | 06 |
| `/api/proposals/{proposal_id}` | GET | 06 |
| `/api/proposals/{proposal_id}/handoff` | POST | 06 |
| `/api/proposals/{proposal_id}/implementation-link` | POST | 06 |
| `/api/proposals/{proposal_id}/rebase` | POST | 06 |
| `/api/proposals/{proposal_id}/approve` | POST | 07 |
| `/api/proposals/{proposal_id}/reject` | POST | 07 |
| `/api/proposals/{proposal_id}/defer` | POST | 07 |
| `/api/regressions` | POST | 07 |
| `/api/regressions/{regression_id}` | GET | 07 |
| `/api/regressions/{regression_id}/publish` | POST | 07 |
| `/api/regressions/{regression_id}/rollback` | POST | 07 |
| `/api/regressions/{regression_id}/no-significant-change` | POST | 07 |
| `/api/regressions/{regression_id}/require-judge-recheck` | POST | 07 |
| `/api/regressions/{regression_id}/resume-after-judge-recheck` | POST | 07 |
| `/api/regressions/{regression_id}/require-judge-migration` | POST | 07 |
| `/api/regressions/{regression_id}/resume-after-judge-migration` | POST | 07 |
| `/api/redaction/reports` | GET | 03 |
| `/api/evidence/{path}`, `/api/traces/{path}` | GET | 03（受 REDACTION_ENABLED 保护） |

## 依赖说明

- **计划 05 继承计划 02 的类型定义。** `JudgeState`、`JudgeVersionModel` 和 `JudgeDriftCheckModel` 在计划 02 的 `api/lifecycle.py` 和 `api/schemas.py` 中定义。计划 05 导入并扩展行为但不重新定义这些类型。
- **脱敏硬门控（引擎 §10, §15）：** 计划 02 证据服务端点（`/api/evidence/*`、`/api/traces/*`）返回 503 直到设置 `REDACTION_ENABLED` 环境变量。此变量仅在计划 03 `RedactionService` 连接到应用后设置。不要将 `REDACTION_ENABLED=1` 作为计划 02 集成测试的一部分设置。

## 执行顺序说明

计划 03 和 04 都仅依赖 02，可以并行运行。05 需要两者。06 需要 03+05。07 需要 05+06。08 需要每个 API 契约，但其基础任务（脚手架、路由器、API 客户端、运行/数据页面）可以在 02 稳定后开始。在每个计划内，任务严格排序。
