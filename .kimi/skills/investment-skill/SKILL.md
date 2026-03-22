---
name: investment-agent
description: |
  Comprehensive investment portfolio monitoring and leading indicator alert system for 
  Chinese A-share, Hong Kong stocks, and global markets. This skill automatically 
  tracks 12 funds, monitors 10+ leading market indicators, analyzes macro liquidity, 
  and generates comprehensive investment reports with risk warnings.
  
  **USE THIS SKILL** whenever the user wants to:
  - Monitor their investment portfolio or fund performance
  - Check market conditions or get daily/weekly investment summaries
  - Analyze VIX, DXY, or other volatility/liquidity indicators
  - Track semiconductor industry trends or China/HK market conditions
  - Get strategic recommendations for portfolio adjustments
  - Understand whether to hold, reduce, or increase positions
  - Check macro liquidity, Fed policy impact, or gold/currency trends
  - Monitor specific funds (019455中韩半导体, 000216黄金, 013402恒科, etc.)
  - Receive alerts when funds decline >3% or VIX spikes >30
  - Analyze risk levels (Green/Yellow/Orange/Red) and defensive strategies
  
  **CRITICAL CAPABILITIES:**
  - 6 monitoring modules: Fund Monitor, Macro Liquidity, Daily Summary, 
    Semiconductor Tracker, China Market Monitor, Leading Indicator Alerts
  - 30+ tracked indicators: VIX, DXY, SOFR-OIS, yield curve, credit spreads, 
    PE ratios, margin debt, fund flows, SOX index, and more
  - Automated report generation to Obsidian vault with warning levels
  - Historical pattern matching (8 crisis cases) and backtesting system
  - Both short-term tactical and long-term strategic recommendations
  
  **AUTO-TRIGGER CONTEXTS:**
  - User mentions "fund", "portfolio", "investment", "stock", "market", "VIX", 
    "semiconductor", " analyze", "report", "recommendation", "should I buy/sell"
  - User asks about specific fund codes (019455, 000216, 013402, etc.)
  - User mentions "risk", "warning", "alert", "decline", "crash", "crisis"
  - User asks about China market, 港股, A股, or macro economic conditions
  - User wants to know portfolio performance or P&L status
  
  **OUTPUT:** Comprehensive markdown reports with warning levels (🟢🟡🟠🔴), 
  actionable recommendations, and historical pattern analysis. All reports 
  auto-saved to vault-notes/ for Obsidian integration.
  
  **TYPICAL USAGE PATTERNS:**
  - "帮我跑一遍今天的任务，生成报告" → Run all monitors and generate comprehensive report
  - "VIX飙升到30了，我该怎么办？" → Analyze VIX spike impact and give defensive advice
  - "看看我的基金组合" → Check 12 funds performance and generate report
  - "半导体行业怎么样？" → Analyze semiconductor trends and portfolio impact
  - "我是长线投资者，需要操作吗？" → Provide long-term investment strategy guidance

version: 2.0
author: Investment Agent Team
compatibility:
  python: "3.10+"
  dependencies:
    - uv (package manager)
    - akshare (China market data)
    - yfinance (global markets)
    - playwright (web scraping)
    - pandas, numpy (data processing)
  platforms: [macOS, Linux]
  integrations: [Obsidian Vault, Claude Code]

---

# Investment Agent Skill v2.0

An intelligent investment analysis system that automates data collection, portfolio monitoring, and predictive market analysis using leading indicators (not just price-based alerts). Built for integration with Obsidian vault-based knowledge management.

## Quick Start

```bash
# Run complete daily analysis (all 6 modules)
./run.sh

# Or run individual skills
uv run python skills/fund_monitor/__init__.py
uv run python skills/leading_indicator_alerts/__init__.py
uv run python skills/china_market_monitor/__init__.py
```

## Core Capabilities

### 1. **Portfolio Monitoring** (`skills/fund_monitor/`)
Track 12 funds with real-time performance and alerting.

