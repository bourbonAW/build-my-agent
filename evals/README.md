# Bourbon Eval 体系

基于 [Skill-Creator 评测规范](https://docs.anthropic.com/en/docs/claude-code/skill-creator) 和 [深度研究报告](./deep-research-report.md) 设计的 Code Agent 评测体系。

## 设计原则

1. **产物导向**：验证文件/代码的最终状态，不只是文本输出
2. **程序化优先**：断言验证优先，LLM judge 仅作补充
3. **分层门禁**：单元测试 → 程序化断言 → 人工抽检
4. **A/B 对比**：Skill 评估采用 with-skill vs without-skill 对照

## 快速开始

```bash
# 运行所有评测
uv run python evals/runner.py

# 运行特定类别评测
uv run python evals/runner.py --category code-search

# 对比模式（with-skill vs baseline）
uv run python evals/runner.py --skill note-vault --baseline
```

## 目录结构

```
evals/
├── config.toml              # 评测配置
├── README.md               # 本文档
├── fixtures/               # 测试固件
│   ├── python-project/     # Python 项目示例
│   ├── js-project/         # JS 项目示例
│   └── malicious/          # 安全测试用例
├── cases/                  # 评测用例
│   ├── code-search/        # 代码搜索场景
│   ├── file-operations/    # 文件操作场景
│   ├── code-analysis/      # 代码分析场景
│   ├── safety/             # 安全评测
│   └── skills/             # Skill 评测
│       └── note-vault/
├── assertions/             # 断言库
│   ├── file_assertions.py
│   ├── code_assertions.py
│   └── security_assertions.py
├── runner.py               # 评测执行器
├── reporter.py             # 报告生成器（P1）
├── validator/              # 独立验证层（Phase 1）
│   ├── artifact.py         # Output Artifact 生成
│   ├── report.py           # Validation Report 模型
│   ├── evaluator_agent.py  # Evaluator 子进程入口
│   ├── install_skills.py   # 项目 skill 复制到 ~/.bourbon/skills/
│   └── skills/             # eval-correctness / eval-quality 合约
└── results/                # 评测结果（gitignore）
```

## 评测用例格式

```json
{
  "id": "case-001",
  "name": "用例名称",
  "category": "类别",
  "difficulty": "easy|medium|hard",
  "prompt": "用户输入",
  "context": {
    "workdir": "fixtures/python-project"
  },
  "setup": {
    "create_files": {...},
    "run_commands": [...]
  },
  "expected": {
    "description": "期望结果描述"
  },
  "assertions": [
    {
      "id": "assert-1",
      "type": "programmatic|llm_judge",
      "description": "断言描述",
      "check": "file_exists:output.txt"
    }
  ],
  "cleanup": {
    "remove_files": [...]
  },
  "tags": ["tag1", "tag2"]
}
```

## 断言类型

### 程序化断言

- `file_exists:path` - 文件存在
- `file_contains:path:content` - 文件包含内容
- `file_not_contains:path:content` - 文件不包含内容
- `json_path_equals:path:key.subkey:value` - JSON 路径值匹配
- `code_compiles:path` - 代码可编译
- `test_passes:path` - 测试通过

### LLM Judge 断言

用于开放式任务的质量评估，使用独立 LLM 进行评判。

## Independent Validation

Eval Runner 现在支持独立验证层，采用 Generator-Evaluator 分离：

1. Runner 正常执行 case
2. 生成 `artifact/` 快照，包括 `meta.json`、`context.json`、`output.json`、`workspace/`
3. Evaluator 子进程读取 artifact 并生成 `validation/report.json`
4. 验证断言以 `eval_*` 形式并入 case 结果

### 用例配置

```json
{
  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 8.0,
    "dimensions": {
      "correctness": { "weight": 0.6, "threshold": 9.0 },
      "quality": { "weight": 0.4, "threshold": 7.0 }
    }
  }
}
```

### Phase 1 Scope

- 当前实现是基础设施阶段
- Evaluator 会生成真实 artifact / report，并通过 subprocess 运行
- 评分仍是模拟值，后续 Phase 2 才接入真实 `skill()` 调用

### 调试

```bash
EVAL_KEEP_ARTIFACTS=1 uv run python evals/runner.py
```

### Hermetic Evaluator Skills

- 项目内 skill 资产位于 `evals/validator/skills/`
- `EvalRunner` 初始化时会把这些 skill 强制复制到 `~/.bourbon/skills/`
- 这样 SkillScanner 能按现有机制发现它们，同时保证项目版本覆盖用户版本

## 实施路线图

### P0：最小可用（当前）

- [x] 基础目录结构
- [x] 配置系统
- [x] 示例用例（15-20 个）
- [x] 基础断言库
- [x] 简单 runner

### P1：稳定性与 Skill 评测

- [ ] 多次运行与方差分析（pass^k）
- [ ] Skill 触发准确率评测
- [ ] 并行执行与上下文隔离
- [ ] 报告生成器（markdown/html）
- [ ] 安全红队测试集

### P2：CI/CD 集成

- [ ] GitHub Actions 工作流
- [ ] PR 自动评测与评论
- [ ] 门禁阈值（pass rate、regression）
- [ ] 趋势看板与回归检测
- [ ] 基准对比（A/B）

### P3：线上评测

- [ ] 真实用户采样
- [ ] 在线 A/B 实验
- [ ] 私有评测集维护
- [ ] 自动用例生成

## 关键指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| Pass Rate | 通过率 | ≥ 80% |
| Regression Rate | 回归率 | ≤ 5% |
| Flaky Rate | 不稳定率 | ≤ 10% |
| Skill Trigger Accuracy | Skill 触发准确率 | ≥ 85% |
| Avg Duration | 平均耗时 | ≤ 60s |

## 参考资源

- [Skill-Creator 官方文档](https://docs.anthropic.com/en/docs/claude-code/skill-creator)
- [Agent Skills 规范](https://agentskills.io/)
- [SWE-bench](https://www.swebench.com/)
- [τ-bench](https://github.com/sierra-research/tau-bench)
