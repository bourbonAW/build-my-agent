# Flywheel 本地案例库：自己管理标签而非 Langfuse 数据集

**日期**: 2026-07-02
**状态**: 草稿
**取代**: `2026-06-22-flywheel-engine-design.md` — 具体包括:
  - §2 复用表行 "数据集 + 数据集项目" 和 "分数 / 标签 / 注释"
  - §5 第4步 ("将代表性失败升级为 Langfuse 数据集")
  - §6 (60/20/20 `judge_train`/`judge_dev`/`judge_test` 划分, 每类支持下限, 宏F1门槛作为通过/失败门槛)
  - §7 不相交性断言 ("回归集与整个判官案例池无重叠")
  - §10 设计决策行 "数据 / 分数 / 数据集 → Langfuse 原生"
**未变**: OTel `gen_ai.*` 追踪属性, Langfuse 作为追踪/可观测性记录系统, `flywheel/` 本地文件报告 + 薄读API + React UI, `identity.py`/`metrics.py`/`report.py`, `regression.py` 中的 McNemar 精确测试机制 (被移除的是该测试的不相交性*前提条件*, 不是测试本身).
**相关**: `2026-06-22-flywheel-engine-design.md`, `2026-06-22-flywheel-ui-ux-design.md`

---

## 0. 为什么要反转之前的深思熟虑的决定

原始引擎设计选择了 "复用 Langfuse 数据集 + 分数 + 原生注释UI, 不要构建私有注释表" 作为一项原则 — 避免针对已经建模此功能的系统进行双重记账。这项原则总体上仍然是正确的。改变的是在该项目上直接实践使用所产生的工作流:

- 升级追踪会创建一个 Langfuse **数据集项目**, 但对其进行标签化需要在 Langfuse 项目详情页面手动编辑原始 JSON `metadata` blob — 没有针对 `splits` / `failure_label` / `human_label` 的结构化表单, 因为这些是 flywheel 发明的约定, 叠加在通用 `metadata` 字段上, 不是 Langfuse UI 理解的内容.
- Langfuse 自己的 **人工注释** 功能 (队列, 分数配置) 是一个真实的、精美的标签化UI — 但它写的是附加到**追踪**的**分数**, 而不是数据集项目的 `metadata`. 任务6的实际实现读取 `metadata.human_label`, 从不读分数. 两个界面互不通话: 人类可以完成一个注释队列并在 Langfuse 中看到100%的进度, 而 `validate_judge.py` 仍然认为该项目未被标签化.
- 实际结果是两个断开的"标签化"界面 (元数据编辑和人工注释) 都没有真正为 `flywheel` 的特定字段设计, 加上第三个无关的概念 (Langfuse "实验" / 数据集运行) 这个代码库根本不使用. 这不是 Langfuse 是个坏产品 — 而是一个通用目的的eval平台的UI尴尬地硬套在一个维护者的狭隘、已经决定的标签架构上.

对于单个维护者的项目, 每个案例需要捕获一个小的、固定的字段集, 直接拥有该存储和UI现在比继续弯曲 Langfuse 的数据集/注释模型来适配少得多的代码和摩擦. Langfuse 真正标准的部分 — 通过OTel `gen_ai.*` 的追踪捕获 — 保持不变, 仍然是原始执行历史的记录系统.

---

## 1. 目标

用一个 flywheel 拥有的本地存储和一个目的性构建的标签化UI替换 "Langfuse 数据集项目 + 手动编辑的元数据 + 断开的人工注释队列", 同时保持所有上游 (追踪捕获) 和下游 (测试运行, 判官评分, 回归对比, 报告) 的工作方式相同 — 只是从不同的地方读取.

```
真实追踪 -> 查看失败 -> 少数可重放案例
        -> 对其评分 (判官) -> 改变一件事
        -> 重新运行, 比较通过率, 不要回归
```

这个目标与原始引擎设计的§1相同. 只有"少数可重放案例"存储和标签化步骤改变.

---

## 2. 与原始设计相比的变化

