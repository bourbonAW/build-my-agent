"""
Historical Pattern Matcher - 历史模式智能匹配系统
从Vault知识库读取历史复盘，进行智能匹配
"""
import sys
import re
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class HistoricalPattern:
    """历史模式数据结构"""
    pattern_id: str
    name: str
    date: str
    severity: str  # normal, elevated, critical, extreme
    crisis_type: str
    indicators: Dict[str, Dict]  # 指标阈值
    timeline: Dict[str, str]  # 时间线
    market_impact: Dict[str, float]  # 市场影响
    lessons_learned: List[str]  # 经验教训
    file_path: str


class HistoricalPatternManager:
    """
    历史模式管理器
    
    功能：
    1. 从Vault读取历史复盘笔记
    2. 解析YAML frontmatter
    3. 提取关键指标阈值
    4. 智能匹配当前市场状况
    5. 生成详细的匹配报告
    """
    
    def __init__(self, vault_path: Optional[str] = None):
        """初始化历史模式管理器"""
        if vault_path is None:
            vault_path = Path.home() / "vault-notes"
        
        self.vault_path = Path(vault_path)
        self.patterns_dir = self.vault_path / "knowledge" / "investment" / "historical_patterns"
        
        # 内置模式库（作为fallback）
        self.builtin_patterns = self._load_builtin_patterns()
        
        # 从Vault加载的模式
        self.vault_patterns = self._load_vault_patterns()
        
        # 合并所有模式
        self.all_patterns = {**self.builtin_patterns, **self.vault_patterns}
    
    def _load_builtin_patterns(self) -> Dict[str, HistoricalPattern]:
        """加载内置历史模式（作为fallback）"""
        patterns = {}
        
        # 2024年8月日元套利 unwind
        patterns["2024_08_yen_carry"] = HistoricalPattern(
            pattern_id="2024_08_yen_carry",
            name="2024年8月日元套利交易 unwind 危机",
            date="2024-08-05",
            severity="high",
            crisis_type="yen_carry_trade_unwind",
            indicators={
                "us_jp_spread_2y": {"threshold": 3.5, "operator": "<", "weight": 3.0},
                "usdjpy_change": {"threshold": -1.5, "operator": "<", "weight": 2.5},
                "jgb_10y": {"threshold": 0.8, "operator": ">", "weight": 2.0},
                "vix": {"threshold": 25, "operator": ">", "weight": 1.5},
                "move": {"threshold": 110, "operator": ">", "weight": 1.5},
            },
            timeline={
                "warning": "24-48 hours before",
                "crash": "1-3 days",
                "recovery": "1-2 weeks"
            },
            market_impact={
                "nasdaq": -8.0,
                "nikkei": -12.4,
                "semiconductor": -15.0,
                "gold": 5.0
            },
            lessons_learned=[
                "美日利差<3.5% + 日元快速升值 = 危机信号",
                "不要试图抄底，等待VIX回落",
                "黄金作为对冲有效"
            ],
            file_path="builtin"
        )
        
        # 2022年强美元冲击
        patterns["2022_strong_dollar"] = HistoricalPattern(
            pattern_id="2022_strong_dollar",
            name="2022年强美元冲击",
            date="2022-01-01",
            severity="high",
            crisis_type="strong_dollar_shock",
            indicators={
                "dxy": {"threshold": 105, "operator": ">", "weight": 3.0},
                "us_2y_yield": {"threshold": 3.0, "operator": ">", "weight": 2.0},
                "move": {"threshold": 100, "operator": ">", "weight": 1.5},
                "yield_curve_spread": {"threshold": 0.5, "operator": ">", "weight": 1.0},
            },
            timeline={
                "buildup": "3-6 months",
                "crash": "1-2 months", 
                "bottom": "2-3 months",
                "recovery": "3-6 months"
            },
            market_impact={
                "nasdaq": -33.0,
                "emerging_markets": -25.0,
                "bitcoin": -64.0,
                "gold": -0.3
            },
            lessons_learned=[
                "DXY>105是减仓信号",
                "科技股在强美元环境中最脆弱",
                "黄金相对抗跌，有色受益"
            ],
            file_path="builtin"
        )
        
        # 2020年3月疫情流动性危机
        patterns["2020_covid_crisis"] = HistoricalPattern(
            pattern_id="2020_covid_crisis",
            name="2020年3月新冠疫情流动性危机",
            date="2020-03-01",
            severity="extreme",
            crisis_type="liquidity_crisis",
            indicators={
                "vix": {"threshold": 50, "operator": ">", "weight": 3.0},
                "move": {"threshold": 120, "operator": ">", "weight": 3.0},
                "sofr_ois_spread": {"threshold": 30, "operator": ">", "weight": 2.5},
                "ted_spread": {"threshold": 40, "operator": ">", "weight": 2.0},
                "credit_spread_ig": {"threshold": 200, "operator": ">", "weight": 2.0},
                "credit_spread_hy": {"threshold": 700, "operator": ">", "weight": 2.0},
            },
            timeline={
                "warning": "VIX>25",
                "severe": "VIX>35",
                "extreme": "VIX>50",
                "bottom": "VIX peak + Fed action"
            },
            market_impact={
                "sp500": -34.0,
                "nasdaq": -30.0,
                "crude_oil": -55.0,
                "bitcoin": -50.0
            },
            lessons_learned=[
                "流动性危机中现金为王",
                "所有资产一起跌(包括黄金初期)",
                "政策底=市场底",
                "分批抄底，不要一次性"
            ],
            file_path="builtin"
        )
        
        # 2008年金融危机
        patterns["2008_financial_crisis"] = HistoricalPattern(
            pattern_id="2008_financial_crisis",
            name="2008年金融危机",
            date="2008-09-01",
            severity="extreme",
            crisis_type="financial_crisis",
            indicators={
                "yield_curve_inverted": {"threshold": 0, "operator": "<", "weight": 3.0},
                "libor_ois_spread": {"threshold": 50, "operator": ">", "weight": 3.0},
                "credit_spread": {"threshold": 200, "operator": ">", "weight": 2.5},
                "ted_spread": {"threshold": 100, "operator": ">", "weight": 2.5},
                "vix": {"threshold": 40, "operator": ">", "weight": 2.0},
                "bank_index_underperformance": {"threshold": -20, "operator": "<", "weight": 1.5},
            },
            timeline={
                "warning": "Yield curve inversion (6-18 months ahead)",
                "buildup": "2007-2008",
                "explosion": "September 2008",
                "bottom": "March 2009"
            },
            market_impact={
                "sp500": -57.0,
                "nasdaq": -55.0,
                "banking_sector": -85.0,
                "emerging_markets": -60.0
            },
            lessons_learned=[
                "收益率曲线倒挂100%预示衰退",
                "流动性危机比估值调整更严重",
                "需要政府救助才能结束",
                "金融股永远不能抄底"
            ],
            file_path="builtin"
        )
        
        # 2018年贸易战震荡
        patterns["2018_trade_war"] = HistoricalPattern(
            pattern_id="2018_trade_war",
            name="2018年中美贸易战震荡",
            date="2018-03-01",
            severity="elevated",
            crisis_type="trade_war",
            indicators={
                "vix": {"threshold": 20, "operator": ">", "weight": 2.0},
                "china_pmi": {"threshold": 50, "operator": "<", "weight": 2.0},
                "copper": {"threshold": -10, "operator": "<", "weight": 1.5, "metric": "change_pct"},
            },
            timeline={
                "escalation": "Throughout 2018",
                "bottom": "December 2018",
                "truce": "Early 2019"
            },
            market_impact={
                "sp500": -20.0,
                "china_equities": -30.0,
                "semiconductor": -25.0
            },
            lessons_learned=[
                "贸易战影响渐进式",
                "科技股和出口股最脆弱",
                "需要关注政策新闻"
            ],
            file_path="builtin"
        )
        
        # 2021年Archegos爆仓
        patterns["2021_archegos"] = HistoricalPattern(
            pattern_id="2021_archegos",
            name="2021年Archegos爆仓事件",
            date="2021-03-26",
            severity="elevated",
            crisis_type="idiosyncratic_risk",
            indicators={
                "concentrated_liquidation": {"threshold": 1, "operator": ">=", "weight": 2.0},
                "prime_brokerage_stress": {"threshold": 1, "operator": ">=", "weight": 2.0},
            },
            timeline={
                "event": "Single day",
                "impact": "1-2 weeks",
                "recovery": "1 month"
            },
            market_impact={
                "affected_stocks": -50.0,
                "broader_market": -2.0
            },
            lessons_learned=[
                "杠杆是双刃剑",
                "集中度风险",
                "单一事件不传染整个市场"
            ],
            file_path="builtin"
        )
        
        return patterns
    
    def _load_vault_patterns(self) -> Dict[str, HistoricalPattern]:
        """从Vault知识库加载历史模式"""
        patterns = {}
        
        if not self.patterns_dir.exists():
            return patterns
        
        # 扫描所有历史模式文件
        for md_file in self.patterns_dir.glob("*.md"):
            try:
                pattern = self._parse_pattern_file(md_file)
                if pattern:
                    patterns[pattern.pattern_id] = pattern
            except Exception as e:
                print(f"⚠️  Error parsing {md_file}: {e}")
        
        return patterns
    
    def _parse_pattern_file(self, file_path: Path) -> Optional[HistoricalPattern]:
        """解析单个历史模式Markdown文件"""
        content = file_path.read_text(encoding='utf-8')
        
        # 提取YAML frontmatter
        if not content.startswith('---'):
            return None
        
        yaml_end = content.find('---', 3)
        if yaml_end == -1:
            return None
        
        try:
            frontmatter = yaml.safe_load(content[3:yaml_end])
            # Convert datetime objects to strings
            if 'date' in frontmatter and hasattr(frontmatter['date'], 'strftime'):
                frontmatter['date'] = frontmatter['date'].strftime('%Y-%m-%d')
        except Exception as e:
            print(f"⚠️  YAML parsing error: {e}")
            return None
        
        # 构建pattern_id
        date_str = frontmatter.get('date', '')[:7].replace('-', '_')
        crisis_type = frontmatter.get('crisis_type', 'unknown')
        pattern_id = f"{date_str}_{crisis_type}"
        
        # 从正文提取指标阈值（简化实现）
        indicators = self._extract_indicators_from_content(content)
        
        # 从正文提取市场影响
        market_impact = self._extract_market_impact(content)
        
        # 从正文提取经验教训
        lessons = self._extract_lessons(content)
        
        return HistoricalPattern(
            pattern_id=pattern_id,
            name=file_path.stem.replace('_', ' ').title(),
            date=frontmatter.get('date', ''),
            severity=frontmatter.get('severity', 'normal'),
            crisis_type=crisis_type,
            indicators=indicators,
            timeline=frontmatter.get('timeline', {}),
            market_impact=market_impact,
            lessons_learned=lessons,
            file_path=str(file_path)
        )
    
    def _extract_indicators_from_content(self, content: str) -> Dict:
        """从Markdown内容提取指标阈值"""
        indicators = {}
        
        # 查找指标表格
        if "| 指标 |" in content:
            lines = content.split('\n')
            in_table = False
            for line in lines:
                if "| 指标 |" in line:
                    in_table = True
                    continue
                if in_table and line.startswith('|') and 'threshold' not in line.lower():
                    # 解析表格行
                    cells = [c.strip() for c in line.split('|')[1:-1]]
                    if len(cells) >= 4:
                        indicator_name = cells[0]
                        try:
                            threshold = float(cells[2].replace('%', '').replace('bp', ''))
                            indicators[indicator_name.lower().replace(' ', '_')] = {
                                "threshold": threshold,
                                "operator": ">" if " elevate" in line.lower() or " critical" in line.lower() else "<",
                                "weight": 2.0
                            }
                        except:
                            pass
        
        return indicators
    
    def _extract_market_impact(self, content: str) -> Dict:
        """提取市场影响数据"""
        impact = {}
        
        # 查找市场表现表格
        patterns = [
            (r"标普500.*?(\-?\d+\.?\d*)%", "sp500"),
            (r"纳斯达克.*?(\-?\d+\.?\d*)%", "nasdaq"),
            (r"日经.*?(\-?\d+\.?\d*)%", "nikkei"),
            (r"黄金.*?(\-?\d+\.?\d*)%", "gold"),
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
        if "经验教训" in content or "lessons_learned" in content.lower():
            # 提取 bullet points
            lines = content.split('\n')
            in_lessons = False
            for line in lines:
                if "经验教训" in line or "lessons" in line.lower():
                    in_lessons = True
                    continue
                if in_lessons and line.strip().startswith('-') or line.strip().startswith('✅'):
                    lesson = line.strip()[1:].strip()
                    if lesson and len(lesson) > 10:
                        lessons.append(lesson)
        
        return lessons[:5]  # 最多5条
    
    def match_current_conditions(self, current_signals: List[Dict]) -> List[Tuple[str, float, str]]:
        """
        匹配当前市场状况与历史模式
        
        Args:
            current_signals: 当前指标信号列表
            
        Returns:
            List of (pattern_name, match_score, description)
        """
        matches = []
        
        # 转换当前信号为字典
        current_dict = {s.get('indicator_name', '').lower().replace(' ', '_'): s 
                       for s in current_signals}
        
        for pattern_id, pattern in self.all_patterns.items():
            score = self._calculate_match_score(pattern, current_dict)
            
            if score > 0.3:  # 阈值30%
                description = self._generate_match_description(pattern, score)
                matches.append((pattern.name, score, description))
        
        # 按匹配度排序
        matches.sort(key=lambda x: x[1], reverse=True)
        
        return matches
    
    def _calculate_match_score(self, pattern: HistoricalPattern, 
                               current: Dict[str, Dict]) -> float:
        """计算模式匹配分数"""
        if not pattern.indicators:
            return 0.0
        
        total_weight = 0.0
        matched_weight = 0.0
        
        for indicator_key, threshold_config in pattern.indicators.items():
            weight = threshold_config.get('weight', 1.0)
            total_weight += weight
            
            # 查找匹配的当前指标
            for current_key, current_signal in current.items():
                if indicator_key in current_key or current_key in indicator_key:
                    # 检查是否触发阈值
                    current_value = current_signal.get('current_value', 0)
                    threshold = threshold_config.get('threshold', 0)
                    operator = threshold_config.get('operator', '>')
                    
                    triggered = False
                    if operator == '>' and current_value > threshold:
                        triggered = True
                    elif operator == '<' and current_value < threshold:
                        triggered = True
                    
                    if triggered:
                        matched_weight += weight
                    break
        
        return matched_weight / total_weight if total_weight > 0 else 0.0
    
    def _generate_match_description(self, pattern: HistoricalPattern, score: float) -> str:
        """生成匹配描述"""
        severity_emoji = {
            "normal": "🟢",
            "elevated": "🟡", 
            "critical": "🔴",
            "extreme": "🚨"
        }
        
        # 获取关键影响
        key_impacts = []
        if pattern.market_impact:
            sorted_impacts = sorted(pattern.market_impact.items(), 
                                   key=lambda x: abs(x[1]), reverse=True)[:2]
            for asset, impact in sorted_impacts:
                key_impacts.append(f"{asset}: {impact:+.1f}%")
        
        impact_str = ", ".join(key_impacts) if key_impacts else "详见历史复盘"
        
        # 获取关键教训
        key_lesson = pattern.lessons_learned[0] if pattern.lessons_learned else ""
        
        description = f"""
{severity_emoji.get(pattern.severity, '⚪')} 匹配度: {score*100:.1f}%
时间: {pattern.date} | 严重程度: {pattern.severity.upper()}

历史影响:
  {impact_str}

核心教训:
  {key_lesson}

建议行动:
  {self._get_action_advice(pattern.severity)}
"""
        return description
    
    def _get_action_advice(self, severity: str) -> str:
        """根据严重程度给出建议"""
        advice = {
            "normal": "维持配置，保持警惕",
            "elevated": "减仓20-30%，增配对冲资产",
            "critical": "减仓50%以上，现金为王",
            "extreme": "清仓权益资产，等待危机结束"
        }
        return advice.get(severity, "密切关注")
    
    def get_pattern_details(self, pattern_name: str) -> Optional[HistoricalPattern]:
        """获取特定模式的详细信息"""
        for pattern in self.all_patterns.values():
            if pattern.name == pattern_name or pattern.pattern_id == pattern_name:
                return pattern
        return None
    
    def list_all_patterns(self) -> List[Tuple[str, str, str]]:
        """列出所有可用模式"""
        return [(p.pattern_id, p.name, p.severity) for p in self.all_patterns.values()]


# 便捷函数
def get_pattern_manager() -> HistoricalPatternManager:
    """获取历史模式管理器实例"""
    return HistoricalPatternManager()


def match_historical_patterns(current_signals: List[Dict]) -> List[Tuple[str, float, str]]:
    """快速匹配历史模式"""
    manager = get_pattern_manager()
    return manager.match_current_conditions(current_signals)


if __name__ == "__main__":
    # 测试
    manager = HistoricalPatternManager()
    
    print("📚 Available Historical Patterns:")
    for pid, name, severity in manager.list_all_patterns():
        print(f"  - {name} ({severity})")
    
    print(f"\n✅ Total patterns: {len(manager.all_patterns)}")