**Monitored Funds:**
- 019455: 华泰柏瑞中韩半导体ETF (Semiconductor)
- 000216: 华安黄金ETF (Gold)
- 013402: 华夏恒生科技ETF (HK Tech)
- 016532: 嘉实纳斯达克100ETF (NASDAQ)
- 017091: 景顺长城纳斯达克科技ETF (Tech)
- 501312: 华宝海外科技股票 (Overseas Tech)
- 050025: 博时标普500ETF (S&P 500)
- 161125: 易方达标普500指数 (S&P 500)
- 007300: 国联安中证半导体ETF (A-share Semi)
- 008887: 华夏国证半导体芯片ETF (Chips)
- 018167: 国泰有色矿业ETF (Mining)
- 007910: 大成有色金属期货ETF (Metals)

**Alert Thresholds:**
- Daily decline >3%: Yellow alert
- Daily decline >5%: Red alert  
- Daily surge >5%: Blue alert
- Consecutive 3-day decline: Warning

### 2. **Leading Indicator Alerts** (`skills/leading_indicator_alerts/`)
**The core innovation** - predict market moves 24-72 hours in advance.

**10 Leading Indicators:**
1. **US-Japan 2Y Spread** - Yen carry trade unwind warning
2. **DXY Dollar Index** - Global liquidity conditions
3. **MOVE/VIX Index** - Bond/stock market volatility
4. **Yield Curve (10Y-2Y)** - Recession predictor
5. **IG Credit Spreads** - Corporate bond stress
6. **SOFR-OIS Spread** - Interbank liquidity
7. **High Yield Spreads** - Risk appetite gauge
8. **TED Spread** - Offshore dollar liquidity
9. **Term Premium** - Long bond risk compensation
10. **Copper-Gold Ratio** - Economic cycle indicator

**Warning System:**
- 🟢 Green: All indicators normal
- 🟡 Yellow: 1-2 elevated signals
- 🟠 Orange: 3+ signals or 1 critical
- 🔴 Red: Multiple critical signals (action required)

### 3. **China Market Monitor** (`skills/china_market_monitor/`)
A-share and HK market-specific indicators.

**Monitored Metrics:**
- **Valuation:** CSI300 PE/PB, ChiNext PE, risk premium
- **Leverage:** Margin balance/GDP, margin buy ratio
- **Sentiment:** Turnover rate, new investor accounts, fear/greed index
- **Flows:** Northbound (外资), Southbound (内资), main force flows

**Thresholds:**
- CSI300 PE >20x: Overvalued
- Margin/GDP >3%: Extreme leverage (2015-level risk)
- Turnover >6%: Market fever

### 4. **Semiconductor Tracker** (`skills/semiconductor_tracker/`)
Track SOX index and correlate with your semiconductor holdings.

**Metrics:**
- Philadelphia Semiconductor Index (SOX)
- Memory chip prices (DRAM/NAND trends)
- Portfolio correlation analysis
- Korea KOSPI vs A-share semi divergence

### 5. **Macro Liquidity** (`skills/macro_liquidity/`)
Fed policy impact and global liquidity conditions.

**Indicators:**
- Fed balance sheet changes
- Treasury yield curve
- Gold prices vs real yields
- DXY and EM currency stress

### 6. **Daily Summary** (`skills/daily_summary/`)
Generate comprehensive daily briefings.

**Includes:**
- Global market overview (US, HK, CN)
- Portfolio performance summary
- Key news and macro events
- Strategy suggestions
- Risk level assessment

## Architecture

