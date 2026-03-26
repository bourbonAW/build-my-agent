# Agent Eval Validator 设计文档

**日期:** 2026-03-26  
**状态:** 已批准，待实现  
**参考:** [Harness Design Philosophy](../../harness-design-philosophy.md)（本文档同目录下的设计哲学总结）

---

## 1. 设计目标

### 1.1 问题陈述

当前 Bourbon Eval 框架的验证存在以下局限性：

1. **断言的刚性限制** - 现有断言（`file_exists`, `output_contains` 等）只能验证客观事实，无法评估主观质量维度（如代码优雅性、解决方案完整性）
2. **生成与评估耦合** - Agent 在同一个对话流中既生成输出又自我判断是否完成，存在结构性偏差
3. **质量维度不可量化** - "这个实现好不好"无法通过布尔断言回答，缺乏可迭代的评分机制
4. **验证逻辑硬编码** - 新增的验证类型需要修改框架代码，无法灵活扩展

### 1.2 设计目标

基于 Harness 设计哲学（生成与评估分离、文件化交接、可量化维度），为 Eval 框架引入独立的验证层。

**分阶段实现：**
- **Phase 1 (Plumbing Only)**: 搭建完整的基础设施框架（Artifact、Report、Evaluator Agent），使用模拟技能响应验证 pipeline 工作
- **Phase 2 (Real Skills)**: 接入真实的 Bourbon Agent skill 调用，实现真正的 LLM-based 评估

本设计文档涵盖两阶段的完整架构，但 Phase 1 仅实现基础设施（带模拟响应）。

**Phase 1 目标：**
1. **生成与评估分离** - Evaluator Agent 作为独立进程验证 Generator Agent 的输出
2. **文件化交接** - 通过结构化的 Output Artifact 传递状态
3. **可量化维度** - 将"好"拆解为可测量的子指标
4. **Skill 化扩展** - 验证逻辑作为可插拔的 Evaluator Skills（Phase 1 模拟，Phase 2 真实）
5. **硬失败策略** - 验证不通过则测试用例失败
6. **项目资产** - Evaluator skills 作为项目级 hermetic assets，版本控制并保证 CI 可复现性

### 1.3 非目标（边界）

以下特性**不在 Phase 1 范围内**：

1. **真实 Skill 调用** - Phase 1 使用模拟响应，Phase 2 实现真正的 `skill()` 工具调用
2. **不替代现有断言** - 传统断言继续保留，Evaluator 验证作为增强层
3. **不实现实时验证** - 仅支持事后验证（Agent 执行完成后），不涉及执行过程中的干预
4. **不做跨用例分析** - 单次验证仅针对单个用例的输出，不做历史趋势分析或横向对比
5. **不修改 Agent 核心逻辑** - 验证层是 Eval 框架的增强，不改动 Bourbon Agent 的执行逻辑

**Phase 2 规划：**
- 真实的 Evaluator skill 调用（通过 Bourbon Agent framework）
- LLM-based 评分和推理
- 可选：规则引擎作为 fast-path 评估

---

## 2. 架构设计

### 2.1 整体流程

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Eval Runner    │────▶│  Output Artifact │────▶│ Evaluator Agent │
│  (Generator)    │     │  (JSON + files)  │     │  (独立进程)      │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                              ┌───────────────────────────┘
                              ▼
                    ┌──────────────────┐
                    │ Validation Report│
                    │ - 多维度评分      │
                    │ - 改进建议        │
                    │ - 证据引用        │
                    └────────┬─────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  用例通过/失败    │
                    │  (验证硬失败)     │
                    └──────────────────┘
```

### 2.2 核心组件

#### 2.2.1 Output Artifact（文件化交接）

每个用例执行后生成，位于临时工作目录：

```
workdir/
├── artifact/
│   ├── meta.json          # 元数据：用例ID、时间戳、token使用
│   ├── context.json       # 原始prompt、成功标准合约
│   ├── output.json        # Agent输出、工具调用记录
│   └── workspace/         # 工作目录文件快照（执行后的状态）
└── validation/
    └── report.json        # Evaluator生成的验证报告
