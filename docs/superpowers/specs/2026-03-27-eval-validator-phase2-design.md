# Agent Eval Validator Phase 2 设计文档

**日期:** 2026-03-27
**状态:** 待批准
**前置:** [Phase 1 设计文档](2026-03-26-agent-eval-validator-design.md)

---

## 1. 设计目标

### 1.1 问题陈述

Phase 1 搭建了完整的 Generator-Evaluator 管道（Artifact → Subprocess → Report → Runner 集成），但 evaluator 内部是硬编码模拟：每个 dimension 固定返回 8.5 分，`reasoning="Phase 1 simulation"`。

这意味着验证层虽然结构上存在，但不产生任何真实的评估信号。

### 1.2 Phase 2 目标

将模拟替换为真实的 LLM-based 评估：

1. **在 evaluator subprocess 内实例化完整 Bourbon Agent** — 具备工具调用能力，可以读文件、搜索代码、分析 workspace
2. **每个 dimension 独立调用 `agent.step()`** — correctness 和 quality 各自一轮 agent 对话，互不干扰
3. **通过 `submit_evaluation` tool 收集结构化结果** — LLM 通过 tool call 提交评分 JSON，避免文本解析
4. **自定义 evaluator system prompt** — 明确 agent 角色为评审者，而非代码助手
5. **利用现有 sandbox 机制** — evaluator agent 继承 bourbon 的沙箱隔离，完整工具集在 sandbox 约束下可用

### 1.3 非目标

1. **Agent 核心代码仅做最小改动** — 仅给 `Agent.__init__` 添加可选的 `system_prompt` 参数，不改变现有逻辑
2. **不修改 Artifact / Report 数据模型** — Phase 1 的结构保持不变
3. **不修改 runner 集成逻辑** — `_run_validation()` 不需要变化
4. **不实现规则引擎 fast-path** — 未来可选优化，不在本次范围内
5. **不做并行 dimension 评估** — 保持串行，简化实现

---

## 2. 架构设计

### 2.1 整体流程

```
EvaluatorAgentRunner.run()  (subprocess 入口)
  │
  ├── 加载 OutputArtifact
  ├── 创建 Bourbon Agent (evaluator system prompt + sandbox + 完整工具集 + submit_evaluation tool)
  │
  ├── Dimension: correctness
  │   ├── agent.step("评估 correctness，使用 eval-correctness skill 分析 artifact")
  │   ├── Agent loop: LLM → skill("eval-correctness") → Read/Grep 分析 workspace → submit_evaluation()
  │   └── 从 submit_evaluation tool input 提取 JSON → ValidationDimension
  │
  ├── Dimension: quality
  │   ├── agent.step("评估 quality，使用 eval-quality skill 分析 artifact")
  │   ├── Agent loop: LLM → skill("eval-quality") → Read/Grep 分析 workspace → submit_evaluation()
  │   └── 从 submit_evaluation tool input 提取 JSON → ValidationDimension
  │
  ├── 汇总 → ValidationReport
  └── 保存 report.json
```

### 2.2 关键变化对比

| 组件 | Phase 1 | Phase 2 |
|------|---------|---------|
| `run_evaluator_agent()` | 硬编码 score=8.5 | 实例化 Agent，逐 dimension 调用 step() |
| `submit_evaluation` tool | 不存在 | 新增，接受结构化 JSON，触发 loop 终止 |
| Evaluator system prompt | 不存在 | 新增，定义评审者角色和输出规范 |
| eval-correctness SKILL.md | Placeholder | 完整评估指令和评分标准 |
| eval-quality SKILL.md | Placeholder | 完整评估指令和评分标准 |
| Agent 实例化 | 不涉及 | subprocess 内部创建，workdir=artifact workspace |

### 2.3 不变的部分

- `OutputArtifact` / `ArtifactBuilder` — 生成侧不变
- `ValidationReport` / `ValidationDimension` — 数据模型不变
- `EvaluatorAgentRunner.run()` 的 subprocess 启动机制 — CLI 参数传递不变
- `evals/runner.py` 的 `_run_validation()` — 集成点不变
- `install_skills.py` — hermetic 安装机制不变

---

## 3. 核心组件设计

### 3.1 `submit_evaluation` Tool

**用途：** 让 evaluator agent 的 LLM 通过 tool call 提交结构化评估结果，替代从自由文本中解析 JSON。

