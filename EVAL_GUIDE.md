# Bourbon Eval Guide

Bourbon's evaluation framework runs through [promptfoo](https://www.promptfoo.dev/).

## Architecture

```
promptfooconfig.yaml              # 日常评估入口（项目行为 + 安全 + 校准）
promptfooconfig-benchmarks.yaml  # 社区 benchmark 入口（5 个维度回归检测）
        ↓
evals/promptfoo_provider.py      # 封装 Agent.step()，返回 JSON 给 promptfoo
        ↓
evals/cases/*.yaml               # 日常测试用例
evals/benchmarks/*.yaml          # 社区 benchmark 静态子集（生成后提交）
        ↓
promptfoo assertions              # javascript, llm-rubric, contains 等
```

### Components

- **`promptfooconfig.yaml`** - 日常评估根配置，定义 provider、默认选项和测试文件引用。
- **`promptfooconfig-benchmarks.yaml`** - 社区 benchmark 专用配置，timeout 设为 180s（比日常长），repeat 3。
- **`evals/promptfoo_provider.py`** - 自定义 Python provider，运行 `Agent.step()`，返回 JSON `{text, workdir, duration_ms}`。
- **`evals/promptfoo_artifact_provider.py`** - 为 `llm-rubric` 评估提供预构建校准产物。
- **`evals/cases/`** - YAML 测试用例文件，按类别组织。
- **`evals/benchmarks/`** - 社区 benchmark 静态子集（由 loader 生成后提交，运行时不需要 HuggingFace 访问）。
- **`evals/loaders/`** - 从 HuggingFace 拉取数据集并转换为 promptfoo YAML 的脚本。
- **`evals/fixtures/`** - 预构建测试固件（校准产物、项目模板）。
- **`evals/benchmarks/BASELINES.md`** - benchmark 基线记录表。

## Quick Start

```bash
# 运行日常评估（全部）
npx promptfoo@latest eval

# 按描述文本过滤（匹配 test description，不是 metadata.category）
npx promptfoo@latest eval --filter-pattern "Skills"

# 多次迭代分析方差
npx promptfoo@latest eval --repeat 5

# 禁用缓存，强制重新运行
npx promptfoo@latest eval --no-cache

# 运行社区 benchmark（全部 5 个维度）
npx promptfoo@latest eval --config promptfooconfig-benchmarks.yaml

# 只跑某个 benchmark 维度
npx promptfoo@latest eval --config promptfooconfig-benchmarks.yaml --filter-pattern "GSM8K"

# 查看结果看板
npx promptfoo@latest view
```

## Test Categories（日常评估）

| Category | File | Description |
|----------|------|-------------|
| Calibration | `calibration.yaml` | 预构建产物 + 多维度 llm-rubric 评分 |
| Calibration Gen-Eval | `calibration-gen-eval.yaml` | LLM 生成再评估的校准流程 |
| Safety | `safety.yaml` | 安全护栏红队测试 |
| Security | `security.yaml` | 安全行为验证 |
| Sandbox | `sandbox.yaml` | 沙箱隔离测试 |
| Skills | `skills.yaml` | Skill 功能与触发准确性 |
| Code Search | `code-search.yaml` | 代码搜索结果质量 |
| File Operations | `file-operations.yaml` | 文件操作正确性 |
| General | `general.yaml` | 通用 agent 行为 |
| Validator Smoke | `validator-smoke.yaml` | Validator 冒烟测试 |

## Community Benchmarks（社区 benchmark）

通过 `promptfooconfig-benchmarks.yaml` 运行，用于多维度回归检测。

| Dimension | Benchmark | 文件 | 任务数 | Assertion 类型 | 基线阈值 |
|-----------|-----------|------|--------|----------------|---------|
| A — 代码正确性 | HumanEval | `humaneval_50.yaml` | 50 | llm-rubric（沙箱执行 + LLM 判分）| pass@1 ≥ 60% |
| B — 工具使用 | GAIA Level 1 | `gaia_level1_30.yaml` | 15* | javascript（答案字符串匹配）| pass@1 ≥ 40% |
| C — 指令遵循 | MT-Bench | `mt_bench_80.yaml` | 80 | llm-rubric（分数 ≥ 7）| 均分 ≥ 7.0 |
| D1 — 算术推理 | GSM8K | `gsm8k_50.yaml` | 50 | javascript（`####` 分隔符）| pass@1 ≥ 75% |
| D2 — 逻辑推理 | BIG-bench Hard | `bigbench_hard_100.yaml` | 100 | javascript（`Answer: (X)`）| pass@1 ≥ 55% |

> \* GAIA 原计划 30 个任务，经过滤（排除需附件、排除需 web 搜索）后实际 15 个可用任务。

### 更新 benchmark 子集

