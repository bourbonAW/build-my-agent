# Eval-Agent 校准用例设计文档

**日期:** 2026-03-30
**状态:** 待批准
**前置:** [Phase 2 设计文档](2026-03-27-eval-validator-phase2-design.md)

---

## 1. 设计目标

### 1.1 问题陈述

Phase 2 完成了真实的 LLM-based evaluator agent，但目前仅有一个冒烟测试 (`validator-smoke/real-evaluator.json`) 来验证整条管道。这个冒烟测试验证的是 **管道能跑通**，而非 **评分是否准确**。

我们需要 **校准用例（calibration cases）** — 即预构建好的 artifact（已知 workspace 内容 + 已知预期评分范围），用来验证 eval-agent 的判断准确性。

### 1.2 目标

1. **校准集（Calibration Set）** — 验证 eval-agent 对 "明确好" 和 "明确差" 的 artifact 能给出合理评分
2. **对抗性测试（Adversarial）** — 验证 eval-agent 能识别 "看起来对但有 bug" 的实现
3. **多维度区分力（Multi-dimension Discrimination）** — 验证 eval-agent 在 correctness 和 quality 上能给出不同的分数

三个目标通过 **变体（variant）** 渐进覆盖：每道题目构造 Gold / Buggy / Correct-but-messy 三个变体。

### 1.3 题目来源