**注册方式：** 仅在 evaluator subprocess 内注册到 ToolRegistry（全局 singleton）。由于 subprocess 是独立进程，注册不会污染主进程的 registry。在 `run_evaluator_agent()` 中显式 import `submit_tool` 模块触发注册，早于 Agent 实例化。

**Capability 声明：** 使用 `required_capabilities=[]`（空列表），因为 `submit_evaluation` 不属于任何现有 capability 类别（file_read/write/exec/net/skill/mcp），且仅在 evaluator 上下文中使用。

**Input Schema:**

```json
{
  "type": "object",
  "properties": {
    "score": {
      "type": "number",
      "description": "评分 0-10",
      "minimum": 0,
      "maximum": 10
    },
    "reasoning": {
      "type": "string",
      "description": "评分理由，说明为什么给出这个分数"
    },
    "evidence": {
      "type": "array",
      "items": {"type": "string"},
      "description": "支撑评分的具体证据（代码片段、文件路径、行为观察等）"
    },
    "suggestions": {
      "type": "array",
      "items": {"type": "string"},
      "description": "改进建议"
    },
    "breakdown": {
      "type": "object",
      "description": "可选，细分指标的评分"
    }
  },
  "required": ["score", "reasoning", "evidence"]
}
```

**结果捕获机制：** 使用模块级变量 + 闭包模式。`submit_tool.py` 内定义模块级 `_evaluation_result: dict = {}`，handler 函数直接写入该变量。`run_evaluator_agent()` 通过 `from evals.validator.submit_tool import get_result, clear_result` 读取和清空结果。

```python
# evals/validator/submit_tool.py 核心模式
_evaluation_result: dict = {}

def _handle_submit(score, reasoning, evidence, suggestions=None, breakdown=None):
    _evaluation_result.update({"score": score, "reasoning": reasoning, ...})
    return "评估已提交。无需进一步操作。"

def get_result() -> dict:
    return dict(_evaluation_result)

def clear_result():
    _evaluation_result.clear()
```

**Loop 终止机制：** handler 返回 "评估已提交。无需进一步操作。"，引导 LLM 自然结束对话（不再发出 tool call），使 `_run_conversation_loop()` 退出。

### 3.2 Evaluator System Prompt

自定义 system prompt，替代 Agent 默认的 `_build_system_prompt()`：

```
你是一个代码评审 Agent。你的任务是评估另一个 AI Agent 的执行产出。

## 工作方式

1. 你会收到一个评估任务，指定要评估的维度和对应的 skill
2. 调用指定的 skill 获取该维度的评估标准和指南
3. 使用 Read、Glob、Grep 等工具分析 workspace 中的代码和文件
4. 参考 artifact 中的 context（prompt、success_criteria）和 output（final_output）
5. 完成分析后，调用 submit_evaluation 工具提交你的结构化评估结果

## 规则

- 你是评审者，不是开发者。不要修改任何文件
- 评分范围 0-10，基于 skill 中定义的标准
- evidence 必须引用具体的文件路径、代码行或行为观察
- 每次只评估一个维度
- 分析完成后必须调用 submit_evaluation 提交结果

## Artifact 位置

工作目录是 artifact 的根目录（包含 meta.json、context.json、output.json 和 workspace/）。
- meta.json — 执行元数据
- context.json — 任务上下文和成功标准
- output.json — Agent 的最终输出
- workspace/ — 执行后的文件快照
```

**workdir 设置：** evaluator agent 的 `workdir` 设为 `artifact_dir`（而非 `artifact_dir/workspace`），确保 agent 能同时读取 JSON 文件和 workspace 子目录，避免 sandbox 路径限制问题。

**实现方式：** 给 `Agent.__init__` 添加可选 `system_prompt` 参数（路径 A）。

### 3.3 Evaluator Skill 升级

#### eval-correctness/SKILL.md

从 placeholder 升级为完整的评估指令：

```markdown
---
name: eval-correctness
description: 评估 agent 输出是否正确完成了任务要求
metadata:
  version: "2.0"
  author: bourbon
---

# Correctness 评估指南

## 评估维度

你需要评估 agent 的产出是否正确满足了任务要求。

## 评估流程

1. 阅读 `../context.json` 中的 prompt 和 success_criteria
2. 阅读 `../output.json` 中的 final_output
3. 检查 workspace 中的文件变更是否符合预期
4. 逐条验证 success_criteria 是否被满足

## 评分标准

| 分数范围 | 含义 |
|----------|------|
| 9-10 | 所有 success_criteria 完全满足，无遗漏 |
| 7-8 | 核心标准满足，存在细微偏差 |
| 5-6 | 部分标准满足，有明显遗漏 |
| 3-4 | 少数标准满足，大量问题 |
| 0-2 | 基本未满足任务要求 |

## 输出

分析完成后，调用 submit_evaluation 提交评分。
evidence 中请引用具体的文件路径和代码行。
```