```
~/investment-skill/
├── SKILL.md                          # This file
├── config/
│   ├── portfolio.yaml                # 12 fund holdings
│   └── sources.yaml                  # Data source config
├── skills/                           # 6 core modules
│   ├── fund_monitor/
│   ├── leading_indicator_alerts/     # ⭐ Core innovation
│   ├── china_market_monitor/         # ⭐ A-share/HK specific
│   ├── macro_liquidity/
│   ├── daily_summary/
│   └── semiconductor_tracker/
├── collectors/                       # Data sources
│   ├── eastmoney_collector.py
│   ├── akshare_collector.py
│   ├── yahoo_collector.py
│   └── macro_collector.py
├── utils/                           # Shared utilities
│   ├── vault_writer.py
│   └── data_cache.py
├── evals/                           # 🆕 Test cases (new in v2.0)
│   └── evals.json
├── scripts/                         # 🆕 Helper scripts (new in v2.0)
│   ├── run_all_monitors.py
│   └── generate_comprehensive_report.py
└── references/                      # 🆕 Documentation (new in v2.0)
    └── historical_patterns/
```

## Commands

### Run Complete Analysis
```bash
./run.sh                    # Run all 6 skills sequentially
```

### Individual Skills
```bash
# Fund monitoring
uv run python skills/fund_monitor/__init__.py

# Leading indicators (predictive alerts)
uv run python skills/leading_indicator_alerts/__init__.py

# China A-share/HK market
uv run python skills/china_market_monitor/__init__.py

# Macro liquidity
uv run python skills/macro_liquidity/__init__.py

# Semiconductor industry
uv run python skills/semiconductor_tracker/__init__.py

# Daily summary
uv run python skills/daily_summary/__init__.py
```

### Test & Benchmark (New in v2.0)
```bash
# Run test cases
python -m scripts.run_tests

# Generate performance benchmark
python -m scripts.benchmark

# View evaluation results
python eval-viewer/generate_review.py
```

## Configuration

### Portfolio Setup (`config/portfolio.yaml`)
```yaml
portfolio:
  funds:
    - code: "019455"
      name: "华泰柏瑞中韩半导体ETF联接C"
      category: "semiconductor"
      region: "asia"
      weight: 0.083  # 8.3% of portfolio
      
    - code: "000216"
      name: "华安黄金ETF联接A"
      category: "commodity"
      region: "global"
      weight: 0.083
  
  alerts:
    daily_decline_threshold: -3.0
    consecutive_decline_days: 3
    daily_surge_threshold: 5.0
    vix_critical: 30
    vix_extreme: 40
```

### Data Sources (`config/sources.yaml`)
```yaml
sources:
  fund_data:
    primary: "eastmoney"
    backup: "akshare"
  
  macro_data:
    fed: "federal_reserve_api"
    yahoo: "yahoo_finance"
    
  china_data:
    a_share: "akshare"
    hk_stock: "yahoo_finance"
```

## Historical Pattern System (New in v2.0)

**8 Crisis Cases in Knowledge Base:**
1. 1997 Asian Financial Crisis
2. 2008 Financial Crisis
3. 2011 EU Debt Crisis
4. 2015 A-share Circuit Breaker
5. 2018 US-China Trade War
6. 2020 COVID Liquidity Crisis
7. 2022 Strong Dollar Shock
8. 2024 Yen Carry Trade Unwind

**Pattern Matching:**
- Smart matching algorithm compares current indicators to historical cases
- Weighted scoring (0-100% match)
- Actionable lessons from each crisis
- Auto-suggestions based on historical patterns

## Output Examples

### Comprehensive Daily Report
```markdown
# 📊 Daily Investment Report - 2026-03-10

**Warning Level:** 🟢 GREEN

## Executive Summary
- Portfolio: +1.84% (12/12 funds up)
- VIX: 28.58 (elevated but stable)
- Leading Indicators: 0 warnings

## Key Alerts
✅ All systems normal

## Strategic Recommendation
Hold current positions. Market recovered from yesterday's dip.
```

