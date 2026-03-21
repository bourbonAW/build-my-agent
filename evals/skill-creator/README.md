# Skill-Creator for Bourbon

从 Anthropic skill-creator 适配的 Skill 触发评测工具。

## 目录结构

```
eval/skill-creator/
├── SKILL.md                    # skill-creator 官方文档
├── scripts/                    # 官方脚本（需要 claude CLI）
│   ├── aggregate_benchmark.py
│   ├── run_loop.py            # description 优化循环
│   ├── run_eval.py            # 触发评测
│   └── ...
├── agents/                     # 子 agent 定义
│   ├── grader.md
│   ├── analyzer.md
│   └── comparator.md
├── references/                 # 参考资料
│   └── schemas.md
├── eval-viewer/               # 结果查看器
│   └── generate_review.py
├── eval-sets/                 # Bourbon 评测集
│   └── superpowers-trigger-eval.json
└── README.md                  # 本文件
```

## 使用方式

### 1. Skill 触发评测（Bourbon 适配版）

```bash
# 使用 Bourbon Agent 测试 skill 触发准确率
uv run python evals/trigger_eval.py \
  --skill-path .kimi/skills/superpowers/SKILL.md \
  --eval-set evals/skill-creator/eval-sets/superpowers-trigger-eval.json \
  --output evals/results/trigger_report.json
```

输出指标：
- **Accuracy**: 整体准确率
- **Precision**: 精确率（触发的正确率）
- **Recall**: 召回率（该触发的是否都触发了）
- **F1 Score**: 综合指标
- **False Positive Rate**: 误触发率

### 2. 创建新的触发评测集

参考 `eval-sets/superpowers-trigger-eval.json` 格式：

```json
[
  {
    "query": "用户输入",
    "should_trigger": true/false,
    "reason": "原因说明"
  }
]
```

建议：
- 8-10 个 should-trigger（不同表达方式）
- 8-10 个 should-not-trigger（包含 near-miss 场景）
- 覆盖 edge cases

### 3. Description 优化（需要 claude CLI）

如果你有 `claude` CLI 工具，可以使用官方脚本：

```bash
cd evals/skill-creator

# 运行 description 优化循环
python -m scripts.run_loop \
  --eval-set eval-sets/superpowers-trigger-eval.json \
  --skill-path ../../.kimi/skills/superpowers \
  --max-iterations 5
```

## 触发评测原理

```
用户 Query
    ↓
[模拟 Skill 在 available_skills 中]
    ↓
Bourbon Agent 处理
    ↓
检测是否触发 skill
    ↓
对比 should_trigger 预期
    ↓
计算 Accuracy/Precision/Recall/F1
```

## 当前限制

1. **启发式检测**：目前通过输出文本检测触发，而非直接检测工具调用
2. **无 train/test 分割**：不像官方版本有防止过拟合的分割
3. **需要 Bourbon Agent**：依赖 Bourbon 的配置和运行环境

## 与官方 skill-creator 的区别

| 功能 | 官方 skill-creator | Bourbon 适配版 |
|------|-------------------|---------------|
| 运行环境 | `claude -p` CLI | Bourbon Agent |
| 触发检测 | 直接检测工具调用 | 启发式文本检测 |
| Description 优化 | 自动循环改进 | 需手动分析后修改 |
| Viewer | HTML 查看器 | JSON 报告 |

## 下一步改进

- [ ] 直接检测 Agent 的工具调用（而非文本分析）
- [ ] 集成到主 eval runner
- [ ] 自动 description 优化建议
- [ ] HTML 报告可视化
