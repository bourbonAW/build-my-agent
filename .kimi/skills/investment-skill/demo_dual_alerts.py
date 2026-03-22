#!/usr/bin/env python3
"""
双预警系统对比演示
同时运行两种预警系统，展示区别
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from skills.fund_monitor import FundMonitor
from skills.leading_indicator_alerts import LeadingIndicatorMonitor


def demo_dual_alerts():
    """演示双预警系统的区别"""
    
    print("\n" + "="*80)
    print("🔔 双预警系统对比演示")
    print("="*80)
    print("\n对比两个系统的输出，理解'滞后' vs '前瞻'的区别\n")
    
    # 1. 传统价格预警
    print("\n" + "-"*80)
    print("【系统1】传统价格预警 (Price-Based Alert)")
    print("-"*80)
    print("特点：基于已发生的价格变动")
    print("时效：事后提醒（滞后）\n")
    
    fund_monitor = FundMonitor()
    report = fund_monitor.monitor_all(alerts_only=True)
    fund_monitor.print_report(report)
    
    print("\n💡 解读：这个系统告诉你'已经跌了3%'，但你无法改变已发生的事")
    
    # 2. 领先指标预警
    print("\n" + "="*80)
    print("【系统2】领先指标预警 (Leading Indicator Alert) ⭐ 推荐")
    print("="*80)
    print("特点：基于预示未来变动的信号")
    print("时效：事前预警（前瞻）\n")
    
    leading_monitor = LeadingIndicatorMonitor()
    report = leading_monitor.analyze()
    leading_monitor.print_report(report)
    
    print("\n💡 解读：这个系统告诉你'48小时内可能暴跌'，你可以提前减仓避免亏损")
    
    # 总结
    print("\n" + "="*80)
    print("📊 对比总结")
    print("="*80)
    
    comparison = """
┌─────────────────────┬──────────────────────────┬──────────────────────────┐
│       维度          │    传统价格预警           │    领先指标预警           │
├─────────────────────┼──────────────────────────┼──────────────────────────┤
│ 监控对象            │ 价格、涨跌幅             │ 利差、波动率、流动性     │
│ 时间性质            │ 滞后（已发生）           │ 前瞻（将发生）           │
│ 行动价值            │ ❌ 无法行动             │ ✅ 可提前应对           │
│ 避免回撤            │ ❌ 不能                 │ ✅ 能                   │
│ 核心问题            │ "跌了多少？"            │ "将要发生什么？"        │
│ 例子                │ "有色矿业跌了3.33%"     │ "流动性紧缩，48小时内    │
│                     │                          │  可能暴跌，建议减仓"     │
└─────────────────────┴──────────────────────────┴──────────────────────────┘

🎯 使用建议：
   • 价格预警：用于复盘、了解当前状态
   • 领先指标预警：用于决策、提前避险
   • 最佳实践：两者结合使用
"""
    print(comparison)
    
    print("\n" + "="*80)
    print("✅ 演示完成")
    print("="*80)
    print("\n📚 详细文档：")
    print("   • 价格预警: ALERTS_GUIDE.md")
    print("   • 领先指标: LEADING_INDICATOR_GUIDE.md")
    print("   • 对比说明: DUAL_ALERT_SYSTEM.md")
    print("\n🚀 开始使用：")
    print("   • 单次检查: uv run python skills/leading_indicator_alerts/__init__.py")
    print("   • 持续监控: uv run python skills/leading_indicator_alerts/__init__.py --monitor")
    print()


if __name__ == "__main__":
    demo_dual_alerts()