```bash
# 安装 loader 依赖
uv pip install -e ".[loaders]"

# 重新生成（各 loader 使用本地 HF 缓存，无需重新下载）
.venv/bin/python evals/loaders/load_gsm8k.py --sample 50 --seed 42 --stratify-by-steps \
    --output evals/benchmarks/gsm8k_50.yaml

.venv/bin/python evals/loaders/load_bigbench_hard.py --per-task 10 --seed 42 \
    --output evals/benchmarks/bigbench_hard_100.yaml

.venv/bin/python evals/loaders/load_humaneval.py --sample 50 --seed 42 \
    --output evals/benchmarks/humaneval_50.yaml

.venv/bin/python evals/loaders/load_mt_bench.py \
    --output evals/benchmarks/mt_bench_80.yaml

# GAIA 需要 HuggingFace 登录（gated dataset）
huggingface-cli login
.venv/bin/python evals/loaders/load_gaia.py --sample 30 --seed 42 \
    --exclude-attachments --exclude-web \
    --output evals/benchmarks/gaia_level1_30.yaml
```

### 更新 Baselines

运行完整 benchmark 后，将结果填入 `evals/benchmarks/BASELINES.md`，然后提交：

```bash
git add evals/benchmarks/BASELINES.md
git commit -m "chore(eval): update baselines after <原因>"
```

## Assertion Types

### Programmatic (javascript)

> **注意（promptfoo 0.121.3+）：**
> - 测试变量需通过 `context.vars.xxx` 访问，`vars` 在内联 JS 中**不可直接使用**
> - 返回值只能是 `boolean` 或 `number`，不能返回 `{ pass, reason }` 对象

文件和审计断言解析 provider JSON 输出以访问 `workdir`，再检查文件系统状态：

```yaml
assert:
  - type: javascript
    value: |
      const data = JSON.parse(output);
      const fs = require('fs');
      const path = require('path');
      return fs.existsSync(path.join(data.workdir, 'expected-file.py'));
```

访问测试变量：

```yaml
assert:
  - type: javascript
    value: |
      const data = JSON.parse(output);
      const match = data.text.match(/####\s*(\d+\.?\d*)/);
      if (!match) return false;
      return match[1] === String(context.vars.expected_answer);  // 用 context.vars，不是 vars
```

### LLM Judge (llm-rubric)

主观质量评估：

```yaml
assert:
  - type: llm-rubric
    value: "The response correctly identifies the bug and explains why it occurs"
```

### Text Matching

对原始 JSON 输出做子串匹配：

```yaml
assert:
  - type: contains
    value: "expected text"
  - type: not-contains
    value: "should not appear"
```

## Calibration Cases

校准使用 `evals/fixtures/` 中的预构建产物，通过 `llm-rubric` 进行多维度评分，每个维度得到独立 metric：

```yaml
assert:
  - type: llm-rubric
    value: "Evaluate correctness of the implementation..."
    metric: correctness
  - type: javascript
    value: |
      const scores = context.namedScores;
      return scores.correctness >= 0.6 && scores.correctness <= 0.9;
```

## Provider Output Contract

Agent provider 返回 JSON 编码的输出（注意字段是 `duration_ms`，不是 `duration`）：

```json
{
  "text": "Agent 的文本响应...",
  "workdir": "/tmp/eval-workspace-xxx",
  "duration_ms": 12500
}
```

- `javascript` 断言解析此 JSON 以访问 `workdir` 和文件系统
- `contains`/`not-contains` 断言对原始 JSON 字符串做子串匹配
- `llm-rubric` 断言接收原始 JSON；LLM 会自动提取 text 字段

## Configuration Options

`promptfooconfig.yaml`（日常评估）：

```yaml
evaluateOptions:
  maxConcurrency: 1    # 串行，确保工作区隔离
  repeat: 3            # 每个用例默认迭代次数
  timeoutMs: 60000     # 每个用例超时
```

`promptfooconfig-benchmarks.yaml`（社区 benchmark）：

```yaml
evaluateOptions:
  maxConcurrency: 1
  repeat: 3
  timeoutMs: 180000    # benchmark 任务更复杂，超时设为 3 分钟
```

## Fixtures

`evals/fixtures/` 中的预构建固件：

| Fixture | 用途 |
|---------|------|
| `calibration-below-zero-*` | 预构建 below_zero 实现（gold/buggy/messy） |
| `calibration-logic-puzzle-*` | 预构建逻辑谜题解答（gold/buggy/messy） |
| `python-project` | 文件操作测试用 Python 项目模板 |
| `js-project` | 文件操作测试用 JS 项目模板 |
| `malicious` | 安全测试用恶意固件 |

## Smoke Test

使用 `smoke-benchmarks.yaml` 快速验证 benchmark 流水线是否通畅（1 个用例，无需运行全量）：

```bash
npx promptfoo@latest eval --config smoke-benchmarks.yaml --no-cache
```
