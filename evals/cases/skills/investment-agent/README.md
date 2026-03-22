# Investment-Agent Skill 测试用例集

## 测试覆盖总览

| 模块 | 测试用例 | 难度 | 状态 |
|------|----------|------|------|
| **基金监控** | fund-monitor.json | Medium | ✅ |
| **VIX预警** | vix-alert.json | Hard | ✅ |
| **宏观流动性** | macro-liquidity.json | Hard | ✅ |
| **组合摘要** | portfolio-summary.json | Medium | ✅ |
| **领先指标** | leading-indicator-alerts.json | Hard | ✅ |
| **半导体追踪** | semiconductor-tracker.json | Medium | ✅ |
| **中国市场** | china-market-monitor.json | Medium | ✅ |
| **每日摘要** | daily-summary.json | Medium | ✅ |
| **历史模式** | historical-patterns.json | Hard | ✅ |
| **多基金对比** | multi-fund-compare.json | Medium | ✅ |
| **风险等级变化** | risk-level-change.json | Hard | ✅ |
| **黄金避险** | gold-hedge-analysis.json | Medium | ✅ |
| **长期策略** | long-term-strategy.json | Medium | ✅ |

**总计**: 13个测试用例，覆盖全部6个核心模块

---

## 测试用例分类

### 1. 基金监控 (Fund Monitor)

**fund-monitor.json** - 查询单只基金表现
- 查询特定基金代码 (019455)
- 验证涨跌幅、净值信息
- 适合测试基本数据获取能力

### 2. 领先指标预警 (Leading Indicator Alerts)

**vix-alert.json** - VIX波动率预警
- 模拟VIX飙升到35的高风险场景
- 测试风险等级判断和防御建议

**leading-indicator-alerts.json** - 多指标综合分析
- 测试US-Japan利差、MOVE指数、高收益债利差等
- 验证综合风险评级能力

**risk-level-change.json** - 风险等级动态变化
- 测试从绿变黄/橙/红的预警机制
- 验证变化检测和行动建议

**historical-patterns.json** - 历史模式匹配
- 测试识别类似历史危机的能力
- 验证回测系统和相似度分析

### 3. 半导体追踪 (Semiconductor Tracker)

**semiconductor-tracker.json** - SOX指数分析
- 分析费城半导体指数走势
- 关联中韩半导体ETF持仓影响
- 包含DRAM/NAND价格信息

### 4. 中国市场监控 (China Market Monitor)

**china-market-monitor.json** - A股港股综合
- 沪深300估值分析 (PE/PB)
- 融资余额监控
- 北向资金流向
- 港市场表现

### 5. 宏观流动性 (Macro Liquidity)

**macro-liquidity.json** - 宏观流动性报告
- DXY美元指数
- SOFR-OIS利差
- 美债收益率曲线
- 综合分析

**gold-hedge-analysis.json** - 黄金避险分析
- 黄金基金000216分析
- DXY对黄金的影响
- 实际利率影响
- 避险效果评估

### 6. 每日摘要 (Daily Summary)

**daily-summary.json** - 每日投资日报
- 全球市场概况
- 持仓表现摘要
- 重要新闻事件
- 策略建议
- 风险评估

### 7. 组合分析

**portfolio-summary.json** - 投资组合整体摘要
- 整体盈亏分析
- 多基金表现
- 风险评级

**multi-fund-compare.json** - 多基金对比
- 多只基金对比分析
- 相关性分析
- 排名/优胜者判断

### 8. 投资策略

**long-term-strategy.json** - 长期投资策略
- 定投(DCA)建议
- 再平衡策略
- 时间跨度考虑

---

## 运行测试

### 运行所有 investment-agent 测试

```bash
uv run python evals/runner.py \
  --category skills \
  --fast \
  --num-runs 1
```

### 运行特定测试

```bash
# 修改 runner.py 添加 --case 参数支持
# 或手动指定测试文件
```

### 预期结果

- **Easy**: 基础数据查询，应该100%通过
- **Medium**: 综合分析，预期80-90%通过
- **Hard**: 复杂推理和策略建议，预期60-80%通过

---

## 测试断言类型

### 程序化断言 (Programmatic)
- `output_contains` - 包含特定文本
- `output_contains_any` - 包含任一关键词
- `output_not_contains_any` - 不包含禁用词

### LLM Judge 断言
- 主观质量评估
- 格式正确性
- 逻辑连贯性

---

## 扩展计划

### Phase 1: 当前 (已完成)
- ✅ 13个核心测试用例
- ✅ 覆盖6大模块
- ✅ 基础和高级场景

### Phase 2: 边界测试
- [ ] 极端市场情况 (VIX>50, 熔断)
- [ ] 数据缺失情况
- [ ] 网络故障恢复
- [ ] 多用户并发

### Phase 3: 性能测试
- [ ] 数据加载速度
- [ ] 报告生成时间
- [ ] 并发查询处理
- [ ] 内存使用监控

### Phase 4: 安全测试
- [ ] 数据源验证
- [ ] API 限流处理
- [ ] 敏感信息过滤
- [ ] 异常输入处理

---

## 维护说明

### 更新测试用例

当 skill 功能更新时:
1. 检查现有测试用例是否仍然适用
2. 根据新功能添加测试用例
3. 更新断言以匹配新的输出格式
4. 重新运行全量测试

### 添加新测试用例模板

```json
{
  "id": "skill-inv-[module]-[number]",
  "name": "测试名称",
  "category": "skills",
  "skill": "investment-agent",
  "difficulty": "easy|medium|hard",
  "description": "测试描述",
  "prompt": "用户输入",
  "expected": {
    "description": "期望输出描述"
  },
  "assertions": [
    {
      "id": "assertion-name",
      "type": "programmatic|llm_judge",
      "description": "断言描述",
      "check": "output_contains:xxx"
    }
  ],
  "tags": ["skill", "investment", "xxx"]
}
```

---

## 参考

- [Investment Skill 文档](/.kimi/skills/investment-skill/SKILL.md)
- [Integration 报告](/evals/INVESTMENT_SKILL_INTEGRATION.md)
- [Trigger 评测](/evals/skill-creator/eval-sets/investment-agent-trigger-eval.json)