- **代码生成**：取自 [OpenAI HumanEval](https://github.com/openai/human-eval)（MIT 协议），社区标准数据集
- **逻辑推理**：经典约束推理问题，有唯一正确解

### 1.4 非目标

1. **不修改 runner 核心逻辑** — 校准用例通过现有 evaluator 管道运行，只新增 `expected_scores` 的校验断言
2. **不追求大规模覆盖** — 首批 2 题 × 3 变体 = 6 个 case，目的是验证方法可行
3. **不要求评分精确匹配** — 验证的是评分落在预期区间内，而非精确到某个数字

---

## 2. 架构设计

### 2.1 核心思路：Pre-built Artifact

与普通 eval case 的关键区别：**校准用例不需要运行 agent**。workspace 是预构建的，直接输入给 evaluator subprocess。

```
普通 eval case:
  prompt → Agent.step() → workspace → ArtifactBuilder → Evaluator → score

校准用例:
  pre-built artifact (fixtures/) → Evaluator → score → compare with expected_scores
```

### 2.2 Artifact 目录嵌套约定

**重要：** 现有 `EvaluatorAgentRunner.run()` 假设 `artifact_dir` 嵌套在某个父目录下：

- `artifact_dir.parent / "evaluator_config.json"` — 写入评估配置
- `artifact_dir.parent / "validation" / "report.json"` — 写入评估报告

在正常管道中，`ArtifactBuilder` 产出 `workdir/artifact/`，所以 `artifact_dir.parent = workdir`。

校准用例的 fixture 必须遵循同样的嵌套：

```
fixtures/calibration-below-zero-gold/
  artifact/              ← artifact_dir 指向这里
    context.json
    output.json
    meta.json
    workspace/
      solution.py
      test_solution.py
```

`_run_calibration_case()` 设置 `artifact_dir = workdir / "artifact"`。

### 2.3 流程

```
runner 加载 calibration case
  ↓
_setup_workspace() 从 fixtures/ 复制预构建目录（含 artifact/ 子目录）
  ↓
跳过 Agent.step()（无 prompt 执行）
  ↓
artifact_dir = workdir / "artifact"
  ↓
EvaluatorAgentRunner(artifact_dir) 启动 evaluator subprocess
  ↓
获取 ValidationReport → 对比 expected_scores
  ↓
每个维度：actual_score ∈ [expected_min, expected_max] → pass/fail
```

### 2.4 Case JSON 新字段

在现有 `evaluator` 配置块中新增 `expected_scores` 和 `pre_built_artifact`：

```json
{
  "id": "calibration-below-zero-gold",
  "name": "Calibration: below_zero (Gold)",
  "category": "calibration",
  "subcategory": "coding",
  "difficulty": "easy",
  "description": "Gold variant: perfect implementation of HumanEval/3 below_zero",

  "pre_built_artifact": true,
  "context": {
    "workdir": "fixtures/calibration-below-zero-gold"
  },

  "assertions": [],

  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 7.0,
    "timeout": 120,
    "dimensions": {
      "correctness": { "weight": 0.7, "threshold": 8.0 },
      "quality": { "weight": 0.3, "threshold": 6.0 }
    },
    "success_criteria": [
      "Function below_zero correctly detects when balance goes below zero",
      "Function returns True for [1, 2, -4, 5] and False for [1, 2, 3]",
      "All test cases pass"
    ],
    "evaluation_hints": [
      "Check workspace/solution.py for the implementation",
      "Run the test assertions mentally against the code"
    ],
    "expected_scores": {
      "correctness": { "min": 9, "max": 10 },
      "quality": { "min": 8, "max": 10 }
    }
  }
}
```

### 2.5 Runner 修改

在 `run_single()` 中，当 `case.get("pre_built_artifact")` 为 true 时：

1. **跳过 `Agent.step()`** — 不执行 agent，workspace 已就绪
2. **直接构建 artifact** — 从 fixture 目录中的 `context.json` / `output.json` / `workspace/` 组装
3. **运行 evaluator** — 与正常流程一致
4. **校验 expected_scores** — 新增断言：每个维度的实际评分是否在预期范围内

新增的校验逻辑（在 `_run_validation()` 返回后）：

```python
expected_scores = evaluator_config.get("expected_scores", {})
for dim_name, expected in expected_scores.items():
    actual = next(
        (d for d in report.dimensions if d.name == dim_name), None
    )
    if actual is None:
        assertion_results.append({
            "id": f"calibration_{dim_name}",
            "text": f"{dim_name} score in expected range [{expected['min']}, {expected['max']}]",
            "passed": False,
            "evidence": f"dimension '{dim_name}' not found in evaluation report",
        })
    else:
        in_range = expected["min"] <= actual.score <= expected["max"]
        assertion_results.append({
            "id": f"calibration_{dim_name}",
            "text": f"{dim_name} score in expected range [{expected['min']}, {expected['max']}]",
            "passed": in_range,
            "evidence": f"actual={actual.score:.1f}, expected=[{expected['min']}, {expected['max']}]",
        })
```

---

## 3. 题目设计

### 3.1 题目 1：代码生成 — `below_zero`（HumanEval/3）

**来源：** OpenAI HumanEval，task_id `HumanEval/3`

**题目描述：** 给定一个存款/取款操作列表，检测银行账户余额是否在某一时刻降到零以下。

**Prompt（存入 context.json）：**

```
Implement the function below_zero that detects if a bank account balance
falls below zero during a series of deposit/withdrawal operations.

The account starts at zero balance. Return True if balance goes below zero
at any point, False otherwise.

def below_zero(operations: List[int]) -> bool:
    ...

Examples:
  below_zero([1, 2, 3]) → False
  below_zero([1, 2, -4, 5]) → True
```

**Success Criteria：**
1. 函数签名为 `below_zero(operations: List[int]) -> bool`
2. 空列表返回 False
3. `[1, 2, -4, 5]` 返回 True
4. `[1, 2, -3, 1, 2, -3]` 返回 False（最低余额为 0，不低于零）
5. 实现逻辑正确处理累积余额

#### 变体 A: Gold（完美实现）

**workspace/solution.py:**
```python
from typing import List


def below_zero(operations: List[int]) -> bool:
    """Detect if bank account balance falls below zero.

    Args:
        operations: List of deposit (positive) and withdrawal (negative) amounts.

    Returns:
        True if balance goes below zero at any point, False otherwise.
    """
    balance = 0
    for op in operations:
        balance += op
        if balance < 0:
            return True
    return False
```

**workspace/test_solution.py:**
```python
from solution import below_zero


def test_empty():
    assert below_zero([]) == False

def test_all_positive():
    assert below_zero([1, 2, 3]) == False

def test_goes_below():
    assert below_zero([1, 2, -4, 5]) == True

def test_touches_zero():
    assert below_zero([1, 2, -3, 1, 2, -3]) == False

def test_immediate_negative():
    assert below_zero([-1, 2, 3]) == True

def test_deep_negative():
    assert below_zero([1, -1, 2, -2, 5, -5, 4, -5]) == True
```

**output.json 的 final_output：**
```
I've implemented the below_zero function in solution.py with a simple
accumulator pattern. The function tracks the running balance and returns
True as soon as it drops below zero. All test cases pass.
```

**预期评分：** correctness [9, 10], quality [8, 10]

#### 变体 B: Buggy（逻辑错误）

**workspace/solution.py:**
```python
from typing import List


def below_zero(operations: List[int]) -> bool:
    """Check if balance goes below zero."""
    balance = 0
    for op in operations:
        balance += op
    if balance < 0:
        return True
    return False
```

**Bug 说明：** `if balance < 0` 在循环外部 — 只检查最终余额，不检查中间状态。对于 `[1, 2, -4, 5]` 返回 False（最终余额为 4），但应该返回 True（中间余额降到 -1）。

**output.json 的 final_output：**
```
Implemented below_zero. The function sums all operations and checks
if the final balance is negative.
```

**预期评分：** correctness [1, 4], quality [2, 5]

#### 变体 C: Correct-but-messy（正确但质量差）

**workspace/solution.py:**
```python
from typing import List
import sys
import os

def below_zero(operations: List[int]) -> bool:
    # this function checks stuff
    x = 0  # balance
    flag = False  # did we go below?
    lst = list(operations)  # make a copy just in case
    i = 0
    while i < len(lst):
        val = lst[i]
        x = x + val
        if x < 0:
            flag = True
            break  # found it
        else:
            pass  # do nothing
        i = i + 1
    if flag == True:
        return True
    else:
        return False
```

**质量问题：**
- 无用的 `import sys, os`
- 单字母变量名 `x`, `i`, `val`
- 不必要的 `list()` 拷贝
- `while` 循环代替简单的 `for`
- `flag == True` 反模式
- `if flag: return True else: return False` 冗余
- 无意义注释 `# do nothing`, `# this function checks stuff`
- `pass` 在 else 分支中无意义

**output.json 的 final_output：**
```
ok so i wrote the function. it works i think. it goes through all the
numbers and keeps track. let me know if u need anything else
```

**预期评分：** correctness [7, 9], quality [2, 4]

---

### 3.2 题目 2：逻辑推理 — 约束推理问题

**题目描述：** 经典逻辑推理，通过排除法确定唯一解。

**Prompt（存入 context.json）：**

```
Solve the following logic puzzle and write your solution to solution.md:

Three friends — Alice, Bob, and Carol — each own exactly one pet:
a cat, a dog, and a fish (one pet per person, no repeats).

Clues:
1. Alice does not own the cat.
2. Bob does not own the dog.
3. Carol does not own the cat.

Determine who owns which pet. Show your reasoning step by step.
```

**Success Criteria：**
1. 正确结论：Alice→dog, Bob→cat, Carol→fish
2. 推理过程展示了排除法步骤
3. 解答写入 solution.md 文件

#### 变体 A: Gold（完美推理）

**workspace/solution.md:**
```markdown
# Logic Puzzle Solution

## Given
- Three friends: Alice, Bob, Carol
- Three pets: cat, dog, fish
- Each person owns exactly one pet

## Reasoning

**Step 1: Apply Clue 1 and 3**
- Alice does not own the cat (Clue 1)
- Carol does not own the cat (Clue 3)
- Therefore, Bob owns the cat (only remaining option)

**Step 2: Apply Clue 2**
- Bob does not own the dog (Clue 2) — consistent, since Bob owns the cat
- Remaining pets for Alice and Carol: dog and fish

**Step 3: Determine remaining assignments**
- Alice cannot own the cat (already assigned to Bob)
- No constraint prevents Alice from owning the dog
- Therefore: Alice owns the dog, Carol owns the fish

## Answer

| Person | Pet  |
|--------|------|
| Alice  | Dog  |
| Bob    | Cat  |
| Carol  | Fish |
```

**output.json 的 final_output：**
```
I solved the logic puzzle using elimination. The key insight is that
clues 1 and 3 together force Bob to own the cat, which then determines
the rest. Full solution written to solution.md.
```

**预期评分：** correctness [9, 10], quality [9, 10]

#### 变体 B: Buggy（推理错误）

**workspace/solution.md:**
```markdown
# Solution

Alice doesn't have a cat, so she has a dog.
Bob doesn't have a dog, so he has a fish.
Carol doesn't have a cat, so she has a cat... wait.

Actually, let me try again.
Alice has a fish.
Bob has a dog.
Carol has a cat.

The answer is Alice=fish, Bob=dog, Carol=cat.
```

**Bug 说明：**
- 结论错误（Bob=dog 违反 Clue 2, Carol=cat 违反 Clue 3）
- 推理过程自我矛盾且中途放弃
- 第二次尝试没有任何推理支撑

**output.json 的 final_output：**
```
Solved it. Alice has fish, Bob has dog, Carol has cat.
```

**预期评分：** correctness [1, 3], quality [2, 5]

#### 变体 C: Correct-but-messy（正确但质量差）

**workspace/solution.md:**
```markdown
ok so lets figure this out

alice no cat, bob no dog, carol no cat

so like if alice cant have cat and carol cant have cat then bob has to have cat right? yeah that makes sense

and then bob cant have dog but he already has cat so thats fine

so alice and carol have dog and fish left. alice can have dog and carol has fish

answer: alice=dog bob=cat carol=fish

actually wait let me double check. alice no cat - she has dog, ok. bob no dog - he has cat, ok. carol no cat - she has fish, ok. yeah its right
```

**质量问题：**
- 无结构化格式
- 口语化表达，大小写不规范
- 没有清晰的步骤分隔
- 自我质疑但没有组织成连贯推理
- 最终答案格式随意

**output.json 的 final_output：**
```
figured it out, wrote to solution.md. alice gets the dog, bob gets the cat,
carol gets the fish. pretty sure thats right
```

**预期评分：** correctness [7, 9], quality [2, 4]

---

## 4. 文件结构

```
evals/
├── cases/
│   └── calibration/
│       ├── coding/
│       │   ├── below-zero-gold.json
│       │   ├── below-zero-buggy.json
│       │   └── below-zero-messy.json
│       └── reasoning/
│           ├── logic-puzzle-gold.json
│           ├── logic-puzzle-buggy.json
│           └── logic-puzzle-messy.json
├── fixtures/
│   ├── calibration-below-zero-gold/
│   │   └── artifact/
│   │       ├── context.json
│   │       ├── output.json
│   │       ├── meta.json
│   │       └── workspace/
│   │           ├── solution.py
│   │           └── test_solution.py
│   ├── calibration-below-zero-buggy/
│   │   └── artifact/
│   │       ├── context.json
│   │       ├── output.json
│   │       ├── meta.json
│   │       └── workspace/
│   │           └── solution.py
│   ├── calibration-below-zero-messy/
│   │   └── artifact/
│   │       ├── context.json
│   │       ├── output.json
│   │       ├── meta.json
│   │       └── workspace/
│   │           └── solution.py
│   ├── calibration-logic-puzzle-gold/
│   │   └── artifact/
│   │       ├── context.json
│   │       ├── output.json
│   │       ├── meta.json
│   │       └── workspace/
│   │           └── solution.md
│   ├── calibration-logic-puzzle-buggy/
│   │   └── artifact/
│   │       └── ...（同上结构）
│   └── calibration-logic-puzzle-messy/
│       └── artifact/
│           └── ...（同上结构）
└── runner.py  # 修改: 支持 pre_built_artifact 和 expected_scores
```

---

## 5. Runner 修改详情

### 5.1 `run_single()` 修改

在 `run_single()` 中，`pre_built_artifact` 为 true 时走不同路径：

```python
def run_single(self, case: dict, run_number: int = 1) -> EvalResult:
    if case.get("pre_built_artifact"):
        return self._run_calibration_case(case, run_number)
    # ... 现有逻辑不变
```

### 5.2 新增 `_run_calibration_case()`

```python
def _run_calibration_case(self, case: dict, run_number: int = 1) -> EvalResult:
    """Run a pre-built artifact through the evaluator only (no agent execution)."""
    start = time.time()
    workdir = self._setup_workspace(case)  # 从 fixture 复制

    try:
        # fixture 内含 artifact/ 子目录，与 ArtifactBuilder 产出结构一致
        artifact_dir = workdir / "artifact"
        if not artifact_dir.exists():
            raise RuntimeError(
                f"Pre-built artifact not found: {artifact_dir}. "
                "Fixture must contain an artifact/ subdirectory."
            )

        evaluator_config = case.get("evaluator", {})
        focus = evaluator_config.get("focus", ["correctness"])
        dimensions_config = dict(evaluator_config.get("dimensions", {}))
        # 合并全局默认维度配置
        for dim_name, dim_config in (
            self.config.get("evaluator", {}).get("default_dimensions", {}).items()
        ):
            dimensions_config.setdefault(dim_name, dim_config)

        report_path = EvaluatorAgentRunner(
            artifact_dir=artifact_dir,
            focus=focus,
            threshold=evaluator_config.get("threshold", 8.0),
            timeout=evaluator_config.get("timeout", 120),
            dimensions_config=dimensions_config,
            dimension_to_skill=self.config.get("evaluator", {}).get("dimension_to_skill", {}),
        ).run()
        report = ValidationReport.load(report_path)

        assertion_results = report.to_assertions()

        # 校准断言：验证评分在预期范围内
        expected_scores = evaluator_config.get("expected_scores", {})
        for dim_name, expected in expected_scores.items():
            actual = next(
                (d for d in report.dimensions if d.name == dim_name), None
            )
            if actual is None:
                assertion_results.append({
                    "id": f"calibration_{dim_name}",
                    "text": f"{dim_name} score in [{expected['min']}, {expected['max']}]",
                    "passed": False,
                    "evidence": f"dimension '{dim_name}' not found in evaluation report",
                })
            else:
                in_range = expected["min"] <= actual.score <= expected["max"]
                assertion_results.append({
                    "id": f"calibration_{dim_name}",
                    "text": f"{dim_name} score in [{expected['min']}, {expected['max']}]",
                    "passed": in_range,
                    "evidence": f"actual={actual.score:.1f}, expected=[{expected['min']}, {expected['max']}]",
                })

        success = all(a["passed"] for a in assertion_results)
        duration = int((time.time() - start) * 1000)

        return EvalResult(
            case_id=case["id"],
            success=success,
            duration_ms=duration,
            assertions=assertion_results,
            run_number=run_number,
        )
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return EvalResult(
            case_id=case["id"],
            success=False,
            duration_ms=duration,
            error=str(e),
            run_number=run_number,
        )
    finally:
        if workdir and not os.environ.get("EVAL_KEEP_ARTIFACTS"):
            self._cleanup_workspace(workdir)
```

### 5.3 运行方式

```bash
# 只运行校准用例
uv run python evals/runner.py --category calibration

# 运行特定子类（使用 category/subcategory 语法）
uv run python evals/runner.py --category calibration/coding

# 运行全部（包含校准用例）
uv run python evals/runner.py
```

**注意：** runner 必须从 repo 根目录执行，因为 fixture 路径使用相对路径解析 `evals/fixtures/`。

---

## 6. Fixture 中 context.json / output.json / meta.json 格式

遵循现有 `ArtifactBuilder` 产出的格式：

**context.json:**
```json
{
  "prompt": "Implement the function below_zero ...",
  "success_criteria": [
    "Function below_zero correctly detects when balance goes below zero",
    "All test cases pass"
  ],
  "success_criteria_formal": [],
  "constraints": [],
  "evaluation_hints": [
    "Check workspace/solution.py for the implementation"
  ],
  "reference_files": []
}
```

**output.json:**
```json
{
  "final_output": "I've implemented the below_zero function ...",
  "tool_calls": [],
  "errors": [],
  "exit_reason": "completed"
}
```

**meta.json:**
```json
{
  "case_id": "calibration-below-zero-gold",
  "duration_ms": 5000,
  "token_usage": { "input_tokens": 1000, "output_tokens": 500 },
  "timestamp": "2026-03-30T00:00:00Z",
  "generator_version": "calibration-fixture"
}
```

---

## 7. 成功标准

### 7.1 校准准确性

| 变体 | 预期行为 |
|------|---------|
| Gold | correctness 和 quality 均高分，且在预期范围内 |
| Buggy | correctness 低分，eval-agent 能识别逻辑错误 |
| Messy | correctness 高、quality 低，两个维度有明显分差（≥3 分） |

### 7.2 失败场景（eval-agent 存在问题的信号）

- Gold 变体拿不到高分 → eval-agent 对正确实现误判
- Buggy 变体拿到高分 → eval-agent 无法识别错误
- Messy 变体两个维度评分相近 → eval-agent 缺乏维度区分力

### 7.3 运行可重复性

校准用例应该在多次运行中表现稳定。建议：
```bash
uv run python evals/runner.py --category calibration --num-runs 3
```
如果 flaky rate > 0，说明预期区间需要调宽或 eval-agent 行为不稳定。
