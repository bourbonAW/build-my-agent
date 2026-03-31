# Bourbon Eval 实施指南

本文档总结 Bourbon Eval 体系的设计与实施状态。

## 体系概览

基于 [深度研究报告](./docs/deep-research-report.md) 和 Anthropic Skill-Creator 规范设计，采用**渐进式落地策略**（P0 → P1 → P2）。

```
┌─────────────────────────────────────────────────────────────────┐
│                      EVAL ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────┤
│  P0: Minimum Viable Eval (✅ DONE)                              │
│     ├─ 15-20 个评测用例                                         │
│     ├─ 程序化断言库                                             │
│     ├─ 基础 Runner                                              │
│     └─ 配置系统                                                 │
├─────────────────────────────────────────────────────────────────┤
│  P1: Stability & Skill Eval (📋 PLANNED)                        │
│     ├─ 多次运行与方差分析 (pass^k)                              │
│     ├─ Skill 触发准确率评测                                     │
│     ├─ 并行执行与上下文隔离                                     │
│     └─ 安全红队测试集                                           │
├─────────────────────────────────────────────────────────────────┤
│  P2: CI/CD Integration (📋 PLANNED)                             │
│     ├─ GitHub Actions 工作流                                    │
│     ├─ PR 自动评测与评论                                        │
│     ├─ 门禁阈值（pass rate、regression）                        │
│     └─ 趋势看板                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 文件结构

```
evals/
├── README.md                   # 使用文档
├── config.toml                # 评测配置
├── runner.py                  # 执行器
├── validate.py                # 验证脚本
├── fixtures/                  # 测试固件
├── cases/                     # 评测用例
│   ├── code-search/           # 代码搜索 (4个用例)
│   ├── file-operations/       # 文件操作 (4个用例)
│   ├── code-analysis/         # 代码分析 (4个用例)
│   ├── safety/                # 安全评测 (4个用例)
│   └── skills/                # Skill 评测
│       └── note-vault/        # note skill 触发测试
└── assertions/                # 断言库
    ├── file_assertions.py     # 文件断言
    ├── code_assertions.py     # 代码断言
    └── security_assertions.py # 安全断言
```

## P0 已完成内容

### 1. 评测用例（5个示例）

| ID | 类别 | 名称 | 断言类型 |
|----|------|------|----------|
| code-search-001 | 代码搜索 | 搜索特定函数定义 | 程序化 + LLM judge |
| file-op-001 | 文件操作 | 读取并修改配置文件 | 程序化 |
| code-analysis-001 | 代码分析 | 分析代码中的 bug | LLM judge |
| safety-001 | 安全 | 路径穿越攻击防护 | 程序化 |
| skill-trigger-001 | Skill | note skill 触发准确率 | 触发测试 |

### 2. 断言库

**程序化断言（可自动验证）：**
- `file_exists(path)` - 文件存在
- `file_contains(path, content)` - 文件包含内容
- `file_not_contains(path, content)` - 文件不包含内容
- `json_path_equals(path, key.subkey, value)` - JSON 路径值匹配
- `code_compiles(path)` - Python 代码可编译
- `function_exists(path, name)` - 函数存在
- `no_path_traversal(path)` - 无路径穿越
- `within_workdir(path, workdir)` - 在工作目录内

**LLM Judge 断言（主观评估）：**
- 由独立 LLM 评判输出质量
- 用于开放式任务（代码分析、建议质量等）

### 3. 配置系统

```toml
[runner]
num_runs = 1              # 运行次数（P1 改为 3+）
timeout = 120             # 超时时间
isolate_context = true    # 上下文隔离

[dimensions]              # 评测维度权重
correctness = 0.4
robustness = 0.2
safety = 0.2
performance = 0.1
skill_trigger = 0.1

[gates]                   # CI 门禁阈值
min_pass_rate = 0.8
max_regression_rate = 0.05
max_flaky_rate = 0.1
```

## 快速开始

### 验证框架

```bash
npx promptfoo@latest eval --filter-pattern "Safety" --no-cache
```

### 运行评测

```bash
# 运行所有评测
npx promptfoo@latest eval

# 按描述过滤类别
npx promptfoo@latest eval --filter-pattern "Skills"

# 多次运行观测波动
npx promptfoo@latest eval --repeat 5

# 查看结果面板
npx promptfoo@latest view
```

## 关键设计决策

### 1. 产物导向 vs 输出导向

传统 Eval 只检查文本输出，Bourbon 检查：
- ✅ 文件最终状态（存在、内容、格式）
- ✅ 代码可编译、测试通过
- ✅ 环境状态变化
- ⚠️ 文本输出仅作辅助

### 2. 程序化优先

| 优先级 | 验证方式 | 示例 |
|--------|----------|------|
| 1 | 断言验证 | 文件存在、JSON 路径匹配 |
| 2 | 测试验证 | pytest 通过、mypy 无错误 |
| 3 | LLM Judge | 代码分析质量、建议合理性 |
| 4 | 人工抽检 | 复杂场景最终确认 |

### 3. A/B 对照

Skill 评测必须对比：
- **新增 skill**: with-skill vs without-skill
- **改进 skill**: new-version vs old-version snapshot

### 4. 非确定性治理

P1 阶段实现：
- 同一用例运行 3 次
- 计算 pass^k（k 次中成功的概率）
- 标记方差高的 flaky 用例

## 下一步行动

### P1 阶段（2-4 周）

1. **实现 Agent 调用接口**
   ```python
   # runner.py 中实现
   def call_agent(prompt, workdir, with_skill=None) -> AgentOutput
   ```

2. **多次运行支持**
   ```toml
   [runner]
   num_runs = 3  # 计算 pass^k
   ```

3. **Skill 触发评测自动化**
   - 构造 20-30 条 should-trigger/should-not-trigger 用例
   - 运行 3 次计算 trigger accuracy
   - 优化 skill description

4. **安全红队测试集**
   - 路径穿越（✓ 已有基础）
   - 命令注入
   - Prompt injection
   - 数据外泄尝试

### P2 阶段（4-6 周）

1. **GitHub Actions 集成**
   ```yaml
   # .github/workflows/eval.yml
   - PR 触发 smoke eval（10条）
   - 评论展示 pass rate 对比
   - 主分支门禁阈值检查
   ```

2. **报告与看板**
   - HTML 交互式报告
   - 历史趋势图表
   - 回归自动告警

## 参考

- [深度研究报告](./docs/deep-research-report.md)
- [Skill-Creator 官方文档](https://docs.anthropic.com/en/docs/claude-code/skill-creator)
- [Agent Skills 规范](https://agentskills.io/)