| 关注点 | 原始 (2026-06-22) | 新 (本文档) |
|---|---|---|
| 数据集项目 | Langfuse 数据集 | 本地 `cases.jsonl`, `case_id` = Langfuse `trace_id` |
| 标签 / 评论 | Langfuse 分数 + 自由文本评论 | `Case.label` / `Case.critique` 字段, 在新的 flywheel `/label` UI 中编辑 |
| 失败分类 | `flywheel/labels.md` 中的自由字符串, 附加为分数评论 | `Case.failure_category`, 可选自由字符串, 相同精神 — 只是存储在案例上而非 Langfuse 分数 |
| 划分策略 | `judge_train`/`judge_dev`/`judge_test`/`regression`, 相互不相交, 在加载时强制 | **已移除.** 每个带标签的案例 (`label` 是 `pass` 或 `fail`) 可以同时用作回归比较输入和判官验证证据. |
| 判官验证 | 60/20/20 分层划分, 每类支持下限 (≥5 黄金每类在保留的20%), 宏F1 ≥ 0.70 **门槛** 阻断/解除流 | **连续指标, 不是门槛**: 判官-vs-人类同意 (F1) 计算在*所有*当前标签化的 `pass`/`fail` 案例上, 每次运行判官时重新计算并显示. 没有通过/失败阈值阻断管道. |
| 回归不相交性 | 声言回归集 ∩ 完整判官池 = ∅ | **已移除** — 现在只有一个池, 所以声言是空洞的. |
| 回归显著性测试 | 基线 vs 候选的成对精确 McNemar 符号测试 | **未变.** 这是关于在相同案例上比较两个测试运行, 与标签存储位置正交. |
| 人工注释UI | Langfuse 注释队列 | 新 flywheel `/label` 路由 (见§6) |

权衡被明确说明: 这放弃了原始设计围绕判官验证的统计严谨性 (分层抽样, 保留的测试划分, 每类支持下限, 硬F1门槛). 这种严谨性存在是为了防止判官被隐含地过度拟合到用于评级它的确切案例. 在当前规模 (单数位到低两位数的案例计数, 一个维护者做所有标签化), 一个专用的保留划分比该案例体积能支持的更多过程, 而连续的全池同意指标更可操作. 如果案例池增长到大约~50标签化案例每类, 重新审视重新引入保留划分 — 见§10.

---

## 3. 架构 / 数据流

```
Langfuse 追踪 (不变 — 追踪/可观测性记录系统)
      | sample_traces.py (不变 — 启发式标记 + 分层抽样)
      v
sample_traces.json (不变 — 本地候选池)
      | 升级 (变化: 无 Langfuse 数据集/项目调用)
      v
cases.jsonl  <-- 新 flywheel 拥有的存储, case_id = trace_id
      | /label UI (新)
      v
cases.jsonl 原地更新 (追加只, 最后一条记录 per case_id 赢)
      | run_harness.py / run_judge.py / validate_judge.py / run_regression.py
      v
(变化: 直接读取 cases.jsonl, 无 Langfuse get_dataset(), 无划分过滤)
```

Langfuse 的角色缩小到恰好一件事: 提供 `sample_traces.py` 读取的原始追踪. "升级"之后的一切都是一个本地文件循环, 从不再与Langfuse通话. Langfuse 数据集和人工注释不再被该管道使用.

---

## 4. 数据模型: `Case`

存储为追加只JSONL在
`~/.flywheel/<project>/state/cases.jsonl` (与 `sample_traces.json` 和 `runs/*.jsonl` 相同的目录约定). 读取通过 `case_id` 解决重复, 最后一条记录赢 — 镜像已由 `write_run_outputs` 使用的崩溃安全模式和来自 `intelligent_customer` 参考项目的追加注释日志模式.

```python
class Case(TypedDict):
    case_id: str                    # = 源追踪中的 trace_id; 全局唯一
    input: str                      # 在升级时从追踪复制
    frozen_output: str              # 代理在该追踪上的实际输出, 在升级时复制
                                     # — 标签化者判的内容, 和固定参考
                                     # run_judge.py 用于少步骤示例
    trace_url: str                  # 深链接回 Langfuse 追踪以获得完整上下文
    expected_output: str            # 在标签化期间填充; "" 直到标签化
    label: Literal["pass", "fail", "skip"] | None   # None 直到标签化
    critique: str                   # 可选自由文本, 当 label == "fail" 时鼓励 (非必需)
    failure_category: str | None    # 可选自由字符串; 目前无强制分类
    annotated_at: str               # ISO 8601; "" 直到首次标签化
```

