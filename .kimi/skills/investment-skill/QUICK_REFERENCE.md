# 实时预警系统 - 快速参考

## 🎯 当前预警功能位置

### 1️⃣ 基金监控预警 (内置)
```
位置: skills/fund_monitor/__init__.py
命令: ./run.sh fund-monitor --alert
配置: config/portfolio.yaml (alerts部分)
```

### 2️⃣ 宏观流动性预警 (内置)  
```
位置: skills/macro_liquidity/__init__.py
命令: ./run.sh macro-liquidity --alert
配置: config/portfolio.yaml (alerts部分)
```

### 3️⃣ 独立实时预警系统 (推荐)
```
位置: skills/realtime_alerts/__init__.py ⭐
命令: uv run python skills/realtime_alerts/__init__.py
功能: 支持持续监控模式
```

---

## 🚀 使用方式

### 单次检查（立即查看）
```bash
cd ~/investment-skill
uv run python skills/realtime_alerts/__init__.py
```

### 持续监控（Daemon模式）
```bash
# 每5分钟检查一次
uv run python skills/realtime_alerts/__init__.py --monitor

# 每10分钟检查
uv run python skills/realtime_alerts/__init__.py --monitor --interval 600

# 只监控基金和宏观
uv run python skills/realtime_alerts/__init__.py --monitor --type fund,macro
```

### 快捷键添加到run.sh
```bash
# 编辑 ~/investment-skill/run.sh，添加:
realtime-alerts|ra)
    echo "🚨 Running Real-time Alerts..."
    uv run python skills/realtime_alerts/__init__.py $@
    ;;
```

然后使用: `./run.sh realtime-alerts --monitor`

---

## ⚙️ 预警配置

编辑 `config/portfolio.yaml`:

```yaml
alerts:
  daily_decline_threshold: -3.0    # 单日跌幅超过3%预警
  daily_surge_threshold: 5.0       # 单日涨幅超过5%预警
  consecutive_decline_days: 3      # 连续3天下跌预警
  benchmark_deviation: 5.0         # 偏离基准5%预警
  portfolio_decline_threshold: -5.0 # 组合下跌5%预警
```

---

## 📊 预警输出

### 控制台输出
```
🚨 1 new alert(s) triggered!

🟡 [FUND] 国泰有色矿业ETF联接A(018167) - Significant Decline
   Daily decline of -3.33% exceeds threshold of -3.0%
   Time: 2026-02-22T23:48:00
```

### Vault文件
保存位置: `vault-notes/daily/YYYY-MM-DD_alerts.md`

---

## 🔔 预警类型

| 类型 | 严重程度 | 触发条件 | 示例 |
|------|---------|---------|------|
| **基金跌幅** | 🟡 warning | 单日跌超-3% | 有色矿业-3.33% |
| **基金涨幅** | 🔵 info | 单日涨超5% | - |
| **持仓亏损** | 🔴 alert | 从成本亏超10% | - |
| **VIX高位** | 🟡 warning | VIX>25 | 波动率预警 |
| **指数异动** | 🟡 warning | 标普500涨跌>2% | - |
| **SOX异动** | 🟡 warning | 半导体指数>3% | - |

---

## 💡 实际使用场景

### 场景1: 每天早上检查
```bash
# 添加到crontab，工作日8:30运行
30 8 * * 1-5 cd ~/investment-skill && uv run python skills/realtime_alerts/__init__.py
```

### 场景2: 重大数据发布日
```bash
# 美国CPI发布日，开启实时监控
uv run python skills/realtime_alerts/__init__.py --monitor --interval 180
```

### 场景3: 盘中关注
```bash
# 放在后台运行
nohup uv run python skills/realtime_alerts/__init__.py --monitor > logs/realtime.log 2>&1 &

# 查看日志
tail -f logs/realtime.log
```

---

## 📁 文件位置速查

```
~/investment-skill/
├── skills/
│   ├── fund_monitor/__init__.py          # 基金预警
│   ├── macro_liquidity/__init__.py       # 宏观预警
│   └── realtime_alerts/__init__.py       # ⭐ 独立实时预警
├── config/portfolio.yaml                  # 预警阈值配置
├── ALERTS_GUIDE.md                        # 详细文档
└── QUICK_REFERENCE.md                     # 本文件

~/vault-notes/daily/
├── YYYY-MM-DD_alerts.md                   # 预警记录
└── YYYY-MM-DD_fund_report.md              # 基金报告
```

---

## 🎓 学习路径

1. **快速开始**: 运行 `./run.sh` 查看所有报告
2. **理解预警**: 阅读 `ALERTS_GUIDE.md`
3. **自定义**: 修改 `config/portfolio.yaml` 调整阈值
4. **自动化**: 设置定时任务或开启持续监控
5. **集成**: 添加自定义回调（微信/Slack/邮件等）

---

## ⚡ 命令速查表

| 命令 | 功能 |
|------|------|
| `./run.sh` | 运行所有报告 |
| `./run.sh fund-monitor` | 基金监控（含预警） |
| `./run.sh fund-monitor --alert` | 只显示预警 |
| `uv run python skills/realtime_alerts/__init__.py` | 单次预警检查 |
| `uv run python skills/realtime_alerts/__init__.py --monitor` | 持续监控 |
| `uv run python skills/realtime_alerts/__init__.py --interval 600` | 每10分钟检查 |

---

**最新状态**: ✅ 实时预警系统已部署并测试成功
**最后更新**: 2026-02-22
