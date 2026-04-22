# Skill Evaluation Paradigms & The Criterion Problem

> **Session Date**: 2026-04-21
> **Context**: 在 Bourbon 项目已实现 promptfoo-based eval 框架后，对 Claude Code skill-creator 和 SkillsBench 的 eval 设计进行深度对比分析，并由此引出评估理论中的信任悖论。

---

## 一、两种根本对立的 Eval 范式

当前 agent skill 的评估领域存在两条泾渭分明的路线：

| 维度 | Claude Code skill-creator | SkillsBench |
|------|--------------------------|-------------|
| **核心哲学** | LLM 是万能的评判者 | 只有程序化断言才是可信的 |
| **断言表达** | 自然语言 `expectations[]`（rubric） | Pytest 单元测试 + 数值断言 |
| **评分引擎** | Grader Agent（独立 LLM）| pytest 执行器 |
| **验证对象** | 输出内容 + 执行过程（transcript）| **仅最终结果**（outcome-based）|
| **可复现性** | 不在意（接受 LLM 方差）| **核心要求**——100% 可复现 |
| **Anti-cheat** | 基本不考虑 | 强要求——防止 agent 读 solution |
| **Skill Delta 测量** | 概念上有（with-skill vs baseline）| **核心指标**（with vs without）|
| **环境隔离** | 无（直接文件系统运行）| Docker 容器完全隔离 |
| **适用场景** | Skill 作者快速迭代、原型验证 | 大规模 benchmark、模型能力排名 |

### 1.1 Claude Code skill-creator：全量 LLM-rubric

skill-creator 的评估设计可以概括为 **"LLM-as-judge as first principle"**：

- **Expectations 即 rubric**：`evals.json` 中的 `expectations` 是自然语言描述的成功标准，例如：
  ```json
  "expectations": [
    "The output includes the name 'John Smith'",
    "The spreadsheet has a SUM formula in cell B10"
  ]
  ```
- **Grader Agent 评判一切**：由独立 LLM agent 读取完整 transcript 和输出文件后做主观判断，输出 `grading.json`（`text` / `passed` / `evidence`）。
- **程序化断言只是脚注**：虽然提到 "write and run a script"，但这些脚本是 LLM 根据场景临时生成的，并非工程化基础设施。
- **连 eval 改进都是 LLM 自我批判**：`eval_feedback` 字段让 LLM 评判自己的 rubric 是否好。

**优势**：快速迭代，减少编写断言的负担。
**劣势**：可复现性差，评分方差大，不适合 CI 回归。

### 1.2 SkillsBench：工程化确定性评估

SkillsBench 是对 skill-creator 路线的**直接反叛**，其 rubric 明确声明：

> **"No LLM-as-judge unless you can show multiple LLMs always agree and document why programmatic checks won't work."**

核心设计支柱：

1. **Outcome-Based Verification**：只测最终结果，不测过程。
2. **Deterministic Tests**：`test_outputs.py` 全是可计算的数值断言（误差范围、阈值判断）。
3. **Skill Delta 测量**：每个 task PR 必须提供 with-skill 和 without-skill 的 pass rate 对比。
4. **Docker 隔离 + Anti-cheat**：agent 以 root 运行，tests/ 和 solution/ 不放入 image。
5. **人工真实性**：`instruction.md` 和 `solve.sh` 必须人工编写，甚至用 GPTZero 检测 AI 生成内容。

**优势**：高可复现性，可 CI 集成，可信的模型排名。
**劣势**：任务设计成本高，需要人工编写 oracle 和测试。

---

## 二、Eval-Set 的 Schema 与位置差异

### 2.1 skill-creator

- **位置**：skill 目录下的 `evals/evals.json`
- **Schema**（`references/schemas.md`）：
  ```json
  {
    "skill_name": "example-skill",
    "evals": [
      {
        "id": 1,
        "prompt": "User's task prompt",
        "expected_output": "Description of expected result",
        "files": ["evals/files/sample1.pdf"],
        "expectations": ["The output includes X"]
      }
    ]
  }
  ```
- **特点**：自然语言 expectations，无结构化断言类型。

### 2.2 SkillsBench

- **位置**：**任务目录本身即 eval case**，无独立 eval-set 文件：
  ```
  tasks/<task-id>/
  ├── instruction.md      # ← prompt
  ├── task.toml          # ← 配置（超时、资源）
  ├── tests/test_outputs.py  # ← 断言
  └── environment/       # ← 输入 + 运行环境
  ```
- **批量配置**：BenchFlow SDK 使用 YAML 文件定义 benchmark：
  ```yaml
  tasks_dir: .ref/skillsbench/tasks
  agent: claude-agent-acp
  model: zai/glm-5.1
  environment: daytona
  concurrency: 8
  exclude:
    - scheduling-email-assistant
  ```
- **特点**：约定优于配置，扫描目录下所有 task，用 `exclude` 排除。

### 2.3 promptfoo（Bourbon 当前方案）

- **位置**：`promptfooconfig.yaml`（项目根目录）
- **特点**：显式定义 `tests[]` + `assert[]`，断言类型丰富（contains、regex、javascript、python、llm-rubric）。

---

## 三、信任悖论：The Problem of the Criterion

### 3.1 悖论的结构