故意在评审期间剪切的字段及为什么:
- `annotated_by` — 尚不需要多用户概念 (单个维护者).
- `source_trace_score` (`sample_traces.py` 启发式标记) — 从未被下游使用; `trace_url` 在需要时提供对完整上下文的直接访问, 比陈旧启发式快照更好.
- `promoted_at` — JSONL 追加顺序已在该规模捕获升级顺序; 不值得专用字段.
- `splits` — 按§2移除.

---

## 5. 后端变化

### 5.1 升级重写 (`api/pipeline.py`)

`promote_cases()` 完全放弃 `create_dataset()` / `create_dataset_item()` /
`_write_langfuse_dataset()` 调用. 它反而:
1. 从 `sample_traces.json` 加载选定的条目.
2. 对每一条, 如果 `case_id` (追踪id) 已存在于 `cases.jsonl`, 跳过它 (从不覆盖现有标签).
3. 追加新的 `Case` 记录: `input`/`frozen_output` 从追踪自己的 `input`/`output` 字段复制 (已由 `sample_traces.py` 的 `_as_dict()` 捕获), `expected_output=""`, `label=None`.
4. 返回总结: `{promoted: N, skipped: M}`.

`dataset.name`/`total_cases` 簿记在 `pipeline_state.json` 被指向 `cases.jsonl` 的计数而非 Langfuse 数据集名.

### 5.2 新案例端点

- `GET /api/pipeline/cases` — 完整的案例列表 (标签化和未标签化), 由 `/label` UI 和 `DatasetPanel` 的进度显示使用.
- `POST /api/pipeline/cases/{case_id}/label` — 主体: `expected_output`,
  `label`, `critique`, `failure_category`. 为该 `case_id` 追加新记录 (从不原地改变 — 相同的追加只, 最后赢模式), 由与本会话早期修复通过为 `pipeline_state.py` 的 `mutate()` 引入的相同 `threading.Lock` 保护的写助手保护, 以防止并发标签提交损坏文件.

### 5.3 脚本层 (`scripts/common.py` + 四个运行脚本)

- `DatasetItem` 数据类: 放弃 `splits`, `failure_label`, `human_label`;
  添加与 `Case` 匹配的字段 (`label`, `critique`, `failure_category`).
- `load_dataset_items()`: 放弃 Langfuse `get_dataset()` 分支; 仅读取本地JSON. 在所有四个脚本 (`run_harness.py`, `run_judge.py`,
  `validate_judge.py`, `run_regression.py`) 中将 `--dataset-json` CLI 标志重命名为 `--cases-path` 以停止暗示涉及 Langfuse "数据集".
- `ensure_disjoint_splits()` (`scripts/common.py`) 和
  `check_splits_disjoint()` (`flywheel/regression.py`): **删除**, 连同它们在 `run_harness.py` 和 `run_regression.py` 中的调用站点.
- `require_failure_labels()`: **删除** (failure_category 现在是可选的到处, 不仅仅非回归项).
- `run_harness.py`: 运行每个 `label != "skip"` 的案例 (之前: `regression` 划分中的每个案例).
- `validate_judge.py`: 从通过/失败**门槛**重写为**连续报告** — 计算判官-vs-人类 F1 (和每标签精确/回忆/混淆矩阵, 与今天相同的数学) 在每个带 `label in ("pass", "fail")` 的案例上, 无保留划分, 无支持下限检查, 无 `passes: bool` 门槛字段阻断下游步骤.
- `run_judge.py`: 判官少步骤示例从任何标签化案例抽取, 使用 `Case.frozen_output` (§4) 作为被评级的固定输出和 `Case.label` 作为黄金判决 — 无架构间隙; `frozen_output` 在升级时自动填充 (§5.1).

---

## 6. 前端: `/label` 路由

现有 flywheel React 应用 (`flywheel/ui/src/App.tsx`) 中的新路由, 以 `intelligent_customer/eval/templates/annotate.html` 的交互模式建模, 以 React 组件重新实现而非直接移植.