```

**meta.json 结构:**
```json
{
  "case_id": "code-refactor-001",
  "timestamp": "2026-03-26T21:00:00Z",
  "duration_ms": 45000,
  "token_usage": {
    "input_tokens": 1200,
    "output_tokens": 800,
    "total_tokens": 2000
  },
  "generator_version": "bourbon-0.5.0"
}
```

**context.json 结构:**

包含原始任务上下文和成功标准合约，供 Evaluator Agent 参考：

```json
{
  "prompt": "Extract the sorting logic...",
  "success_criteria": [
    "新函数定义在全局作用域",
    "原代码调用新函数",
    "不改变原有行为"
  ],
  "success_criteria_formal": {
    "description": "形式化的成功标准，便于机器解析",
    "items": [
      {
        "id": "func_defined",
        "description": "新函数定义在全局作用域",
        "check_type": "pattern_match",
        "pattern": "^def\\s+\\w+\\s*\\(",
        "target": "workspace/src/utils.py"
      },
      {
        "id": "func_called",
        "description": "原代码调用新函数",
        "check_type": "semantic",
        "reference": "original_call_site"
      }
    ]
  },
  "constraints": ["使用Python", "保持类型注解"],
  "reference_files": ["original_code.py"],
  "evaluation_hints": ["重点关注函数签名是否保持兼容"]
}
```

**说明：**
- `success_criteria`: 面向人类的自然语言描述
- `success_criteria_formal`: 可选，面向机器的结构化标准
- `evaluation_hints`: 给 Evaluator 的额外指导

**output.json 结构:**
```json
{
  "final_output": "Agent的最终响应文本",
  "tool_calls": [
    {"tool": "read_file", "args": {...}, "result": "...", "timestamp": "..."},
    {"tool": "edit_file", "args": {...}, "result": "...", "timestamp": "..."}
  ],
  "errors": [],
  "exit_reason": "completed"
}
```

#### 2.2.2 Evaluator Skill 系统

**Hermetic 项目资产策略：**

Evaluator Skills 是项目级资产（与代码库版本同步），而非用户级全局状态：

```
evals/validator/skills/        # 项目级（版本控制）
├── eval-correctness/
│   └── SKILL.md              # 验证功能正确性
├── eval-quality/
│   └── SKILL.md              # 验证代码质量
└── eval-security/
    └── SKILL.md              # 可选：安全合规
         ↓ 复制/挂载到
~/.bourbon/skills/            # 运行时（CI/本地）
├── eval-correctness/
├── eval-quality/
└── eval-security/
```

**为什么项目资产？**
- **CI 可复现性**: 相同代码版本始终使用相同验证逻辑
- **版本同步**: Eval skill 更新与 eval case 更新同步 PR
- **环境无关**: 不依赖用户是否正确安装/更新全局 skills

**运行时机制:**
1. 项目 skills 在启动时复制/挂载到 `~/.bourbon/skills/`（或临时目录）
2. SkillScanner 从标准位置发现（与常规 skills 统一）
3. 用户级同名 skills 被项目级覆盖（hermetic 优先）

**Phase 1 vs Phase 2:**
- **Phase 1**: Skills 仅作为文档/合约存在，Evaluator 返回模拟响应
- **Phase 2**: Evaluator Agent 通过 `skill("eval-correctness")` 真实调用

**命名约定:**
- Evaluator skills 使用 `eval-{dimension}` 格式（如 `eval-correctness`）
- 避免子目录结构，SkillScanner 只扫描直接子目录

**SKILL.md 示例 (correctness-evaluator):**
```yaml
---
name: eval-correctness
description: Evaluate whether the agent output correctly fulfills the task requirements
metadata:
  version: "1.0"
  author: bourbon
---

# Correctness Evaluator

You are an evaluator assessing whether an AI agent's output correctly fulfills the given task.

## Evaluation Criteria

1. **Functional Completeness** (0-10): Does the solution implement all required functionality?
2. **Behavioral Correctness** (0-10): Does the solution produce correct results?
3. **Edge Case Handling** (0-10): Does the solution handle boundary conditions?