在分析 SkillsBench 时，我们发现了一个深层认识论难题：

```
你想相信 SkillsBench 对 agent 的评分
    ↓
这要求 SkillsBench 里的 skills 确实能带来提升（skill delta > 0）
    ↓
要验证 skills 是否有效，需要跑 with/without 对比实验
    ↓
但那个对比实验的"正确结论"又依赖于你相信这些 skills 是好的
    ↓
循环论证（circularity）
```

换句话说：如果 SkillsBench 里的 skills 本身不够好，那它测量的"agent 使用 skill 的能力"就毫无意义；但要验证 skills 好不好，你又需要一个比 SkillsBench 更可信的外部评估——这就陷入了**无限后退**或**循环论证**。

### 3.2 相关术语

| 术语 | 定义 | 适用性 |
|------|------|--------|
| **The Problem of the Criterion**（标准问题）| 要知道什么是真的，需要标准；要知道标准是否正确，又需要知道什么是真的。 | **最贴切**——直接描述评估标准的自我依赖 |
| **Circularity / Circular Validation**（循环验证）| 用 A 证明 B，但 B 的正确性又预设了 A 的可靠性。 | **高度贴切**——描述技能评估中的逻辑循环 |
| **Meta-Evaluation Problem**（元评估问题）| 谁来评测评测器？（Who evaluates the evaluators?） | **贴切**——ML 评估领域的常用表述 |
| **Ground Truth Problem**（基准真值问题）| 没有外部客观真值时，如何建立可信基准。 | **相关**——skills 是否"真的好"缺乏绝对真值 |
| **Construct Validity Crisis**（构念效度危机）| 你的 benchmark 是否真的能测量你声称测量的 construct。 | **相关**——SkillsBench 声称测"skill utilization"，但如果 skills 本身不行，construct 就崩塌了 |

### 3.3 现实解决方案

学术界/工业界处理标准问题的常用策略：

1. **Predictive Validity（预测效度）**
   - 不问"skill 好不好"，问"benchmark 分数能否预测真实场景表现"。
   - 如果 SkillsBench 高分 → 实际用户满意度也高，则 benchmark 可信。
   - **缺点**：延迟验证，需要时间积累真实数据。

2. **Convergent Validity（聚合效度）**
   - 用多个独立评估方式看是否收敛到同一结论。
   - 例如：promptfoo 测 + 人工评 + A/B test 用户反馈，三者一致 → 增加信任。

3. **Expert Judgment as Anchor（专家判断锚定）**
   - SkillsBench 要求 `instruction.md` 和 `solve.sh` 人工编写，用**领域专家**作为外部真值来源打破循环。
   - 专家不参与被测循环，其判断不构成循环论证。

4. **Pragmatic Success（实用主义）**
   - 不纠结哲学上的绝对可信，只看"用它做决策，结果好不好"。

---

## 四、对 Bourbon 项目的启示

### 4.1 分层验证架构

Bourbon 的 eval 框架可以采用三层验证模型，避免单一评估方式的信任危机：

```
Layer 1: Fast Regression（快速回归）
    └── promptfoo 程序化断言（contains、regex、javascript）
    └── 每次代码提交自动运行
    
Layer 2: Calibration Review（校准评审）
    └── 人工 review agent 输出样本
    └── 周期性地验证 Layer 1 的断言是否仍然合理
    
Layer 3: Predictive Validation（预测效度验证）
    └── 收集真实用户反馈 / 任务成功率
    └── 与 benchmark 分数做相关性分析
```

### 4.2 关键设计原则

1. **Baseline 锚定必须独立**
   - with-skill 和 without-skill 的验证方式应有所不同（如 baseline 用人工抽查，with-skill 用程序化断言），避免同一评估系统同时验证自己和被测对象。

2. **Skill Delta 是核心指标**
   - 和 SkillsBench 一样，Bourbon 的 eval 不应只测"agent 能不能完成任务"，而应测"skill 带来了多少提升"。
   - 没有 delta 的 skill 评估是没有意义的。

3. **透明声明而非隐藏假设**
   - 像 SkillsBench 那样，公开每个 task/skill 的 with/without 数据，让社区参与判断评估是否有效。
   - 隐藏评估假设 → 信任一旦崩塌无法修复。

4. **确定性断言优先，LLM-rubric 兜底**
   - 遵循 SkillsBench 的哲学：能用代码验证的，绝不用 LLM 评判。
   - LLM-rubric 仅用于"无法程序化验证"的主观维度（如回答语气、解释清晰度）。

---

## 五、结论

skill-creator 和 SkillsBench 代表了评估设计的两个极端：

- **skill-creator**：LLM-centric，追求速度，牺牲可复现性。
- **SkillsBench**：Engineering-centric，追求可信，牺牲设计速度。

而 Bourbon 作为通用 agent 平台，其 eval 框架需要**根据场景选择合适的位置**：
- Skill 开发迭代期 → 借鉴 skill-creator 的快速反馈
- Skill 发布/回归期 → 借鉴 SkillsBench 的确定性验证
- 整个生命周期 → 警惕标准问题，建立多层验证体系

最终意识到评估设计的循环性（"谁来评估评估器"），是从**工具使用者**转向**评估设计者**的临界点——这个意识比任何具体技术决策都重要。