### Leading Indicator Alert (Crisis Mode Example)
```markdown
# 🔮 Leading Indicator Alert - 2026-03-08

**Warning Level:** 🔴 RED

## Critical Signals (3)
🚨 VIX: 29.49 (+24%) - Market panic level
🚨 DXY: >105 - Strong dollar pressure
🚨 US-JP Spread: <3.5% - Carry trade unwind risk

## Historical Pattern Match
2024 Yen Carry Trade Unwind: 72% similarity
2022 Strong Dollar Shock: 68% similarity

## Action Required
📉 Reduce QDII funds by 30%
🛡️ Increase gold to 15%
💵 Keep 20% cash
```

## Automation

### Scheduled Execution (crontab)
```bash
# Daily at 8:00 AM (market open)
0 8 * * 1-5 cd ~/investment-skill && ./run.sh

# Leading indicators check every 2 hours
0 */2 * * 1-5 cd ~/investment-skill && uv run python skills/leading_indicator_alerts/__init__.py
```

### macOS LaunchAgent
See `templates/com.investment.agent.plist` for native macOS scheduling.

## Integration with Obsidian Vault

All reports automatically saved to your vault:

```
vault-notes/
├── daily/
│   ├── 2026-03-10_comprehensive_report.md
│   ├── 2026-03-10_fund_report.md
│   └── 2026-03-10_investment.md
├── knowledge/
│   └── investment/
│       ├── macro/
│       │   ├── leading_indicator_alert_*.md
│       │   └── china_market_alert_*.md
│       ├── industries/
│       │   └── semiconductor/
│       └── historical_patterns/
│           ├── 2008_financial_crisis.md
│           ├── 2020_covid_crisis.md
│           └── 2024_yen_carry_unwind.md
```

## For Long-Term Investors

**Core Philosophy:** Time is your friend, volatility is opportunity.

**When to Act:**
- 🔴 Red warning + portfolio down >5%: Consider 20-30% reduction
- 🟠 Orange warning: Monitor closely, prepare action plan
- 🟡 Yellow warning: Normal fluctuation, hold positions
- 🟢 Green: Maintain strategy, enjoy the ride

**When NOT to Act:**
- Daily -1% to -3% declines: Normal market noise
- VIX 20-25: Low volatility period
- Single fund down while others stable: Diversification working

**Remember:** The system monitors 30+ indicators so you don't have to check prices daily. Trust the leading indicators over price movements.

## Requirements

- Python 3.10+
- uv (modern Python package manager)
- Dependencies managed via `pyproject.toml`

**Installation:**
```bash
# Using uv (recommended)
uv sync

# Or traditional pip
pip install -r requirements.txt
```

## Testing & Benchmarking (New in v2.0)

### Run Test Suite
```bash
# Run all test cases
python -m scripts.run_tests

# Check specific skill
python -m scripts.test_skill fund_monitor
```

### Performance Benchmark
```bash
# Generate benchmark report
python -m scripts.benchmark --iterations 3

# View results
open benchmark_report.html
```

### Test Cases Include:
- Portfolio monitoring accuracy
- VIX spike detection and response
- Crisis pattern matching
- Long-term vs short-term strategy differentiation
- China market specific scenarios

## Development

### Adding New Skills
1. Create directory in `skills/`
2. Implement `analyze()` function returning report object
3. Add to `run.sh` sequence
4. Write test cases in `evals/evals.json`

### Version History

**v2.0 (Current)**
- ✅ Test-driven development with evals system
- ✅ Historical pattern matching (8 crisis cases)
- ✅ China A-share/HK specific monitor (25 indicators)
- ✅ Performance benchmarking framework
- ✅ Optimized skill description for better triggering
- ✅ Helper scripts for automation

**v1.0 (Initial)**
- 4 core skills (fund, macro, daily, semi)
- Basic alerting system
- Vault integration

## License

Private use only. Personal investment tool.

## Support

- **Documentation:** See `references/` directory
- **Test Reports:** Check `evals/` after running tests
- **Historical Analysis:** Review `vault-notes/knowledge/investment/historical_patterns/`

---

**Remember:** This skill uses leading indicators to predict market moves, not just react to price changes. Trust the system, think long-term, and let time work in your favor.