## Output Format

Return a JSON object:
```json
{
  "score": 8.5,
  "breakdown": {
    "functional_completeness": 9,
    "behavioral_correctness": 8,
    "edge_case_handling": 8
  },
  "reasoning": "Detailed explanation...",
  "evidence": ["引用具体代码片段..."],
  "suggestions": ["改进建议..."]
}
```
```

#### 2.2.3 Evaluator Agent（独立进程）

**实现:** `evals/validator/evaluator_agent.py`

- 独立 Python 进程，通过 `subprocess` 启动
- 干净的系统提示，不继承 Runner 的上下文
- 通过文件系统读取 Artifact，写入 Report
- 支持超时控制

**工作流程:**
1. 读取 `artifact/` 目录下的所有文件
2. 解析用例的 `focus` 字段（如 `["correctness", "quality"]`）
3. **单个 Agent 内部**按需调用对应 Evaluator Skills
4. 聚合各维度结果，生成最终报告
5. 写入 `validation/report.json`

**关键设计:** Evaluator 作为单一 Agent 运行，而非为每个 skill 启动独立进程。Agent 使用 `skill()` 工具动态加载验证逻辑，保持架构简洁。

#### 2.2.4 Validation Report（详细分析）

**评分规则:**

| 规则 | 说明 |
|------|------|
| `passed = score >= threshold` | 分数大于等于阈值视为通过（>=，不是 >） |
| 权重校验 | 各维度权重之和应等于 1.0，否则发出警告并自动归一化 |
| 整体通过 | `overall_passed = overall_score >= overall_threshold`，各维度独立判断是否通过 |

**维度 vs 整体通过的关系:**
- 每个维度有自己的 `passed` 字段（基于该维度的 threshold）
- 整体 `passed` 基于 `overall_score` 和 `overall_threshold` 计算
- 用例最终通过 = 传统断言通过 AND (验证未启用 OR 验证通过)

**report.json 结构:**
```json
{
  "version": "1.0",
  "timestamp": "2026-03-26T21:01:00Z",
  "evaluator_focus": ["correctness", "quality"],
  "skills_used": ["eval-correctness", "eval-quality"],
  "dimensions": [
    {
      "name": "correctness",
      "skill": "eval-correctness",
      "score": 8.5,
      "weight": 0.6,
      "threshold": 9.0,
      "passed": false,
      "breakdown": {
        "functional_completeness": 9,
        "behavioral_correctness": 8,
        "edge_case_handling": 8
      },
      "reasoning": "核心功能实现正确，但边界情况处理有遗漏。在输入为空列表时，新函数没有正确处理。",
      "evidence": [
        "文件 src/utils.py 第15行: `def sort_data(items):`",
        "缺少对 `if not items: return []` 的处理"
      ],
      "suggestions": [
        "建议添加空列表检查",
        "建议添加更多边界测试用例"
      ]
    },
    {
      "name": "quality",
      "skill": "eval-quality", 
      "score": 8.0,
      "weight": 0.4,
      "threshold": 7.0,
      "passed": true,
      "breakdown": {
        "code_clarity": 8,
        "naming_conventions": 9,
        "documentation": 7
      },
      "reasoning": "代码结构清晰，命名规范良好，但缺少函数文档字符串。",
      "evidence": ["新函数缺少 docstring"],
      "suggestions": ["为新函数添加文档字符串，描述参数和返回值"]
    }
  ],
  "overall_score": 8.3,
  "overall_threshold": 8.0,
  "passed": true,
  "summary": "功能实现基本正确，建议改进边界处理和文档"
}
```

#### 2.2.5 依赖项

| 依赖 | 说明 | 版本要求 |
|------|------|----------|
| Python | 标准库 `subprocess` 用于启动 Evaluator 进程 | 3.8+ |
| Bourbon Core | Skill 系统用于加载 Evaluator Skills | 现有版本 |
| Disk Space | Artifact 存储（工作目录快照） | 建议每用例 10MB 预留 |

#### 2.2.6 其他设计决策

**并发执行 (Phase 1):**
- Phase 1 采用**单个 Evaluator Agent** 顺序调用各 Skills
- 原因：简化架构，减少进程开销，便于调试
- Agent 内部通过 `skill()` 工具按需加载验证逻辑
- 未来可优化为 Agent 内部并行调用 Skills（异步执行，统一聚合）

**Artifact 生命周期:**
- 默认：验证完成后立即清理
- 调试模式（`--keep-artifacts`）：保留到指定目录
- CI 环境：可通过环境变量配置保留策略

**Skill 版本控制:**
- Evaluator Skills 遵循 Bourbon Skill 系统的版本管理
- 可指定 Skill 版本：`"skills": ["correctness-evaluator@1.0"]`
- 未指定版本时使用最新版本，但会记录实际使用的版本到 Report

**Skill 发现路径:**
- 用户级：`~/.bourbon/skills/evaluators/`
- 项目级：`{workdir}/.bourbon/skills/evaluators/`（优先级更高）
- 与常规 Skill 系统保持一致

**Artifact 大小限制:**
- 默认最大大小：100MB
- 自动排除模式：`[".git/", "node_modules/", "__pycache__/", "*.pyc", ".venv/", "*.log"]`
- 超过限制时：发出警告，截断大文件（保留前1000行），继续验证
- 可配置：`max_artifact_size_mb` 和 `exclude_patterns`

### 2.3 集成到 Eval Runner

修改 `evals/runner.py` 的 `run_single()` 方法：

```python
def run_single(self, case: dict, run_number: int = 1) -> EvalResult:
    # 1. 执行用例（现有逻辑）
    output = agent.step(prompt)
    
    # 2. 生成 Output Artifact
    artifact_dir = self._create_artifact(case, output, workdir)
    
    # 3. 检查是否需要独立验证
    evaluator_config = case.get("evaluator", {})
    if evaluator_config.get("enabled", False):
        # 4. 启动 Evaluator Agent 进行验证
        validation_result = self._run_evaluator(
            artifact_dir=artifact_dir,
            config=evaluator_config
        )
        
        # 5. 合并验证结果
        success = success and validation_result["passed"]
        assertion_results.extend(self._validation_to_assertions(validation_result))
