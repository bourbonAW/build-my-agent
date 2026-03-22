# Investment-Agent Skill 测试覆盖矩阵

**版本**: v2.0  
**测试用例**: 13个  
**覆盖模块**: 6/6 (100%)

---

## 📊 模块覆盖总览

```
┌─────────────────────────────────────────────────────────────┐
│                    Investment-Agent v2.0                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ Fund Monitor    │  │ Leading Indicators│                 │
│  │ ✅ 1 test       │  │ ✅ 4 tests        │                 │
│  │                 │  │                   │                 │
│  │ • Single fund   │  │ • VIX alert       │                 │
│  │   query         │  │ • Multi-indicator │                 │
│  │                 │  │ • Risk change     │                 │
│  │                 │  │ • Pattern match   │                 │
│  └─────────────────┘  └─────────────────┘                  │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ China Market    │  │ Macro Liquidity   │                 │
│  │ ✅ 1 test       │  │ ✅ 2 tests        │                 │
│  │                 │  │                   │                 │
│  │ • A-share/HK    │  │ • DXY/SOFR-OIS  │                 │
│  │ • Margin/North  │  │ • Gold hedge      │                 │
│  │   bound         │  │                   │                 │
│  └─────────────────┘  └─────────────────┘                  │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ Daily Summary   │  │ Semiconductor     │                 │
│  │ ✅ 1 test       │  │ ✅ 1 test         │                 │
│  │                 │  │                   │                 │
│  │ • Daily report  │  │ • SOX index       │                 │
│  │ • Global markets│  │ • DRAM/NAND       │                 │
│  │ • Strategy      │  │ • Correlation     │                 │
│  └─────────────────┘  └─────────────────┘                  │
│                                                             │
│  ┌─────────────────────────────────────────┐               │
│  │     Portfolio Analysis (2 tests)        │               │
│  │                                         │               │
│  │  • Overall summary & P&L                │               │
│  │  • Multi-fund comparison                │               │
│  │  • Correlation analysis                 │               │
│  └─────────────────────────────────────────┘               │
│                                                             │
│  ┌─────────────────────────────────────────┐               │
│  │     Strategy (1 test)                   │               │
│  │                                         │               │
│  │  • Long-term DCA                        │               │
│  │  • Rebalancing                          │               │
│  └─────────────────────────────────────────┘               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 测试用例详情

### 1. Fund Monitor (基金监控)

**skill-inv-fund-001**: 查询单只基金表现
- **Query**: "帮我查询一下019455中韩半导体ETF今天的表现"
- **Assertions**: 基金代码、涨跌幅、净值信息
- **Difficulty**: Medium
- **Status**: ✅ Ready

---

### 2. Leading Indicator Alerts (领先指标预警) - 4个测试

**skill-inv-vix-001**: VIX波动率预警
- **Query**: "VIX指数飙升到35了，这对我的投资组合有什么影响？"
- **Assertions**: VIX分析、风险等级、防御建议
- **Difficulty**: Hard

**skill-inv-leading-001**: 多指标综合分析
- **Query**: "运行领先指标预警系统，检查US-Japan利差、MOVE指数等"
- **Assertions**: 多指标、风险评级、预警阈值
- **Difficulty**: Hard

**skill-inv-risk-change-001**: 风险等级动态变化
- **Query**: "检查一下风险等级是否有变化，从昨天的绿灯变成什么颜色了？"
- **Assertions**: 等级对比、颜色指示、变化原因、行动建议
- **Difficulty**: Hard

**skill-inv-historical-001**: 历史模式匹配
- **Query**: "当前的市场状况与历史上的哪些危机案例相似？"
- **Assertions**: 历史案例、模式相似度、对比分析、警示信号
- **Difficulty**: Hard

---

### 3. China Market Monitor (中国市场监控)

**skill-inv-china-001**: A股港股综合分析
- **Query**: "看一下今天A股和港股的表现，特别是沪深300估值、融资余额和北向资金"
- **Assertions**: CSI300估值、融资余额、北向资金、港市场
- **Difficulty**: Medium

---

### 4. Macro Liquidity (宏观流动性) - 2个测试

**skill-inv-macro-001**: 宏观流动性分析报告
- **Query**: "生成一份宏观流动性分析报告，包括DXY、SOFR-OIS、美债收益率曲线"
- **Assertions**: DXY、SOFR-OIS、收益率曲线、综合分析
- **Difficulty**: Hard

**skill-inv-gold-001**: 黄金避险分析
- **Query**: "分析黄金ETF000216的避险效果，以及DXY和实际利率的影响"
- **Assertions**: 黄金基金、DXY影响、实际利率、避险效果
- **Difficulty**: Medium

---

### 5. Daily Summary (每日摘要)

**skill-inv-daily-001**: 每日投资摘要
- **Query**: "生成今天的投资日报，包含全球市场概况、持仓表现和重要新闻"
- **Assertions**: 全球市场、持仓表现、新闻事件、策略建议、风险评估
- **Difficulty**: Medium

---

### 6. Semiconductor Tracker (半导体追踪)

**skill-inv-semi-001**: SOX指数分析
- **Query**: "分析一下费城半导体指数(SOX)的最新走势，以及对持仓的影响"
- **Assertions**: SOX指数、持仓关联、趋势分析、存储芯片
- **Difficulty**: Medium

---

### 7. Portfolio Analysis (组合分析) - 2个测试

**skill-inv-portfolio-001**: 投资组合整体摘要
- **Query**: "看一下今天整个投资组合的表现，生成整体摘要报告"
- **Assertions**: 组合摘要、盈亏信息、多基金分析、风险评估
- **Difficulty**: Medium

**skill-inv-compare-001**: 多基金对比分析
- **Query**: "对比一下中韩半导体ETF、黄金ETF和纳指100ETF的表现"
- **Assertions**: 多基金、业绩对比、相关性、排名
- **Difficulty**: Medium

---

### 8. Strategy (投资策略)

**skill-inv-longterm-001**: 长期投资策略
- **Query**: "我是长期投资者，打算定投3-5年，现在这个时点应该怎么做？"
- **Assertions**: 长期视角、定投策略、再平衡、时间跨度
- **Difficulty**: Medium

---

## 📈 难度分布

| 难度 | 数量 | 占比 | 测试用例 |
|------|------|------|----------|
| **Easy** | 0 | 0% | - |
| **Medium** | 8 | 62% | fund, china, daily, semi, gold, portfolio, compare, long-term |
| **Hard** | 5 | 38% | vix, leading, risk-change, macro, historical |

---

## 🧪 断言统计

| 类型 | 数量 | 说明 |
|------|------|------|
| **Programmatic** | ~45 | `output_contains`, `output_contains_any` |
| **LLM Judge** | 0 | 当前全部使用程序化断言 |

---

## 🔍 功能覆盖检查表

### 数据采集
- [x] 基金净值数据
- [x] VIX指数数据
- [x] DXY美元指数
- [x] SOFR-OIS利差
- [x] 美债收益率曲线
- [x] 沪深300估值
- [x] 融资余额
- [x] 北向资金流向
- [x] SOX半导体指数
- [x] 存储芯片价格

### 分析能力
- [x] 单基金分析
- [x] 多基金对比
- [x] 相关性分析
- [x] 风险评级
- [x] 风险等级变化检测
- [x] 历史模式匹配
- [x] 领先指标综合分析

### 报告生成
- [x] 基金监控报告
- [x] 宏观流动性报告
- [x] 每日投资摘要
- [x] 风险预警报告
- [x] 策略建议

### 投资建议
- [x] 短期防御策略
- [x] 长期定投策略
- [x] 再平衡建议
- [x] 资产配置建议

---

## 🚀 运行所有测试

```bash
# 快速运行（推荐用于开发）
uv run python evals/runner.py \
  --category skills \
  --fast \
  --num-runs 1

# 完整运行（用于回归测试）
uv run python evals/runner.py \
  --category skills \
  --num-runs 3
```

---

## 📋 预期通过率

基于难度分布估算：

| 模块 | 预期通过率 | 原因 |
|------|-----------|------|
| Fund Monitor | 90-95% | 基础数据查询 |
| Leading Indicators | 60-75% | 复杂推理和判断 |
| China Market | 80-90% | 标准数据查询 |
| Macro Liquidity | 70-80% | 多维度分析 |
| Daily Summary | 75-85% | 报告生成 |
| Semiconductor | 80-90% | 行业分析 |
| Portfolio | 80-90% | 组合计算 |
| Strategy | 65-75% | 主观建议 |

**整体预期**: 75-85%

---

## 🎯 扩展建议

### Phase 1: 边界测试
- [ ] 极端市场情况 (VIX>50)
- [ ] 数据缺失处理
- [ ] 网络故障恢复

### Phase 2: 性能测试
- [ ] 数据加载速度
- [ ] 报告生成时间
- [ ] 并发查询处理

### Phase 3: 负面测试
- [ ] 无效基金代码
- [ ] 错误日期范围
- [ ] 权限不足场景

---

*Coverage Matrix v1.0 - Generated 2026-03-22*