#### eval-quality/SKILL.md

```markdown
---
name: eval-quality
description: 评估代码和响应的质量、可维护性和清晰度
metadata:
  version: "2.0"
  author: bourbon
---

# Quality 评估指南

## 评估维度

评估 agent 产出的代码质量和响应质量。

## 评估流程

1. 阅读 workspace 中的代码文件
2. 评估代码结构、命名、可读性
3. 检查是否有明显的反模式或冗余
4. 评估 final_output 的清晰度和有用性

## 评分标准

| 分数范围 | 含义 |
|----------|------|
| 9-10 | 代码清晰、结构良好、无冗余、响应精准 |
| 7-8 | 整体质量好，有小的改进空间 |
| 5-6 | 能工作但有明显的质量问题 |
| 3-4 | 代码混乱或响应不清晰 |
| 0-2 | 质量极差，难以理解或维护 |

## 关注点

- 命名是否清晰表达意图
- 函数/方法长度是否合理
- 是否有不必要的复杂性
- 错误处理是否恰当
- 响应是否简洁且切题

## 输出

分析完成后，调用 submit_evaluation 提交评分。
evidence 中请引用具体的代码片段。
```

### 3.4 LLM 配置与 Skill 发现

**LLM 配置：** evaluator subprocess 通过 `ConfigManager` 加载 `~/.bourbon/config.toml` 获取 LLM API key 和 model 配置。`main()` 函数在创建 agent 前调用 `ConfigManager().load()` 获取 `Config` 对象。

**Skill 发现前置条件：** evaluator skills（eval-correctness、eval-quality）通过 `install_skills()` 复制到 `~/.bourbon/skills/`。此安装由 runner 的 `_ensure_evaluator_skills()` 在 eval 运行初期完成，早于 subprocess 启动。evaluator agent 的 `SkillScanner` 通过 user-level 路径 `~/.bourbon/skills/` 发现这些 skills。

**max_tool_rounds：** evaluator agent 使用较低的 `max_tool_rounds`（15），防止评估循环失控消耗过多 token。通过 config 覆盖或在 agent 创建后设置 `agent._max_tool_rounds = 15`。

### 3.5 `create_evaluator_agent()` 函数

```python
def create_evaluator_agent(artifact_dir: Path, system_prompt: str) -> Agent:
    """Create a Bourbon Agent configured for evaluation."""
    from bourbon.config import ConfigManager

    config = ConfigManager().load()
    # 限制 tool rounds 防止失控
    config.ui.max_tool_rounds = 15

    agent = Agent(
        config=config,
        workdir=artifact_dir,  # artifact 根目录，包含 JSON + workspace/
        system_prompt=system_prompt,
    )
    return agent
```

### 3.6 `run_evaluator_agent()` 重写

```python
def run_evaluator_agent(config: EvaluatorConfig) -> ValidationReport:
    """Run real LLM-based evaluation for each dimension."""
    # 注册 submit_evaluation tool（subprocess 内，不污染主进程）
    from evals.validator.submit_tool import clear_result, get_result  # noqa: triggers registration

    artifact = OutputArtifact.load(config.artifact_dir)

    # 创建 evaluator agent
    agent = create_evaluator_agent(
        artifact_dir=config.artifact_dir,  # 包含 JSON + workspace/
        system_prompt=EVALUATOR_SYSTEM_PROMPT,
    )

    dimensions = []
    for dimension_name in config.focus:
        dim_config = config.dimensions_config.get(dimension_name, {})
        threshold = dim_config.get("threshold", config.threshold)
        weight = dim_config.get("weight", 1.0 / len(config.focus))
        skill_name = config.dimension_to_skill.get(dimension_name)

        # 构建 step prompt
        prompt = build_evaluation_prompt(dimension_name, skill_name)

        # 清空上一轮结果，重置 agent 消息历史
        clear_result()
        agent.messages.clear()

        # 执行评估
        try:
            agent.step(prompt)
        except Exception as e:
            # agent.step() 异常时记为评估失败
            dimensions.append(
                ValidationDimension(
                    name=dimension_name, score=0.0, weight=weight,
                    threshold=threshold, skill=skill_name,
                    reasoning=f"evaluation error: {e}",
                    evidence=[], suggestions=[],
                )
            )
            continue

        # 从 submit_evaluation 结果中提取评分
        result = get_result()
        dimensions.append(
            ValidationDimension(
                name=dimension_name,
                score=result.get("score", 0.0),
                weight=weight,
                threshold=threshold,
                skill=skill_name,
                reasoning=result.get("reasoning", "no evaluation submitted"),
                evidence=result.get("evidence", []),
                suggestions=result.get("suggestions", []),
                breakdown=result.get("breakdown", {}),
            )
        )

    report = ValidationReport(
        dimensions=dimensions,
        overall_threshold=config.threshold,
        summary="phase 2 LLM-based validation",
    )
    report_path = config.artifact_dir.parent / "validation" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.save(report_path)
    return report
```