```
+---------+------------------------------------------+
| 条 状 |  详情面板                                 |
| 案1 o |  输入: ...                               |
| 案2 v |  实际输出 (frozen_output): ...            |
| 案3 v |  [ 查看原始追踪 -> ]                      |
| 案4 o |  预期输出: [文本区]                       |
|  ... |  ( 通过 )  ( 失败 )  ( 跳过 )             |
|     |  评论 (可选): [文本区]                    |
|     |  失败分类 (可选): [文本输入]              |
|     |  [ 保存 (回车) ]  [<- 上一个]  [下一个 ->] |
+---------+------------------------------------------+
```

标签化者判官 `frozen_output` (代理实际说的) 对比他们自己的 `expected_output` 来决定通过/失败/跳过 — `frozen_output` 是只读的, 总是显示, 从不编辑.

- 左条: `o` 未标签化 / `v` 已标签化, 点击跳转; 默认落在第一个未标签化案例.
- 键盘: `←`/`→` 导航, `回车` 保存并自动前进到下一个未标签化案例 (镜像 `annotate.html` 的流, 优化快速顺序标签化许多案例).
- 保存通过 `useMutation` 调用 `POST /api/pipeline/cases/{case_id}/label`, 乐观地更新条的对勾状态.
- `DatasetPanel` 的现有 `LabelStatusRow` ("人工标签 x/y") 从查询 Langfuse 数据集项目分数切换到 `GET /api/pipeline/cases`, 计算 `labeled = count(label != null)` 客户端. "在 Langfuse 中标签化 ↗" 外部链接变为应用内 `<Link to="/label">`.
- 顶部导航 (`Shell` 组件) 获得第三条条目: `控制 | 标签 | 历史`.

---

## 7. 错误处理

- 升级已存在的 `case_id`: 跳过, 报告计数跳过 — 从不无声覆盖现有标签.
- `cases.jsonl` 读: 用警告跳过格式不正确的单个行 (匹配 `intelligent_customer/eval/annotate.py` 的 `load_jsonl`), 而非在来自被杀死的写者的一个损坏行上失败整个加载.
- 并发写: 锁保护追加 (见§5.2).
- 零标签化案例, 或所有案例 `skip`/未标签化, 当 `run_harness.py` 或 `validate_judge.py` 运行: 抬起清晰 `SystemExit` 消息 (与现有 `"dataset has no regression items"` 检查相同风格), 不是来自脚本深处的裸异常.

---

## 8. 测试

- 后端: `Case` 解析/序列化, 升级去重逻辑, 和 `cases.jsonl` 追加/最后赢读行为的单元测试, 遵循现有 `flywheel/tests` 约定.
- 脚本层: 移除现已死的划分不相交测试; 添加新 `label`/`critique`/`failure_category` 字段和 `--cases-path` 重命名的覆盖.
- 前端: 当前此回购不存在React应用的自动测试基础结构; 通过 `/run` 技能手动验证 `/label` 流 (升级 → 标签化 → 保存 → 运行基线), 如本会话其余UI工作所做.

---

## 9. 现有数据 / 迁移

已升级到 Langfuse `bourbon-evals` 数据集的5个项目 (包括一个手动编辑的 `expected_output`) **不被**迁移. 它们被放弃; 一个新鲜的样本 → 升级周期在此发货后从头填充 `cases.jsonl`. Langfuse 数据集本身被留在原样 (未删除) — 它简单地停止被写入或读取.

---

## 10. 延期 (不是被拒 — 用证据重新审视)

| 项目 | 重新审视何时 |
|---|---|
| 保留的判官验证划分 + 每类支持下限 + 硬F1门槛 | 标签化池增长到大约~50案例每类并且单个维护者不再手动验证每个判官分歧 |
| `failure_category` 强制分类 (必需字段, 固定枚举) | 稳定的分类集合从自由文本使用自然出现 |
| 多用户 `annotated_by` | 超过一个人标签化案例 |
| 重新同步标签回 Langfuse (例如作为分数, 用于跨工具可见性) | 这个单维护者循环之外的某人需要在 Langfuse 内看到标签 |
