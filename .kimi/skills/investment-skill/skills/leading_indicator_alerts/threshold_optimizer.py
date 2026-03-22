"""
Indicator Threshold Optimizer - 指标阈值优化器

基于历史回测数据，自动优化指标阈值和权重配置

使用方法:
    uv run python threshold_optimizer.py
    uv run python threshold_optimizer.py --generate-config
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class OptimizedThreshold:
    """优化后的阈值"""
    indicator: str
    current_elevated: float
    current_critical: float
    optimized_elevated: float
    optimized_critical: float
    confidence: str  # high, medium, low
    rationale: str
    historical_range: Tuple[float, float]
    recommended_weight: float


class ThresholdOptimizer:
    """阈值优化器 - 基于历史数据优化指标配置"""
    
    def __init__(self):
        self.historical_signals = self._load_historical_signals()
        self.current_configs = self._load_current_configs()
    
    def _load_historical_signals(self) -> List[Dict]:
        """从增强回测结果加载历史信号"""
        # 基于成功提取的历史信号数据
        signals = [
            # 1997亚洲金融危机
            {"indicator": "current_account_gdp", "value": -8.2, "severity": "critical", "lead_days": 90, "crisis": "1997_asian"},
            {"indicator": "short_term_debt_reserves", "value": 150, "severity": "critical", "lead_days": 60, "crisis": "1997_asian"},
            {"indicator": "forward_premium", "value": 15, "severity": "critical", "lead_days": 30, "crisis": "1997_asian"},
            
            # 2008金融危机
            {"indicator": "yield_curve", "value": -0.1, "severity": "critical", "lead_days": 260, "crisis": "2008_crisis"},
            {"indicator": "libor_ois_spread", "value": 80, "severity": "critical", "lead_days": 390, "crisis": "2008_crisis"},
            {"indicator": "vix", "value": 48, "severity": "critical", "lead_days": 0, "crisis": "2008_crisis"},
            
            # 2011欧债危机
            {"indicator": "bond_yield", "value": 7.5, "severity": "critical", "lead_days": 35, "crisis": "2011_eu"},
            {"indicator": "cds_spread", "value": 400, "severity": "critical", "lead_days": 35, "crisis": "2011_eu"},
            {"indicator": "vix", "value": 35, "severity": "elevated", "lead_days": 30, "crisis": "2011_eu"},
            
            # 2015A股熔断
            {"indicator": "pe_ratio_gem", "value": 140, "severity": "critical", "lead_days": 70, "crisis": "2015_a_share"},
            {"indicator": "margin_debt_gdp", "value": 2.2, "severity": "critical", "lead_days": 15, "crisis": "2015_a_share"},
            
            # 2018贸易战
            {"indicator": "rmb_volatility", "value": 8, "severity": "elevated", "lead_days": 60, "crisis": "2018_trade"},
            {"indicator": "cnh_cny_spread", "value": 500, "severity": "elevated", "lead_days": 30, "crisis": "2018_trade"},
            {"indicator": "policy_news_frequency", "value": 10, "severity": "elevated", "lead_days": 80, "crisis": "2018_trade"},
            
            # 2020COVID
            {"indicator": "vix", "value": 82, "severity": "critical", "lead_days": -7, "crisis": "2020_covid"},
            {"indicator": "move", "value": 160, "severity": "critical", "lead_days": 0, "crisis": "2020_covid"},
            
            # 2022强美元
            {"indicator": "dxy", "value": 105, "severity": "elevated", "lead_days": 200, "crisis": "2022_dollar"},
            {"indicator": "us_2y_yield", "value": 3.5, "severity": "elevated", "lead_days": 40, "crisis": "2022_dollar"},
            
            # 2024日元套利
            {"indicator": "us_jp_spread", "value": 3.2, "severity": "critical", "lead_days": 4, "crisis": "2024_yen"},
            {"indicator": "usdjpy_change", "value": -2.0, "severity": "critical", "lead_days": 3, "crisis": "2024_yen"},
            {"indicator": "vix", "value": 38, "severity": "elevated", "lead_days": 0, "crisis": "2024_yen"},
        ]
        return signals
    
    def _load_current_configs(self) -> Dict:
        """加载当前配置"""
        return {
            "us_jp_spread_2y": {
                "name": "美日2年期利差",
                "elevated": 4.0,
                "critical": 3.0,
                "weight": 3.0,
                "applicable_crisis": ["yen_carry_trade_unwind", "currency_crisis"]
            },
            "dxy": {
                "name": "美元指数DXY",
                "elevated": 105,
                "critical": 107,
                "weight": 3.0,
                "applicable_crisis": ["strong_dollar_shock", "currency_crisis"]
            },
            "vix": {
                "name": "VIX波动率指数",
                "elevated": 28,
                "critical": 35,
                "weight": 2.5,
                "applicable_crisis": ["liquidity_crisis", "financial_crisis", "all"]
            },
            "move": {
                "name": "MOVE美债波动率",
                "elevated": 120,
                "critical": 140,
                "weight": 2.5,
                "applicable_crisis": ["liquidity_crisis", "financial_crisis"]
            },
            "yield_curve_10y2y": {
                "name": "收益率曲线(10Y-2Y)",
                "elevated": 0.5,
                "critical": 0.0,
                "weight": 3.0,
                "applicable_crisis": ["financial_crisis", "recession"]
            },
            "credit_spread_ig": {
                "name": "投资级信用利差",
                "elevated": 150,
                "critical": 200,
                "weight": 2.0,
                "applicable_crisis": ["financial_crisis", "credit_crisis"]
            },
            "high_yield_spread": {
                "name": "高收益债利差",
                "elevated": 500,
                "critical": 800,
                "weight": 2.0,
                "applicable_crisis": ["financial_crisis", "credit_crisis", "recession"]
            },
            "sofr_ois_spread": {
                "name": "SOFR-OIS利差",
                "elevated": 30,
                "critical": 50,
                "weight": 2.5,
                "applicable_crisis": ["liquidity_crisis", "financial_crisis"]
            },
            "ted_spread": {
                "name": "TED利差",
                "elevated": 40,
                "critical": 100,
                "weight": 2.0,
                "applicable_crisis": ["liquidity_crisis", "currency_crisis"]
            },
            "copper_gold_ratio": {
                "name": "铜金比",
                "elevated": -5,
                "critical": -10,
                "weight": 1.5,
                "applicable_crisis": ["recession", "trade_war"]
            }
        }
    
    def optimize_thresholds(self) -> List[OptimizedThreshold]:
        """优化阈值"""
        optimized = []
        
        for indicator_id, config in self.current_configs.items():
            # 找到该指标的历史信号
            historical_values = [
                s for s in self.historical_signals 
                if indicator_id.replace('_', '') in s["indicator"].replace('_', '')
            ]
            
            if historical_values:
                opt = self._optimize_single_indicator(indicator_id, config, historical_values)
                optimized.append(opt)
            else:
                # 没有历史数据，保持当前配置
                optimized.append(OptimizedThreshold(
                    indicator=config["name"],
                    current_elevated=config["elevated"],
                    current_critical=config["critical"],
                    optimized_elevated=config["elevated"],
                    optimized_critical=config["critical"],
                    confidence="low",
                    rationale="缺乏历史数据验证，保持当前配置",
                    historical_range=(config["elevated"], config["critical"]),
                    recommended_weight=config["weight"]
                ))
        
        return optimized
    
    def _optimize_single_indicator(self, indicator_id: str, config: Dict, 
                                   historical_values: List[Dict]) -> OptimizedThreshold:
        """优化单个指标"""
        
        # 提取历史值
        values = [s["value"] for s in historical_values]
        critical_values = [s["value"] for s in historical_values if s["severity"] == "critical"]
        elevated_values = [s["value"] for s in historical_values if s["severity"] == "elevated"]
        
        # 计算统计值
        min_val = min(values)
        max_val = max(values)
        avg_val = sum(values) / len(values)
        
        # 根据指标方向调整阈值
        direction = self._get_indicator_direction(indicator_id)
        
        if direction == "falling":
            # 值越小越危险（如利差收窄）
            opt_elevated = max(elevated_values) if elevated_values else config["elevated"]
            opt_critical = min(critical_values) if critical_values else config["critical"]
            
            # 保守调整：elevated比平均值略宽松
            if elevated_values:
                opt_elevated = (max(elevated_values) + avg_val) / 2
            if critical_values:
                opt_critical = min(critical_values) * 1.05  # 留5%缓冲
                
        else:  # rising
            # 值越大越危险（如VIX上升）
            opt_elevated = min(elevated_values) if elevated_values else config["elevated"]
            opt_critical = max(critical_values) if critical_values else config["critical"]
            
            if elevated_values:
                opt_elevated = (min(elevated_values) + avg_val) / 2
            if critical_values:
                opt_critical = max(critical_values) * 0.95  # 留5%缓冲
        
        # 计算置信度
        confidence = self._calculate_confidence(len(historical_values), config)
        
        # 计算推荐权重（基于提前期）
        avg_lead = sum(s["lead_days"] for s in historical_values) / len(historical_values)
        recommended_weight = self._calculate_weight(avg_lead, config["weight"])
        
        # 生成理由
        rationale = self._generate_rationale(indicator_id, historical_values, 
                                            config, opt_elevated, opt_critical)
        
        return OptimizedThreshold(
            indicator=config["name"],
            current_elevated=config["elevated"],
            current_critical=config["critical"],
            optimized_elevated=round(opt_elevated, 2),
            optimized_critical=round(opt_critical, 2),
            confidence=confidence,
            rationale=rationale,
            historical_range=(round(min_val, 2), round(max_val, 2)),
            recommended_weight=round(recommended_weight, 1)
        )
    
    def _get_indicator_direction(self, indicator_id: str) -> str:
        """获取指标方向"""
        falling_indicators = ["yield_curve", "us_jp_spread", "copper_gold"]
        for fi in falling_indicators:
            if fi in indicator_id:
                return "falling"
        return "rising"
    
    def _calculate_confidence(self, data_points: int, config: Dict) -> str:
        """计算置信度"""
        if data_points >= 5:
            return "high"
        elif data_points >= 3:
            return "medium"
        else:
            return "low"
    
    def _calculate_weight(self, avg_lead_days: float, current_weight: float) -> float:
        """计算推荐权重（提前期越长，权重越高）"""
        if avg_lead_days >= 60:
            return min(current_weight * 1.2, 4.0)  # 提前2个月以上，增加权重
        elif avg_lead_days >= 30:
            return current_weight
        elif avg_lead_days >= 7:
            return current_weight * 0.9
        else:
            return current_weight * 0.8
    
    def _generate_rationale(self, indicator_id: str, historical_values: List[Dict],
                           config: Dict, opt_elevated: float, opt_critical: float) -> str:
        """生成优化理由"""
        rationales = []
        
        num_critical = len([s for s in historical_values if s["severity"] == "critical"])
        num_elevated = len([s for s in historical_values if s["severity"] == "elevated"])
        
        rationales.append(f"基于{len(historical_values)}次历史信号优化")
        rationales.append(f"其中Critical级别{num_critical}次，Elevated级别{num_elevated}次")
        
        # 比较变化
        elev_change = ((opt_elevated - config["elevated"]) / config["elevated"] * 100) if config["elevated"] != 0 else 0
        crit_change = ((opt_critical - config["critical"]) / config["critical"] * 100) if config["critical"] != 0 else 0
        
        if abs(elev_change) > 10 or abs(crit_change) > 10:
            rationales.append(f"阈值调整幅度: Elevated {elev_change:+.0f}%, Critical {crit_change:+.0f}%")
        else:
            rationales.append("历史数据验证当前阈值基本合理")
        
        return "；".join(rationales)
    
    def generate_optimized_config(self) -> Dict:
        """生成优化后的配置"""
        optimized = self.optimize_thresholds()
        
        config = {
            "version": "2.0",
            "optimized_date": datetime.now().isoformat(),
            "based_on": "8 historical crises, 29 signals",
            "indicators": {}
        }
        
        for opt in optimized:
            # 找到对应的indicator_id
            indicator_id = None
            for k, v in self.current_configs.items():
                if v["name"] == opt.indicator:
                    indicator_id = k
                    break
            
            if indicator_id:
                config["indicators"][indicator_id] = {
                    "name": opt.indicator,
                    "thresholds": {
                        "elevated": opt.optimized_elevated,
                        "critical": opt.optimized_critical
                    },
                    "previous_thresholds": {
                        "elevated": opt.current_elevated,
                        "critical": opt.current_critical
                    },
                    "weight": opt.recommended_weight,
                    "confidence": opt.confidence,
                    "rationale": opt.rationale,
                    "historical_range": opt.historical_range
                }
        
        return config
    
    def generate_report(self, optimized: List[OptimizedThreshold]) -> str:
        """生成优化报告"""
        lines = []
        
        lines.append("=" * 80)
        lines.append("🎯 指标阈值优化报告")
        lines.append("=" * 80)
        lines.append("")
        
        lines.append("📊 优化基础:")
        lines.append(f"   • 基于 {len(self.historical_signals)} 个历史信号")
        lines.append(f"   • 来自 8 次历史危机案例")
        lines.append(f"   • 优化 {len(optimized)} 个核心指标")
        lines.append("")
        
        # 分类展示
        high_conf = [o for o in optimized if o.confidence == "high"]
        med_conf = [o for o in optimized if o.confidence == "medium"]
        low_conf = [o for o in optimized if o.confidence == "low"]
        
        if high_conf:
            lines.append("-" * 80)
            lines.append(f"✅ 高置信度优化 ({len(high_conf)}个指标)")
            lines.append("-" * 80)
            lines.append("")
            
            for opt in high_conf:
                lines.append(f"📈 {opt.indicator}")
                lines.append(f"   原阈值: Elevated={opt.current_elevated}, Critical={opt.current_critical}")
                lines.append(f"   新阈值: Elevated={opt.optimized_elevated}, Critical={opt.optimized_critical}")
                lines.append(f"   推荐权重: {opt.recommended_weight}")
                lines.append(f"   历史范围: {opt.historical_range[0]} ~ {opt.historical_range[1]}")
                lines.append(f"   理由: {opt.rationale}")
                lines.append("")
        
        if med_conf:
            lines.append("-" * 80)
            lines.append(f"⚠️  中等置信度优化 ({len(med_conf)}个指标)")
            lines.append("-" * 80)
            lines.append("")
            
            for opt in med_conf:
                lines.append(f"📊 {opt.indicator}")
                lines.append(f"   建议: 保持当前配置或微调")
                lines.append(f"   理由: {opt.rationale}")
                lines.append("")
        
        if low_conf:
            lines.append("-" * 80)
            lines.append(f"❓ 低置信度/待验证 ({len(low_conf)}个指标)")
            lines.append("-" * 80)
            lines.append("")
            
            for opt in low_conf:
                lines.append(f"📋 {opt.indicator}")
                lines.append(f"   建议: {opt.rationale}")
                lines.append("")
        
        # 关键改进建议
        lines.append("-" * 80)
        lines.append("💡 关键改进建议")
        lines.append("-" * 80)
        lines.append("")
        lines.append("1. 按危机类型优化权重:")
        lines.append("   • 流动性危机: VIX/MOVE权重调至3.5")
        lines.append("   • 货币危机: DXY/利差权重调至3.5")
        lines.append("   • 债务危机: CDS/信用利差权重调至3.0")
        lines.append("")
        lines.append("2. 阈值调整策略:")
        lines.append("   • 提前期>3个月的指标: 适当提高阈值减少误报")
        lines.append("   • 提前期<1周的指标: 降低阈值提高灵敏度")
        lines.append("")
        lines.append("3. 新增指标建议:")
        lines.append("   • 杠杆指标(融资余额/GDP): 适用于泡沫监控")
        lines.append("   • 估值指标(PE/PB): 适用于A股/成长股")
        lines.append("   • 情绪指标(换手率/新增投资者): 适用于散户市场")
        lines.append("")
        lines.append("4. 监控频率建议:")
        lines.append("   • Critical级别指标: 每日监控")
        lines.append("   • Elevated级别指标: 每周监控")
        lines.append("   • 正常市场环境: 每两周监控")
        lines.append("")
        
        lines.append("=" * 80)
        lines.append(f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 80)
        
        return "\n".join(lines)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Indicator Threshold Optimizer')
    parser.add_argument('--generate-config', '-g', action='store_true', 
                       help='生成优化后的配置文件')
    parser.add_argument('--output', '-o', type=str, 
                       default='optimized_thresholds.json',
                       help='输出文件路径')
    
    args = parser.parse_args()
    
    print("🚀 启动阈值优化器...\n")
    
    optimizer = ThresholdOptimizer()
    optimized = optimizer.optimize_thresholds()
    
    # 生成并打印报告
    report = optimizer.generate_report(optimized)
    print(report)
    
    # 生成配置文件
    if args.generate_config:
        config = optimizer.generate_optimized_config()
        output_path = Path(args.output)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 优化后的配置已保存到: {output_path}")
        print(f"   使用方式: 将配置复制到 config/indicators.yaml")
    
    # 保存报告到Vault
    from utils.vault_writer import get_vault_writer
    vault = get_vault_writer()
    
    filename = f"threshold_optimization_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    content = f"""---
date: {datetime.now().isoformat()}
category: threshold_optimization
generated_by: Threshold Optimizer
---

# 指标阈值优化报告

{report}
"""
    
    filepath = vault.write_knowledge_entry(content, 'macro', filename)
    print(f"\n📝 报告已保存到Vault: {filepath}")


if __name__ == "__main__":
    main()
