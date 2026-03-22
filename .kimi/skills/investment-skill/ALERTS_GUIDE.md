# 实时预警系统使用指南

## 📍 预警功能位置

投资Agent中有**3处**实现了预警功能：

### 1. 基金监控内置预警 (Fund Monitor)
**位置**: `skills/fund_monitor/__init__.py`  
**方法**: `_check_alerts()`  
**使用**:
```bash
# 运行基金监控（自动包含预警检查）
./run.sh fund-monitor

# 或只显示预警
./run.sh fund-monitor --alert
```

**预警条件**（在 `config/portfolio.yaml` 中配置）:
- 单日跌幅超过 -3.0%
- 单日涨幅超过 5.0%
- 连续3天下跌
- 偏离基准指数超过 5.0%

### 2. 宏观流动性预警 (Macro Liquidity)
**位置**: `skills/macro_liquidity/__init__.py`  
**方法**: `_check_alerts()`  
**使用**:
```bash
# 运行宏观分析（自动包含预警检查）
./run.sh macro-liquidity

# 或只显示预警
./run.sh macro-liquidity --alert
```

**预警条件**:
- Fed资产负债表收缩超过 5%
- SOFR利率超过 5.5%
- 美元指数超过 105（强美元）或低于 100（弱美元）
- 收益率曲线倒挂
- 黄金价格变动超过 3%

### 3. 独立实时预警系统 (Realtime Alerts) ⭐ 推荐
**位置**: `skills/realtime_alerts/__init__.py`  
**特点**: 专门用于实时监控，支持持续监控模式

**使用方式**:

#### 单次检查（立即查看当前状态）
```bash
cd ~/investment-skill
uv run python -m skills.realtime_alerts
```

#### 持续监控模式（Daemon）
```bash
# 每5分钟检查一次（默认）
uv run python -m skills.realtime_alerts --monitor

# 每10分钟检查一次
uv run python -m skills.realtime_alerts --monitor --interval 600

# 只监控基金和宏观
uv run python -m skills.realtime_alerts --monitor --type fund,macro
```

## 🚨 实时预警功能特性

### 预警去重机制
- **30分钟内不会重复触发**相同预警
- 避免因为数据波动导致的预警轰炸

### 多维度监控
1. **基金预警**
   - 单日大幅涨跌
   - 从成本价下跌超过10%
   - 连续下跌

2. **宏观预警**
   - VIX波动率指数
   - 主要市场指数大幅波动
   - 美元走势

3. **市场预警**
   - 半导体指数(SOX)异动
   - 其他行业指数

### 输出方式
- **控制台**: 彩色输出，带表情符号
- **Vault文件**: 自动保存到 `daily/YYYY-MM-DD_alerts.md`
- **Markdown格式**: 便于在Obsidian中查看

## ⚡ 使用建议

### 场景1: 每天早上开盘前检查
```bash
# 添加到crontab，每天早上8:30运行
30 8 * * 1-5 cd ~/investment-skill && uv run python -m skills.realtime_alerts >> ~/.investment-skill/logs/morning.log 2>&1
```

### 场景2: 盘中实时监控（适合交易日）
```bash
# 开启实时监控，每5分钟检查
uv run python -m skills.realtime_alerts --monitor

# 放在后台运行（Linux/macOS）
nohup uv run python -m skills.realtime_alerts --monitor > ~/.investment-skill/logs/realtime.log 2>&1 &
```

### 场景3: 只关注特定基金
```python
# 修改代码或使用过滤器
alert_system = RealtimeAlertSystem()
alerts = alert_system.check_now(['fund'])  # 只检查基金
```

### 场景4: 自定义预警阈值
编辑 `config/portfolio.yaml`:
```yaml
alerts:
  daily_decline_threshold: -2.0    # 改为2%就预警
  daily_surge_threshold: 3.0       # 改为3%就预警
  consecutive_decline_days: 2      # 连续2天预警
```

## 📊 预警报告示例

当触发预警时，你会看到：

```
🚨 2 new alert(s) triggered!

🔴 [FUND] 国泰有色矿业ETF联接A(018167) - Significant Decline
   Daily decline of -3.33% exceeds threshold of -3.0%
   Time: 2026-02-22T14:30:00

🟡 [MACRO] High Volatility Alert (VIX)
   VIX at 25.5, indicating elevated market volatility
   Time: 2026-02-22T14:30:00

💾 Alerts saved to: /Users/whf/vault-notes/daily/2026-02-22_alerts.md
```

## 🔧 高级用法

### 添加自定义回调
```python
from skills.realtime_alerts import RealtimeAlertSystem

def send_wechat_notification(alerts):
    """发送微信通知示例"""
    for alert in alerts:
        # 调用微信API发送通知
        print(f"Sending WeChat: {alert.title}")

alert_system = RealtimeAlertSystem()
alert_system.monitor_continuously(
    interval=300,
    on_alert=send_wechat_notification  # 触发预警时回调
)
```

### 与其他系统集成
```python
# 推送到Slack
# 发送邮件
# 写入数据库
# 发送短信
```

## 📁 文件位置总结

| 功能 | 文件路径 | 使用方式 |
|------|---------|----------|
| 基金预警 | `skills/fund_monitor/__init__.py` | `./run.sh fund-monitor` |
| 宏观预警 | `skills/macro_liquidity/__init__.py` | `./run.sh macro-liquidity` |
| 实时预警 | `skills/realtime_alerts/__init__.py` | `uv run python -m skills.realtime_alerts` |
| 配置阈值 | `config/portfolio.yaml` | 编辑YAML文件 |
| 预警输出 | `vault-notes/daily/YYYY-MM-DD_alerts.md` | 查看Obsidian |

## 💡 最佳实践

1. **日常使用**: 每天早上运行一次 `./run.sh` 查看所有报告
2. **关键时刻**: 在重要数据发布日（CPI、美联储决议等）开启实时监控
3. **定期检查**: 每周回顾一次预警历史，调整阈值
4. **避免过度预警**: 如果预警太多，适当放宽阈值（如从-3%改为-5%）

## 🔗 相关文件

- 预警配置: `config/portfolio.yaml` (alerts部分)
- 基金配置: `config/portfolio.yaml` (funds部分)
- 预警输出: `vault-notes/daily/YYYY-MM-DD_alerts.md`
- 监控日志: `~/.investment-skill/logs/`