### 3.7 Agent.__init__ 改动

给 `Agent.__init__` 添加可选的 `system_prompt` 参数：

```python
def __init__(self, config, workdir=None, system_prompt=None, ...):
    ...
    self.system_prompt = system_prompt or self._build_system_prompt()
```

最小改动，不影响现有调用方。

### 3.8 Evaluation Prompt 构建

每个 dimension 的 `agent.step()` 调用需要一个明确的 user message：

```python
def build_evaluation_prompt(dimension_name, skill_name):
    return f"""请评估维度: {dimension_name}

步骤:
1. 调用 skill("{skill_name}") 获取评估标准
2. 阅读当前目录下的文件了解任务上下文:
   - context.json — 任务 prompt 和成功标准
   - output.json — Agent 的最终输出
   - meta.json — 执行元数据
3. 使用 Read、Glob、Grep 工具分析 workspace/ 目录中的代码
4. 调用 submit_evaluation 提交你的评估结果
"""
```

---

## 4. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `evals/validator/evaluator_agent.py` | **重写** | `run_evaluator_agent()` 从模拟改为真实 agent 调用 |
| `evals/validator/submit_tool.py` | **新建** | `submit_evaluation` tool 注册和 handler |
| `evals/validator/skills/eval-correctness/SKILL.md` | **重写** | 完整评估指令 |
| `evals/validator/skills/eval-quality/SKILL.md` | **重写** | 完整评估指令 |
| `src/bourbon/agent.py` | **小改** | `__init__` 支持可选 `system_prompt` 参数 |
| `tests/evals/validator/test_evaluator_agent.py` | **重写** | 测试真实 agent 调用流程 |
| `tests/evals/validator/test_submit_tool.py` | **新建** | submit_evaluation tool 单元测试 |

---

## 5. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| LLM 不调用 submit_evaluation | system prompt 和 skill 都明确要求；添加 fallback 检测——如果 step() 返回但无结果，记为 score=0 并标记 "evaluation not submitted" |
| LLM 返回无效 JSON | submit_evaluation 的 input schema 有类型约束；handler 内做 validation，无效数据返回错误让 LLM 重试 |
| Token 消耗过高 | 每个 dimension 独立 agent 对话，messages 在 dimension 之间清空；evaluator timeout 限制 |
| Subprocess 超时 | 继承 Phase 1 的 timeout 机制，EvaluatorAgentRunner 已有 timeout 参数 |
| Agent 修改 workspace 文件 | Sandbox 隔离 + system prompt 明确禁止修改 |
| agent.step() 抛异常 | try/except 包裹，异常时 score=0，记录错误信息到 reasoning |
| Dimension 间 agent 状态泄漏 | 每个 dimension 前 `messages.clear()` + `clear_result()`；已激活的 skills 保留（跨 dimension 复用是期望行为） |

---

## 6. 测试策略

1. **`submit_evaluation` tool 单元测试** — 验证 schema validation、结果存储、确认消息返回
2. **Evaluator agent 集成测试** — mock LLM 响应，验证完整流程：agent 创建 → step() → tool call → dimension 提取
3. **End-to-end 测试** — 使用真实 LLM（需要 API key），对一个简单 eval case 运行完整 validation pipeline
4. **Fallback 测试** — 模拟 LLM 不调用 submit_evaluation 的情况，验证 fallback 逻辑
5. **现有测试回归** — 确保 Phase 1 的测试不被破坏（evaluator.enabled=false 时行为不变）