```

---

## 3. 配置规范

### 3.1 用例级配置

在 test case JSON 中指定：

```json
{
  "id": "code-refactor-001",
  "name": "Extract function refactoring",
  "prompt": "Extract the sorting logic into a separate function",
  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 8.0,
    "timeout": 120,
    "dimensions": {
      "correctness": {
        "weight": 0.6,
        "threshold": 9.0
      },
      "quality": {
        "weight": 0.4,
        "threshold": 7.0
      }
    }
  },
  "assertions": [
    {"id": "file_created", "check": "file_exists:src/utils.py"}
  ]
}
```

### 3.2 全局默认配置

在 `evals/config.toml` 中：

```toml
[evaluator]
enabled = false  # 默认不启用，需要显式在用例中开启
default_threshold = 8.0
default_timeout = 60
max_artifact_size_mb = 100  # Artifact 大小限制

[evaluator.exclude_patterns]
patterns = [".git/", "node_modules/", "__pycache__/", "*.pyc", ".venv/"]

[evaluator.default_dimensions]
correctness = { weight = 0.7, threshold = 8.0 }
quality = { weight = 0.3, threshold = 7.0 }

[evaluator.dimension_to_skill]
# 维度到 Skill 的默认映射（使用 eval- 前缀）
correctness = "eval-correctness"
quality = "eval-quality"
security = "eval-security"
# 可扩展自定义映射
# custom_dim = "my-custom-evaluator"
```

---

## 4. 错误处理

### 4.1 Evaluator Agent 失败

| 场景 | 处理策略 |
|------|----------|
| Evaluator 进程崩溃 | 标记验证失败，记录错误信息 |
| Evaluator 超时 | 标记验证失败，报告超时 |
| 无效的报告格式 | 标记验证失败，报告解析错误 |
| Skill 加载失败 | 跳过该维度，继续其他验证 |

### 4.2 风险分级

| 操作 | 风险等级 | 策略 |
|------|----------|------|
| 启动 Evaluator 子进程 | LOW | 超时保护，异常捕获 |
| 读取 Artifact 文件 | LOW | 文件存在性检查 |
| 写入 Report | LOW | 原子写入，备份旧文件 |
| 清理临时目录 | MEDIUM | 确认目录归属后再删除 |

---

## 5. 可观测性与指标

### 5.1 内置指标

验证框架自动收集以下指标：

| 指标 | 类型 | 说明 |
|------|------|------|
| `evaluator_duration_ms` | Histogram | Evaluator 执行耗时分布 |
| `validation_score` | Histogram | 各维度评分分布 |
| `evaluator_skill_usage` | Counter | 各 Skill 使用频次 |
| `validation_pass_rate` | Gauge | 验证通过率 |
| `artifact_size_bytes` | Histogram | Artifact 大小分布 |

### 5.2 日志输出

```
[EVALUATOR] Starting validation for case=code-refactor-001
[EVALUATOR] Focus dimensions: ['correctness', 'quality']
[EVALUATOR] Loading skill: correctness-evaluator... score=8.5, threshold=9.0, passed=false
[EVALUATOR] Loading skill: quality-evaluator... score=8.0, threshold=7.0, passed=true
[EVALUATOR] Overall: score=8.3, threshold=8.0, passed=true, duration=2345ms
[EVALUATOR] Validation completed
```

### 5.3 Report 元数据

Validation Report 自动包含遥测信息：

```json
{
  "telemetry": {
    "evaluator_version": "1.0.0",
    "focus_dimensions": ["correctness", "quality"],
    "skills_invoked": ["correctness-evaluator@1.0", "quality-evaluator@1.0"],
    "duration_ms": 2345,
    "token_usage": {"input": 2000, "output": 500}
  }
}
```

---

## 6. 测试策略

### 6.1 单元测试

- `test_artifact_creation.py` - 验证 Artifact 生成
- `test_evaluator_agent.py` - 验证 Evaluator 进程管理
- `test_report_parsing.py` - 验证报告解析

### 6.2 集成测试

- 完整流程：用例执行 → Artifact 生成 → Evaluator 验证 → 结果合并
- 多种 Skill 组合的验证流程
- 失败场景的处理

### 6.3 Eval Skills 测试

每个 Evaluator Skill 应有对应的测试用例：

```json
{
  "id": "evaluator-correctness-test",
  "name": "Test correctness evaluator",
  "prompt": "Create a simple function that...",
  "evaluator": {
    "enabled": true,
    "focus": ["correctness"],
    "threshold": 9.0
  }
}
```

---

## 7. 实现优先级

### 7.1 Phase 1: 基础架构
1. Output Artifact 生成 (`artifact.py`)
2. Evaluator Agent 进程管理 (`evaluator_agent.py`)
3. Runner 集成

### 7.2 Phase 2: Evaluator Skills
1. `correctness-evaluator` Skill
2. `quality-evaluator` Skill
3. Skill 发现与加载机制

### 7.3 Phase 3: 报告与可视化
1. Validation Report 生成
2. 报告集成到 HTML/Markdown 输出
3. 历史对比分析

---

## 8. 附录

### 8.1 文件结构

```
evals/
├── runner.py              # 修改：集成验证流程
├── validator/
│   ├── __init__.py
│   ├── artifact.py        # Output Artifact 生成与管理
│   ├── evaluator_agent.py # Evaluator Agent 进程管理
│   ├── report.py          # Validation Report 解析与合并
│   └── skills/            # 内置 Evaluator Skills
│       ├── correctness/
│       │   └── SKILL.md
│       └── quality/
│           └── SKILL.md
└── cases/
    └── example.json       # 示例用例配置
```

### 8.2 参考实现

- Harness Design Philosophy: `docs/harness-design-philosophy.md`
- 现有 Runner: `evals/runner.py`
- Skill 系统: `src/bourbon/skills.py`

---

**批准人:** whf  
**批准日期:** 2026-03-26
