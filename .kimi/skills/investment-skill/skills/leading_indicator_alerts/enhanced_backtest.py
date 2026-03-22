"""
Enhanced Backtest System - 增强版回测系统

基于历史案例文件中的真实数据，进行更准确的回测验证
生成优化建议和阈值调整方案

使用方法:
    uv run python enhanced_backtest.py
"""

import sys
import yaml
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class HistoricalSignal:
    """历史信号数据"""
    indicator: str
    value: float
    date: str
    lead_days: int
    severity: str


@dataclass
class CrisisCase:
    """历史危机案例"""
    crisis_id: str
    name: str
    date: datetime
    severity: str
    crisis_type: str
    file_path: Path
    signals: List[HistoricalSignal] = field(default_factory=list)
    market_impact: Dict[str, float] = field(default_factory=dict)
    lessons: List[str] = field(default_factory=list)


class EnhancedBacktestEngine:
    """增强版回测引擎 - 从Vault案例文件读取真实数据"""
    
    def __init__(self):
        self.vault_path = Path.home() / "vault-notes" / "knowledge" / "investment" / "historical_patterns"
        self.crisis_cases = self._load_crisis_cases()
        self.indicator_configs = self._load_indicator_configs()
    
    def _load_crisis_cases(self) -> List[CrisisCase]:
        """从Vault加载历史案例"""
        cases = []
        
        if not self.vault_path.exists():
            print(f"⚠️  Vault路径不存在: {self.vault_path}")
            return cases
        
        for md_file in self.vault_path.glob("*.md"):
            try:
                case = self._parse_crisis_file(md_file)
                if case:
                    cases.append(case)
            except Exception as e:
                print(f"⚠️  解析文件失败 {md_file.name}: {e}")
        
        return sorted(cases, key=lambda x: x.date)
    
    def _parse_crisis_file(self, file_path: Path) -> Optional[CrisisCase]:
        """解析历史危机Markdown文件"""
        content = file_path.read_text(encoding='utf-8')
        
        if not content.startswith('---'):
            return None
        
        # 提取YAML frontmatter
        yaml_end = content.find('---', 3)
        if yaml_end == -1:
            return None
        
        try:
            frontmatter = yaml.safe_load(content[3:yaml_end])
            if 'date' in frontmatter and hasattr(frontmatter['date'], 'strftime'):
                crisis_date = frontmatter['date']
            else:
                crisis_date = datetime.strptime(str(frontmatter.get('date', '2000-01-01')), '%Y-%m-%d')
        except:
            crisis_date = datetime(2000, 1, 1)
        
        # 从文件名提取ID
        crisis_id = file_path.stem
        
        # 从内容提取信号数据
        signals = self._extract_signals_from_content(content, crisis_date)
        
        # 从内容提取市场影响
        market_impact = self._extract_market_impact(content)
        
        # 从内容提取经验教训
        lessons = self._extract_lessons(content)
        
        return CrisisCase(
            crisis_id=crisis_id,
            name=file_path.stem.replace('_', ' ').title(),
            date=crisis_date,
            severity=frontmatter.get('severity', 'normal'),
            crisis_type=frontmatter.get('crisis_type', 'unknown'),
            file_path=file_path,
            signals=signals,
            market_impact=market_impact,
            lessons=lessons
        )
    
    def _extract_signals_from_content(self, content: str, crisis_date: datetime) -> List[HistoricalSignal]:
        """从Markdown内容提取预警信号数据"""
        signals = []
        
        # 查找领先指标信号表格
        if "领先指标信号" in content or "领先指标" in content:
            lines = content.split('\n')
            in_table = False
            header_line = None
            
            for i, line in enumerate(lines):
                if "指标" in line and "|" in line and "危机前" in line:
                    in_table = True
                    header_line = line
                    continue
                
                if in_table and line.startswith('|') and '---' not in line:
                    cells = [c.strip() for c in line.split('|')[1:-1]]
                    if len(cells) >= 5:
                        try:
                            indicator_name = cells[0].replace('**', '').strip()
                            crisis_value = self._parse_value(cells[1])
                            normal_value = self._parse_value(cells[2])
                            change = self._parse_value(cells[3])
                            severity = self._parse_severity(cells[4])
                            
                            # 估算提前天数（基于内容中的时间线）
                            lead_days = self._estimate_lead_days(content, indicator_name)
                            
                            signal_date = crisis_date - timedelta(days=lead_days)
                            
                            signals.append(HistoricalSignal(
                                indicator=indicator_name,
                                value=crisis_value,
                                date=signal_date.strftime('%Y-%m-%d'),
                                lead_days=lead_days,
                                severity=severity
                            ))
                        except Exception as e:
                            continue
                
                if in_table and line.strip() == '' and i > 0 and '---' not in lines[i-1]:
                    in_table = False
        
        # 查找实际信号时间点
        timeline_signals = self._extract_timeline_signals(content, crisis_date)
        signals.extend(timeline_signals)
        
        return signals
    
    def _parse_value(self, text: str) -> float:
        """解析数值"""
        text = text.replace('%', '').replace('bp', '').replace(',', '').strip()
        # 提取数字
        match = re.search(r'-?\d+\.?\d*', text)
        if match:
            return float(match.group())
        return 0.0
    
    def _parse_severity(self, text: str) -> str:
        """解析严重程度"""
        if '🔴' in text or 'Critical' in text or '严重' in text:
            return 'critical'
        elif '🟠' in text or 'Elevated' in text or '中等' in text:
            return 'elevated'
        return 'normal'
    
    def _estimate_lead_days(self, content: str, indicator: str) -> int:
        """根据内容估算提前天数"""
        # 查找时间线描述
        if "24-48小时" in content or "24-48 hours" in content:
            return 2
        elif "48-72小时" in content:
            return 3
        elif "1-3天" in content or "1-3 days" in content:
            return 3
        elif "3-7天" in content:
            return 5
        elif "1周" in content or "1 week" in content:
            return 7
        elif "2周" in content or "2 weeks" in content:
            return 14
        elif "1个月" in content or "1 month" in content:
            return 30
        elif "3个月" in content or "3 months" in content:
            return 90
        elif "6个月" in content or "6 months" in content:
            return 180
        elif "12个月" in content or "12 months" in content:
            return 365
        return 30  # 默认30天
    
    def _extract_timeline_signals(self, content: str, crisis_date: datetime) -> List[HistoricalSignal]:
        """从时间线提取信号"""
        signals = []
        
        # 查找时间线部分
        if "时间线" in content or "Timeline" in content:
            lines = content.split('\n')
            for line in lines:
                # 匹配日期格式如 "7月31日" 或 "2024-07-31"
                date_match = re.search(r'(\d{4})?[-年]?\s*(\d{1,2})[月/-](\d{1,2})', line)
                if date_match:
                    try:
                        if date_match.group(1):
                            year = int(date_match.group(1))
                        else:
                            year = crisis_date.year
                        month = int(date_match.group(2))
                        day = int(date_match.group(3))
                        
                        signal_date = datetime(year, month, day)
                        lead_days = (crisis_date - signal_date).days
                        
                        # 提取指标名称
                        if any(keyword in line for keyword in ['利差', 'DXY', 'VIX', 'MOVE', '收益率', 'CDS']):
                            indicator = self._extract_indicator_name(line)
                            if indicator:
                                signals.append(HistoricalSignal(
                                    indicator=indicator,
                                    value=0,  # 未知
                                    date=signal_date.strftime('%Y-%m-%d'),
                                    lead_days=max(0, lead_days),
                                    severity='elevated'
                                ))
                    except:
                        continue
        
        return signals
    
    def _extract_indicator_name(self, line: str) -> Optional[str]:
        """从文本提取指标名称"""
        keywords = {
            '美日利差': 'us_jp_spread',
            'DXY': 'dxy',
            '美元指数': 'dxy',
            'VIX': 'vix',
            'MOVE': 'move',
            '收益率曲线': 'yield_curve',
            '利差': 'credit_spread',
            'CDS': 'cds',
            'TED': 'ted',
        }
        
        for keyword, indicator in keywords.items():
            if keyword in line:
                return indicator
        return None
    
    def _extract_market_impact(self, content: str) -> Dict[str, float]:
        """提取市场影响数据"""
        impact = {}
        
        # 查找市场表现表格
        patterns = [
            (r'日经.*?([\-]?\d+\.?\d*)%?', 'nikkei'),
            (r'纳斯达克.*?([\-]?\d+\.?\d*)%?', 'nasdaq'),
            (r'标普.*?([\-]?\d+\.?\d*)%?', 'sp500'),
            (r'黄金.*?([\-]?\d+\.?\d*)%?', 'gold'),
            (r'半导体.*?([\-]?\d+\.?\d*)%?', 'semiconductor'),
        ]
        
        for pattern, key in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                try:
                    impact[key] = float(match.group(1))
                except:
                    pass
        
        return impact
    
    def _extract_lessons(self, content: str) -> List[str]:
        """提取经验教训"""
        lessons = []
        
        # 查找经验教训部分
        if "经验教训" in content or "lessons" in content.lower():
            lines = content.split('\n')
            in_lessons = False
            for line in lines:
                if "经验教训" in line or "核心教训" in line:
                    in_lessons = True
                    continue
                if in_lessons and (line.strip().startswith('-') or line.strip().startswith('✅') or line.strip().startswith('❌')):
                    lesson = line.strip()[1:].strip()
                    if lesson and len(lesson) > 10:
                        lessons.append(lesson)
                if in_lessons and line.strip().startswith('#') and "经验教训" not in line:
                    in_lessons = False
        
        return lessons[:5]
    
    def _load_indicator_configs(self) -> Dict:
        """加载指标配置"""
        return {
            "us_jp_spread": {
                "name": "美日2年期利差",
                "current_thresholds": {"elevated": 4.0, "critical": 3.0},
                "applicable_types": ["yen_carry_trade_unwind", "currency_crisis"]
            },
            "dxy": {
                "name": "美元指数DXY",
                "current_thresholds": {"elevated": 105, "critical": 107},
                "applicable_types": ["strong_dollar_shock", "currency_crisis"]
            },
            "vix": {
                "name": "VIX波动率",
                "current_thresholds": {"elevated": 28, "critical": 35},
                "applicable_types": ["liquidity_crisis", "financial_crisis"]
            },
            "move": {
                "name": "MOVE美债波动率",
                "current_thresholds": {"elevated": 120, "critical": 140},
                "applicable_types": ["liquidity_crisis", "financial_crisis"]
            },
            "yield_curve": {
                "name": "收益率曲线(10Y-2Y)",
                "current_thresholds": {"elevated": 0.5, "critical": 0.0},
                "applicable_types": ["financial_crisis", "recession"]
            },
            "credit_spread": {
                "name": "信用利差",
                "current_thresholds": {"elevated": 150, "critical": 200},
                "applicable_types": ["financial_crisis", "eu_debt_crisis"]
            },
            "cds": {
                "name": "CDS利差",
                "current_thresholds": {"elevated": 300, "critical": 500},
                "applicable_types": ["eu_debt_crisis", "sovereign_debt_crisis"]
            }
        }
    
    def run_analysis(self) -> Dict:
        """运行分析"""
        print("=" * 80)
        print("🔬 增强版回测分析 - 基于历史案例文件")
        print("=" * 80)
        print()
        
        print(f"📚 成功加载 {len(self.crisis_cases)} 个历史危机案例:")
        for case in self.crisis_cases:
            print(f"   - {case.name} ({case.date.strftime('%Y-%m-%d')}) - {len(case.signals)}个信号")
        print()
        
        # 分析每个案例的信号覆盖
        analysis = self._analyze_signal_coverage()
        
        # 生成优化建议
        recommendations = self._generate_optimization_recommendations()
        
        # 统计信息
        stats = self._calculate_statistics()
        
        return {
            "cases": self.crisis_cases,
            "analysis": analysis,
            "recommendations": recommendations,
            "statistics": stats
        }
    
    def _analyze_signal_coverage(self) -> Dict:
        """分析信号覆盖情况"""
        analysis = {}
        
        for case in self.crisis_cases:
            case_analysis = {
                "total_signals": len(case.signals),
                "critical_signals": len([s for s in case.signals if s.severity == 'critical']),
                "elevated_signals": len([s for s in case.signals if s.severity == 'elevated']),
                "avg_lead_time": sum(s.lead_days for s in case.signals) / len(case.signals) if case.signals else 0,
                "earliest_warning": min(s.lead_days for s in case.signals) if case.signals else None,
                "indicators_present": list(set(s.indicator for s in case.signals))
            }
            analysis[case.crisis_id] = case_analysis
        
        return analysis
    
    def _generate_optimization_recommendations(self) -> List[str]:
        """生成优化建议"""
        recommendations = []
        
        # 1. 指标覆盖分析
        all_indicators = set()
        for case in self.crisis_cases:
            for signal in case.signals:
                all_indicators.add(signal.indicator)
        
        recommendations.append(f"📊 数据覆盖: 共识别 {len(all_indicators)} 种不同的预警信号")
        
        # 2. 按危机类型分组建议
        crisis_types = {}
        for case in self.crisis_cases:
            ctype = case.crisis_type
            if ctype not in crisis_types:
                crisis_types[ctype] = []
            crisis_types[ctype].append(case)
        
        recommendations.append("\n🏷️ 按危机类型的指标建议:")
        
        for ctype, cases in crisis_types.items():
            indicators = set()
            for case in cases:
                for signal in case.signals:
                    indicators.add(signal.indicator)
            
            if indicators:
                recommendations.append(f"   • {ctype}: 关注 {', '.join(list(indicators)[:3])}")
        
        # 3. 时间窗口建议
        lead_times = []
        for case in self.crisis_cases:
            for signal in case.signals:
                lead_times.append(signal.lead_days)
        
        if lead_times:
            avg_lead = sum(lead_times) / len(lead_times)
            min_lead = min(lead_times)
            max_lead = max(lead_times)
            
            recommendations.append(f"\n⏰ 预警时间窗口分析:")
            recommendations.append(f"   • 平均提前: {avg_lead:.0f}天")
            recommendations.append(f"   • 最早预警: {min_lead}天")
            recommendations.append(f"   • 最晚预警: {max_lead}天")
            recommendations.append(f"   • 建议监控频率: 至少每周一次")
        
        # 4. 系统改进建议
        recommendations.append("\n💡 系统改进建议:")
        recommendations.append("   1. 基于历史案例调整指标阈值")
        recommendations.append("   2. 增加危机类型自动识别功能")
        recommendations.append("   3. 建立指标组合权重优化算法")
        recommendations.append("   4. 引入更多微观指标(杠杆、估值等)")
        
        return recommendations
    
    def _calculate_statistics(self) -> Dict:
        """计算统计信息"""
        stats = {
            "total_cases": len(self.crisis_cases),
            "total_signals": sum(len(c.signals) for c in self.crisis_cases),
            "severity_distribution": {"critical": 0, "elevated": 0, "normal": 0},
            "crisis_types": {}
        }
        
        for case in self.crisis_cases:
            # 严重程度分布
            for signal in case.signals:
                if signal.severity in stats["severity_distribution"]:
                    stats["severity_distribution"][signal.severity] += 1
            
            # 危机类型统计
            ctype = case.crisis_type
            if ctype not in stats["crisis_types"]:
                stats["crisis_types"][ctype] = 0
            stats["crisis_types"][ctype] += 1
        
        return stats
    
    def generate_report(self, analysis: Dict) -> str:
        """生成分析报告"""
        lines = []
        
        lines.append("=" * 80)
        lines.append("📊 基于历史案例的指标优化分析报告")
        lines.append("=" * 80)
        lines.append("")
        
        # 总体统计
        stats = analysis["statistics"]
        lines.append(f"📈 总体统计:")
        lines.append(f"   • 分析案例数: {stats['total_cases']}")
        lines.append(f"   • 识别信号数: {stats['total_signals']}")
        lines.append(f"   • 严重程度分布: Critical={stats['severity_distribution']['critical']}, "
                    f"Elevated={stats['severity_distribution']['elevated']}")
        lines.append("")
        
        # 危机类型统计
        lines.append("🏷️ 危机类型分布:")
        for ctype, count in stats["crisis_types"].items():
            lines.append(f"   • {ctype}: {count}个案例")
        lines.append("")
        
        # 详细分析
        lines.append("-" * 80)
        lines.append("📋 各案例详细分析")
        lines.append("-" * 80)
        lines.append("")
        
        for crisis_id, case_analysis in analysis["analysis"].items():
            case = next(c for c in analysis["cases"] if c.crisis_id == crisis_id)
            lines.append(f"🔴 {case.name}")
            lines.append(f"   信号数: {case_analysis['total_signals']} "
                        f"(Critical: {case_analysis['critical_signals']}, "
                        f"Elevated: {case_analysis['elevated_signals']})")
            lines.append(f"   平均提前: {case_analysis['avg_lead_time']:.0f}天")
            if case_analysis['earliest_warning']:
                lines.append(f"   最早预警: {case_analysis['earliest_warning']}天")
            if case_analysis['indicators_present']:
                lines.append(f"   涉及指标: {', '.join(case_analysis['indicators_present'])}")
            if case.market_impact:
                impacts = [f"{k}: {v}%" for k, v in list(case.market_impact.items())[:3]]
                lines.append(f"   市场影响: {', '.join(impacts)}")
            lines.append("")
        
        # 优化建议
        lines.append("-" * 80)
        lines.append("💡 优化建议")
        lines.append("-" * 80)
        lines.append("")
        
        for rec in analysis["recommendations"]:
            lines.append(rec)
        
        lines.append("")
        lines.append("=" * 80)
        lines.append(f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 80)
        
        return "\n".join(lines)


def main():
    """主函数"""
    print("🚀 启动增强版回测分析系统...\n")
    
    engine = EnhancedBacktestEngine()
    analysis = engine.run_analysis()
    
    # 生成并打印报告
    report = engine.generate_report(analysis)
    print(report)
    
    # 保存报告到Vault
    from utils.vault_writer import get_vault_writer
    vault = get_vault_writer()
    
    filename = f"enhanced_backtest_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    content = f"""---
date: {datetime.now().isoformat()}
category: backtest_analysis
generated_by: Enhanced Backtest Engine
total_cases: {analysis['statistics']['total_cases']}
total_signals: {analysis['statistics']['total_signals']}
---

# 增强版回测分析报告

{report}
"""
    
    filepath = vault.write_knowledge_entry(content, 'macro', filename)
    print(f"\n📝 报告已保存到Vault: {filepath}")


if __name__ == "__main__":
    main()
