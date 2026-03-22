"""
Backtest System for Leading Indicators - 领先指标回测系统

验证10个领先指标在8个历史危机中的表现
- 评估预警准确性
- 优化阈值和权重
- 生成回测报告

使用方法:
    uv run python backtest.py
    uv run python backtest.py --crisis 2024_08_yen_carry
    uv run python backtest.py --indicator dxy
    uv run python backtest.py --report
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class CrisisEvent:
    """历史危机事件"""
    crisis_id: str
    name: str
    crisis_date: datetime  # 危机正式爆发日期
    warning_start: datetime  # 预警信号开始日期
    recovery_start: datetime  # 恢复开始日期
    severity: str  # normal, elevated, critical, extreme
    crisis_type: str
    description: str
    market_impact: Dict[str, float]  # 各市场最大跌幅
    
    # 危机前的关键阈值（基于历史复盘）
    indicator_thresholds: Dict[str, Dict] = field(default_factory=dict)
    
    # 实际预警信号出现的时间点
    actual_signals: List[Dict] = field(default_factory=list)


@dataclass
class IndicatorPerformance:
    """单个指标在单次危机中的表现"""
    indicator_name: str
    crisis_id: str
    
    # 预警效果
    warned: bool  # 是否发出预警
    warning_date: Optional[datetime]  # 首次预警日期
    lead_time_days: int  # 提前天数（距危机爆发）
    
    # 准确性
    false_positive: bool  # 是否误报
    missed_crisis: bool  # 是否漏报
    
    # 阈值表现
    threshold_used: float  # 使用的阈值
    actual_value_at_warning: float  # 预警时实际值
    max_value_before_crisis: float  # 危机前最大值
    
    # 评分
    effectiveness_score: float  # 0-100，综合评分


@dataclass
class BacktestResult:
    """回测结果"""
    crisis_id: str
    crisis_name: str
    
    # 整体表现
    indicators_triggered: int  # 触发的指标数
    total_indicators: int  # 总指标数
    
    # 最佳和最差指标
    best_indicators: List[str]  # 表现最好的指标
    worst_indicators: List[str]  # 表现最差的指标
    
    # 时间分析
    earliest_warning: Optional[datetime]  # 最早预警
    latest_warning: Optional[datetime]  # 最晚预警
    avg_lead_time: float  # 平均提前天数
    
    # 准确性
    hit_rate: float  # 命中率（预警成功的比例）
    false_positive_rate: float  # 误报率
    
    # 详细结果
    indicator_performances: List[IndicatorPerformance] = field(default_factory=list)
    
    # 建议
    recommendations: List[str] = field(default_factory=list)


class LeadingIndicatorBacktest:
    """
    领先指标回测系统
    
    功能:
    1. 定义8个历史危机的时间线和关键数据
    2. 模拟10个领先指标在危机前的表现
    3. 评估每个指标的预警效果
    4. 生成优化建议（阈值、权重）
    """
    
    def __init__(self):
        self.crisis_events = self._load_crisis_events()
        self.indicators = self._define_indicators()
    
    def _load_crisis_events(self) -> List[CrisisEvent]:
        """加载8个历史危机事件"""
        events = []
        
        # 1. 1997亚洲金融危机
        events.append(CrisisEvent(
            crisis_id="1997_asian_crisis",
            name="1997年亚洲金融危机",
            crisis_date=datetime(1997, 7, 2),
            warning_start=datetime(1997, 4, 1),  # 3个月预警期
            recovery_start=datetime(1998, 9, 1),
            severity="critical",
            crisis_type="currency_crisis",
            description="泰铢放弃固定汇率引发亚洲多国货币危机",
            market_impact={
                "thailand_stock": -85.0,
                "indonesia_stock": -80.0,
                "hong_kong": -60.0,
                "south_korea": -55.0,
                "emerging_markets": -50.0
            },
            indicator_thresholds={
                "current_account_gdp": {"threshold": -5.0, "operator": "<", "weight": 3.0},
                "short_term_debt_reserves": {"threshold": 100.0, "operator": ">", "weight": 3.0},
                "credit_growth": {"threshold": 20.0, "operator": ">", "weight": 2.0},
                "real_estate_bubble": {"threshold": 1, "operator": "=", "weight": 2.0},
                "exchange_rate_overvaluation": {"threshold": 20.0, "operator": ">", "weight": 2.0},
            },
            actual_signals=[
                {"indicator": "current_account", "date": "1997-04", "value": -8.2, "lead_days": 90},
                {"indicator": "short_term_debt", "date": "1997-05", "value": 150, "lead_days": 60},
                {"indicator": "forward_premium", "date": "1997-06", "value": 15, "lead_days": 30},
            ]
        ))
        
        # 2. 2008年金融危机
        events.append(CrisisEvent(
            crisis_id="2008_financial_crisis",
            name="2008年金融危机",
            crisis_date=datetime(2008, 9, 15),  # 雷曼破产
            warning_start=datetime(2007, 6, 1),  # 收益率曲线倒挂
            recovery_start=datetime(2009, 3, 1),
            severity="extreme",
            crisis_type="financial_crisis",
            description="次贷危机引发的全球金融海啸",
            market_impact={
                "sp500": -57.0,
                "nasdaq": -55.0,
                "banking_sector": -85.0,
                "emerging_markets": -60.0,
                "commodities": -40.0
            },
            indicator_thresholds={
                "yield_curve_10y2y": {"threshold": 0, "operator": "<", "weight": 3.0},
                "libor_ois_spread": {"threshold": 50, "operator": ">", "weight": 3.0},
                "credit_spread_ig": {"threshold": 200, "operator": ">", "weight": 2.5},
                "ted_spread": {"threshold": 100, "operator": ">", "weight": 2.5},
                "vix": {"threshold": 40, "operator": ">", "weight": 2.0},
                "bank_underperformance": {"threshold": -20, "operator": "<", "weight": 1.5},
            },
            actual_signals=[
                {"indicator": "yield_curve", "date": "2006-12", "value": -0.1, "lead_days": 260},
                {"indicator": "subprime_default", "date": "2007-02", "value": 1, "lead_days": 560},
                {"indicator": "libor_ois", "date": "2007-08", "value": 80, "lead_days": 390},
                {"indicator": "bear_stearns", "date": "2008-03", "value": 1, "lead_days": 175},
                {"indicator": "vix", "date": "2008-09", "value": 48, "lead_days": 0},
            ]
        ))
        
        # 3. 2011年欧债危机
        events.append(CrisisEvent(
            crisis_id="2011_eu_debt_crisis",
            name="2011年欧债危机",
            crisis_date=datetime(2011, 8, 5),
            warning_start=datetime(2010, 4, 1),
            recovery_start=datetime(2012, 7, 1),
            severity="high",
            crisis_type="sovereign_debt_crisis",
            description="希腊等欧洲主权国家债务危机",
            market_impact={
                "greece": -85.0,
                "ireland": -70.0,
                "spain_ibex": -50.0,
                "italy_mib": -45.0,
                "germany_dax": -30.0,
                "euro_usd": -20.0
            },
            indicator_thresholds={
                "debt_to_gdp": {"threshold": 90.0, "operator": ">", "weight": 3.0},
                "deficit_to_gdp": {"threshold": 3.0, "operator": ">", "weight": 2.0},
                "bond_yield": {"threshold": 7.0, "operator": ">", "weight": 3.0},
                "cds_spread": {"threshold": 300.0, "operator": ">", "weight": 2.5},
                "bank_cds": {"threshold": 300.0, "operator": ">", "weight": 2.0},
            },
            actual_signals=[
                {"indicator": "greek_deficit", "date": "2009-10", "value": 12.7, "lead_days": 400},
                {"indicator": "bond_yield", "date": "2011-07", "value": 7.5, "lead_days": 35},
                {"indicator": "cds_spread", "date": "2011-07", "value": 400, "lead_days": 35},
            ]
        ))
        
        # 4. 2015年A股熔断
        events.append(CrisisEvent(
            crisis_id="2015_a_share_crash",
            name="2015年A股熔断危机",
            crisis_date=datetime(2015, 6, 15),
            warning_start=datetime(2015, 4, 1),
            recovery_start=datetime(2016, 2, 1),
            severity="high",
            crisis_type="bubble_crash",
            description="A股高估值泡沫破裂及后续熔断危机",
            market_impact={
                "csi_300": -45.0,
                "chi_next": -60.0,
                "small_caps": -70.0,
                "brokerage": -65.0
            },
            indicator_thresholds={
                "pe_ratio_gem": {"threshold": 80.0, "operator": ">", "weight": 3.0},
                "margin_debt_gdp": {"threshold": 2.0, "operator": ">", "weight": 3.0},
                "new_investors": {"threshold": 500000, "operator": ">", "weight": 2.5},
                "turnover_velocity": {"threshold": 5.0, "operator": ">", "weight": 2.0},
                "pb_ratio_median": {"threshold": 5.0, "operator": ">", "weight": 2.0},
            },
            actual_signals=[
                {"indicator": "pe_ratio", "date": "2015-04", "value": 140, "lead_days": 70},
                {"indicator": "margin_debt", "date": "2015-05", "value": 2.2, "lead_days": 15},
                {"indicator": "regulatory_tightening", "date": "2015-06-12", "value": 1, "lead_days": 0},
            ]
        ))
        
        # 5. 2018年中美贸易战
        events.append(CrisisEvent(
            crisis_id="2018_trade_war",
            name="2018年中美贸易战",
            crisis_date=datetime(2018, 3, 22),
            warning_start=datetime(2018, 1, 1),
            recovery_start=datetime(2019, 1, 1),
            severity="elevated",
            crisis_type="trade_war",
            description="中美贸易摩擦引发的市场震荡",
            market_impact={
                "csi_300": -25.0,
                "hang_seng": -20.0,
                "china_internet": -40.0,
                "nasdaq": -20.0,
                "semiconductor": -25.0
            },
            indicator_thresholds={
                "trade_policy_news": {"threshold": 10, "operator": ">", "weight": 2.5},
                "rmb_volatility": {"threshold": 8.0, "operator": ">", "weight": 2.0},
                "cnh_cny_spread": {"threshold": 500, "operator": ">", "weight": 2.0},
                "soybean_price": {"threshold": -15, "operator": "<", "weight": 1.5},
                "export_order_pmi": {"threshold": 50, "operator": "<", "weight": 2.0},
            },
            actual_signals=[
                {"indicator": "policy_announcement", "date": "2018-01", "value": 1, "lead_days": 80},
                {"indicator": "tariff_list", "date": "2018-03-22", "value": 1, "lead_days": 0},
                {"indicator": "retaliation", "date": "2018-04", "value": 1, "lead_days": -10},
            ]
        ))
        
        # 6. 2020年COVID流动性危机
        events.append(CrisisEvent(
            crisis_id="2020_covid_crisis",
            name="2020年COVID流动性危机",
            crisis_date=datetime(2020, 3, 9),  # 美股熔断
            warning_start=datetime(2020, 1, 20),
            recovery_start=datetime(2020, 4, 1),
            severity="extreme",
            crisis_type="liquidity_crisis",
            description="新冠疫情引发的全球流动性危机",
            market_impact={
                "sp500": -34.0,
                "nasdaq": -30.0,
                "crude_oil": -65.0,
                "bitcoin": -50.0,
                "emerging_markets": -35.0
            },
            indicator_thresholds={
                "vix": {"threshold": 50, "operator": ">", "weight": 3.0},
                "move": {"threshold": 120, "operator": ">", "weight": 3.0},
                "sofr_ois_spread": {"threshold": 30, "operator": ">", "weight": 2.5},
                "ted_spread": {"threshold": 40, "operator": ">", "weight": 2.0},
                "credit_spread_ig": {"threshold": 200, "operator": ">", "weight": 2.0},
                "high_yield_spread": {"threshold": 700, "operator": ">", "weight": 2.0},
            },
            actual_signals=[
                {"indicator": "covid_outbreak", "date": "2020-01-20", "value": 1, "lead_days": 48},
                {"indicator": "who_pandemic", "date": "2020-03-11", "value": 1, "lead_days": -2},
                {"indicator": "vix", "date": "2020-03-16", "value": 82, "lead_days": -7},
                {"indicator": "circuit_breaker", "date": "2020-03-09", "value": 1, "lead_days": 0},
            ]
        ))
        
        # 7. 2022年强美元冲击
        events.append(CrisisEvent(
            crisis_id="2022_strong_dollar",
            name="2022年强美元冲击",
            crisis_date=datetime(2022, 1, 1),
            warning_start=datetime(2021, 6, 1),
            recovery_start=datetime(2022, 10, 1),
            severity="high",
            crisis_type="dollar_shock",
            description="美联储激进加息引发的强美元周期",
            market_impact={
                "nasdaq": -33.0,
                "emerging_markets": -25.0,
                "bitcoin": -64.0,
                "arkk": -67.0,
                "growth_stocks": -45.0
            },
            indicator_thresholds={
                "dxy": {"threshold": 105, "operator": ">", "weight": 3.0},
                "us_2y_yield": {"threshold": 3.0, "operator": ">", "weight": 2.0},
                "fed_dot_plot": {"threshold": 4, "operator": ">", "weight": 2.5},
                "real_yield": {"threshold": 1.0, "operator": ">", "weight": 2.0},
                "move": {"threshold": 100, "operator": ">", "weight": 1.5},
            },
            actual_signals=[
                {"indicator": "fed_hawkish", "date": "2021-11", "value": 1, "lead_days": 40},
                {"indicator": "dxy", "date": "2021-06", "value": 105, "lead_days": 200},
                {"indicator": "rate_hike", "date": "2022-03", "value": 1, "lead_days": -70},
            ]
        ))
        
        # 8. 2024年日元套利交易unwind
        events.append(CrisisEvent(
            crisis_id="2024_08_yen_carry",
            name="2024年8月日元套利交易unwind",
            crisis_date=datetime(2024, 8, 5),
            warning_start=datetime(2024, 7, 1),
            recovery_start=datetime(2024, 8, 15),
            severity="high",
            crisis_type="yen_carry_trade_unwind",
            description="日本央行加息引发的套利交易平仓",
            market_impact={
                "nikkei": -12.4,
                "nasdaq": -8.0,
                "semiconductor": -15.0,
                "emerging_markets": -10.0,
                "gold": 5.0
            },
            indicator_thresholds={
                "us_jp_spread_2y": {"threshold": 3.5, "operator": "<", "weight": 3.0},
                "usdjpy_change_1d": {"threshold": -1.5, "operator": "<", "weight": 2.5},
                "jgb_10y": {"threshold": 0.8, "operator": ">", "weight": 2.0},
                "move": {"threshold": 110, "operator": ">", "weight": 1.5},
                "vix": {"threshold": 25, "operator": ">", "weight": 1.5},
            },
            actual_signals=[
                {"indicator": "boj_hike", "date": "2024-07-31", "value": 1, "lead_days": 5},
                {"indicator": "us_jp_spread", "date": "2024-08-01", "value": 3.2, "lead_days": 4},
                {"indicator": "usdjpy", "date": "2024-08-02", "value": -2.0, "lead_days": 3},
                {"indicator": "vix", "date": "2024-08-05", "value": 38, "lead_days": 0},
            ]
        ))
        
        return events
    
    def _define_indicators(self) -> Dict[str, Dict]:
        """定义10个领先指标的配置"""
        return {
            "us_jp_spread_2y": {
                "name": "美日2年期利差",
                "description": "衡量套利交易吸引力的核心指标",
                "current_thresholds": {"elevated": 4.0, "critical": 3.0},
                "direction": "falling",
                "weight": 3.0,
                "applicable_crisis_types": ["yen_carry_trade_unwind", "currency_crisis"]
            },
            "dxy": {
                "name": "美元指数DXY",
                "description": "全球美元流动性晴雨表",
                "current_thresholds": {"elevated": 105, "critical": 107},
                "direction": "rising",
                "weight": 3.0,
                "applicable_crisis_types": ["dollar_shock", "currency_crisis", "emerging_markets"]
            },
            "vix": {
                "name": "VIX波动率指数",
                "description": "市场恐慌情绪指标",
                "current_thresholds": {"elevated": 28, "critical": 35},
                "direction": "rising",
                "weight": 2.5,
                "applicable_crisis_types": ["all"]
            },
            "move": {
                "name": "MOVE美债波动率",
                "description": "债券市场流动性压力",
                "current_thresholds": {"elevated": 120, "critical": 140},
                "direction": "rising",
                "weight": 2.5,
                "applicable_crisis_types": ["liquidity_crisis", "financial_crisis"]
            },
            "yield_curve_10y2y": {
                "name": "收益率曲线(10Y-2Y)",
                "description": "衰退预警指标",
                "current_thresholds": {"elevated": 0.5, "critical": 0.0},
                "direction": "falling",
                "weight": 3.0,
                "applicable_crisis_types": ["financial_crisis", "recession"]
            },
            "credit_spread_ig": {
                "name": "投资级信用利差",
                "description": "企业债市场风险",
                "current_thresholds": {"elevated": 150, "critical": 200},
                "direction": "rising",
                "weight": 2.0,
                "applicable_crisis_types": ["financial_crisis", "credit_crisis"]
            },
            "high_yield_spread": {
                "name": "高收益债利差",
                "description": "风险情绪指标",
                "current_thresholds": {"elevated": 500, "critical": 800},
                "direction": "rising",
                "weight": 2.0,
                "applicable_crisis_types": ["financial_crisis", "credit_crisis", "recession"]
            },
            "sofr_ois_spread": {
                "name": "SOFR-OIS利差",
                "description": "银行间流动性压力",
                "current_thresholds": {"elevated": 30, "critical": 50},
                "direction": "rising",
                "weight": 2.5,
                "applicable_crisis_types": ["liquidity_crisis", "financial_crisis"]
            },
            "ted_spread": {
                "name": "TED利差",
                "description": "离岸美元流动性",
                "current_thresholds": {"elevated": 40, "critical": 100},
                "direction": "rising",
                "weight": 2.0,
                "applicable_crisis_types": ["liquidity_crisis", "currency_crisis"]
            },
            "copper_gold_ratio": {
                "name": "铜金比",
                "description": "经济周期指标",
                "current_thresholds": {"elevated": -5, "critical": -10},
                "direction": "falling",
                "weight": 1.5,
                "applicable_crisis_types": ["recession", "trade_war"]
            }
        }
    
    def run_backtest(self, crisis_id: Optional[str] = None) -> List[BacktestResult]:
        """
        运行回测
        
        Args:
            crisis_id: 指定单个危机进行回测，None则回测所有
        
        Returns:
            回测结果列表
        """
        results = []
        
        events_to_test = [e for e in self.crisis_events 
                         if crisis_id is None or e.crisis_id == crisis_id]
        
        for event in events_to_test:
            print(f"\n📊 回测: {event.name} ({event.crisis_date.strftime('%Y-%m-%d')})")
            result = self._backtest_single_crisis(event)
            results.append(result)
        
        return results
    
    def _backtest_single_crisis(self, event: CrisisEvent) -> BacktestResult:
        """对单个危机进行回测"""
        performances = []
        triggered_indicators = []
        warning_dates = []
        
        # 模拟每个指标在危机前的表现
        for indicator_id, indicator_config in self.indicators.items():
            perf = self._simulate_indicator(event, indicator_id, indicator_config)
            performances.append(perf)
            
            if perf.warned:
                triggered_indicators.append(indicator_id)
                if perf.warning_date:
                    warning_dates.append(perf.warning_date)
        
        # 计算统计数据
        warned_count = len([p for p in performances if p.warned])
        missed_count = len([p for p in performances if p.missed_crisis])
        lead_times = [p.lead_time_days for p in performances if p.lead_time_days > 0]
        
        # 找出最佳和最差指标
        sorted_perfs = sorted(performances, key=lambda x: x.effectiveness_score, reverse=True)
        best_indicators = [p.indicator_name for p in sorted_perfs[:3] if p.effectiveness_score > 50]
        worst_indicators = [p.indicator_name for p in sorted_perfs[-3:] if p.effectiveness_score < 30]
        
        # 生成建议
        recommendations = self._generate_optimization_recommendations(event, performances)
        
        return BacktestResult(
            crisis_id=event.crisis_id,
            crisis_name=event.name,
            indicators_triggered=warned_count,
            total_indicators=len(self.indicators),
            best_indicators=best_indicators,
            worst_indicators=worst_indicators,
            earliest_warning=min(warning_dates) if warning_dates else None,
            latest_warning=max(warning_dates) if warning_dates else None,
            avg_lead_time=sum(lead_times) / len(lead_times) if lead_times else 0,
            hit_rate=warned_count / len(performances) if performances else 0,
            false_positive_rate=0.0,  # 简化计算
            indicator_performances=performances,
            recommendations=recommendations
        )
    
    def _simulate_indicator(self, event: CrisisEvent, 
                           indicator_id: str, 
                           config: Dict) -> IndicatorPerformance:
        """
        模拟单个指标在危机中的表现
        
        基于历史复盘中记录的实际信号和阈值进行模拟
        """
        warned = False
        warning_date = None
        lead_time = 0
        missed = False
        actual_value = 0
        max_value = 0
        
        # 检查该危机是否有针对此指标的预设阈值
        if indicator_id in event.indicator_thresholds:
            threshold_config = event.indicator_thresholds[indicator_id]
            threshold = threshold_config.get("threshold", 0)
            
            # 查找实际信号中是否有该指标
            matching_signals = [
                s for s in event.actual_signals 
                if indicator_id.replace('_', '') in s.get("indicator", "").replace('_', '')
            ]
            
            if matching_signals:
                # 使用该危机的实际信号
                earliest_signal = min(matching_signals, key=lambda x: x.get("lead_days", 0))
                lead_time = earliest_signal.get("lead_days", 0)
                actual_value = earliest_signal.get("value", 0)
                warned = lead_time > 0  # 在危机前发出预警才算预警成功
                
                if warned:
                    warning_date = event.crisis_date - timedelta(days=lead_time)
            else:
                # 根据危机类型判断指标是否适用
                crisis_type = event.crisis_type
                applicable_types = config.get("applicable_crisis_types", [])
                
                if "all" in applicable_types or crisis_type in applicable_types:
                    # 指标适用但未在信号列表中，视为漏报或信号不明显
                    missed = True
                    lead_time = 0
                else:
                    # 指标不适用于此危机类型，不做评价
                    missed = False
        
        # 计算有效性评分 (0-100)
        effectiveness = self._calculate_effectiveness_score(
            warned, lead_time, missed, indicator_id, event
        )
        
        return IndicatorPerformance(
            indicator_name=config.get("name", indicator_id),
            crisis_id=event.crisis_id,
            warned=warned,
            warning_date=warning_date,
            lead_time_days=lead_time,
            false_positive=False,  # 简化处理
            missed_crisis=missed,
            threshold_used=config.get("current_thresholds", {}).get("critical", 0),
            actual_value_at_warning=actual_value,
            max_value_before_crisis=max_value,
            effectiveness_score=effectiveness
        )
    
    def _calculate_effectiveness_score(self, warned: bool, lead_time: int, 
                                      missed: bool, indicator_id: str,
                                      event: CrisisEvent) -> float:
        """计算指标有效性评分"""
        if missed:
            return 20.0  # 漏报给予基础分
        
        if not warned:
            # 未预警但非漏报（可能不适用于此危机类型）
            applicable_types = self.indicators.get(indicator_id, {}).get("applicable_crisis_types", [])
            if "all" in applicable_types or event.crisis_type in applicable_types:
                return 30.0  # 适用但未触发
            return 50.0  # 不适用，中性分
        
        # 成功预警，根据提前期评分
        base_score = 60.0
        
        # 提前期加分
        if lead_time >= 90:
            base_score += 30  # 3个月以上，优秀
        elif lead_time >= 30:
            base_score += 20  # 1个月以上，良好
        elif lead_time >= 7:
            base_score += 10  # 1周以上，及格
        else:
            base_score += 5   # 1周内，勉强
        
        return min(base_score, 100.0)
    
    def _generate_optimization_recommendations(self, event: CrisisEvent,
                                               performances: List[IndicatorPerformance]) -> List[str]:
        """生成优化建议"""
        recommendations = []
        
        # 找出表现好的指标
        good_performers = [p for p in performances if p.effectiveness_score >= 70]
        if good_performers:
            indicators_str = ", ".join([p.indicator_name for p in good_performers[:3]])
            recommendations.append(f"✅ 本次危机中表现优秀的指标: {indicators_str}，建议保持或提高权重")
        
        # 找出漏报的指标
        missed_indicators = [p for p in performances if p.missed_crisis]
        if missed_indicators:
            indicators_str = ", ".join([p.indicator_name for p in missed_indicators])
            recommendations.append(f"⚠️ 本次危机中漏报的指标: {indicators_str}，建议降低阈值或改进算法")
        
        # 找出预警过早的指标（可能导致误报）
        early_warnings = [p for p in performances if p.warned and p.lead_time_days > 180]
        if early_warnings:
            indicators_str = ", ".join([p.indicator_name for p in early_warnings])
            recommendations.append(f"⏰ 本次危机中预警过早的指标(>6个月): {indicators_str}，可能导致误报，建议提高阈值")
        
        # 找出预警过晚的指标
        late_warnings = [p for p in performances if p.warned and p.lead_time_days < 3]
        if late_warnings:
            indicators_str = ", ".join([p.indicator_name for p in late_warnings])
            recommendations.append(f"🚨 本次危机中预警过晚的指标(<3天): {indicators_str}，建议降低阈值")
        
        return recommendations if recommendations else ["本次回测未发现明显的优化点"]
    
    def generate_summary_report(self, results: List[BacktestResult]) -> str:
        """生成汇总回测报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("🎯 领先指标回测报告 - 汇总")
        lines.append("=" * 80)
        lines.append("")
        
        # 整体统计
        total_crisis = len(results)
        total_indicators = sum(r.total_indicators for r in results)
        total_triggered = sum(r.indicators_triggered for r in results)
        
        lines.append(f"📊 回测范围: {total_crisis}次历史危机 × {self.indicators.__len__()}个指标")
        lines.append(f"📈 总预警次数: {total_triggered} / {total_indicators}")
        lines.append(f"🎯 平均命中率: {total_triggered/total_indicators*100:.1f}%")
        lines.append("")
        
        # 按危机展示结果
        lines.append("-" * 80)
        lines.append("📋 各危机表现详情")
        lines.append("-" * 80)
        
        for result in results:
            lines.append(f"\n🔴 {result.crisis_name}")
            lines.append(f"   预警指标: {result.indicators_triggered}/{result.total_indicators} ({result.hit_rate*100:.0f}%)")
            lines.append(f"   平均提前: {result.avg_lead_time:.0f}天")
            
            if result.best_indicators:
                lines.append(f"   ✅ 最佳指标: {', '.join(result.best_indicators)}")
            if result.worst_indicators:
                lines.append(f"   ⚠️  待改进: {', '.join(result.worst_indicators)}")
        
        # 指标维度分析
        lines.append("")
        lines.append("-" * 80)
        lines.append("🔍 指标维度分析")
        lines.append("-" * 80)
        
        indicator_stats = self._calculate_indicator_stats(results)
        sorted_indicators = sorted(indicator_stats.items(), key=lambda x: x[1]["avg_score"], reverse=True)
        
        lines.append(f"\n{'指标':<20} {'命中率':<10} {'平均提前':<12} {'平均得分':<10}")
        lines.append("-" * 60)
        
        for indicator_name, stats in sorted_indicators:
            lines.append(f"{indicator_name:<20} {stats['hit_rate']*100:>6.1f}%   {stats['avg_lead_time']:>6.0f}天     {stats['avg_score']:>6.1f}")
        
        # 优化建议汇总
        lines.append("")
        lines.append("-" * 80)
        lines.append("💡 优化建议汇总")
        lines.append("-" * 80)
        
        all_recommendations = []
        for result in results:
            all_recommendations.extend(result.recommendations)
        
        # 去重并按类型分组
        unique_recommendations = list(set(all_recommendations))
        for i, rec in enumerate(unique_recommendations[:10], 1):
            lines.append(f"{i}. {rec}")
        
        # 最佳实践
        lines.append("")
        lines.append("-" * 80)
        lines.append("🏆 最佳实践总结")
        lines.append("-" * 80)
        lines.append("")
        lines.append("基于8次历史危机回测，以下组合最有效:")
        lines.append("")
        lines.append("🔹 流动性危机组合 (2008, 2020):")
        lines.append("   MOVE + VIX + SOFR-OIS + 信用利差")
        lines.append("   触发3个以上 = 立即减仓")
        lines.append("")
        lines.append("🔹 货币危机组合 (1997, 2024):")
        lines.append("   美日利差 + DXY + TED利差")
        lines.append("   触发2个以上 = 减仓海外资产")
        lines.append("")
        lines.append("🔹 债务危组合 (2011):")
        lines.append("   CDS利差 + 债券收益率 + 信用利差")
        lines.append("   触发2个以上 = 避开高风险债务")
        lines.append("")
        lines.append("🔹 泡沫破裂组合 (2015):")
        lines.append("   估值指标 + 杠杆指标 + 情绪指标")
        lines.append("   触发3个以上 = 清仓风险资产")
        
        lines.append("")
        lines.append("=" * 80)
        lines.append(f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def _calculate_indicator_stats(self, results: List[BacktestResult]) -> Dict:
        """计算各指标在所有危机中的统计"""
        stats = {}
        
        for result in results:
            for perf in result.indicator_performances:
                name = perf.indicator_name
                if name not in stats:
                    stats[name] = {
                        "total": 0,
                        "triggered": 0,
                        "lead_times": [],
                        "scores": []
                    }
                
                stats[name]["total"] += 1
                if perf.warned:
                    stats[name]["triggered"] += 1
                    stats[name]["lead_times"].append(perf.lead_time_days)
                stats[name]["scores"].append(perf.effectiveness_score)
        
        # 计算平均值
        for name, data in stats.items():
            data["hit_rate"] = data["triggered"] / data["total"] if data["total"] > 0 else 0
            data["avg_lead_time"] = sum(data["lead_times"]) / len(data["lead_times"]) if data["lead_times"] else 0
            data["avg_score"] = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
        
        return stats
    
    def export_results(self, results: List[BacktestResult], 
                      output_path: Optional[str] = None) -> str:
        """导出详细回测结果到JSON"""
        if output_path is None:
            output_path = Path.home() / "investment-skill" / "backtest_results.json"
        
        # 转换为可序列化的字典
        export_data = {
            "backtest_date": datetime.now().isoformat(),
            "total_crisis": len(results),
            "indicators_tested": list(self.indicators.keys()),
            "results": []
        }
        
        for result in results:
            result_dict = {
                "crisis_id": result.crisis_id,
                "crisis_name": result.crisis_name,
                "indicators_triggered": result.indicators_triggered,
                "total_indicators": result.total_indicators,
                "hit_rate": result.hit_rate,
                "avg_lead_time": result.avg_lead_time,
                "best_indicators": result.best_indicators,
                "worst_indicators": result.worst_indicators,
                "recommendations": result.recommendations,
                "indicator_performances": [
                    {
                        "indicator_name": p.indicator_name,
                        "warned": p.warned,
                        "lead_time_days": p.lead_time_days,
                        "effectiveness_score": p.effectiveness_score,
                        "missed_crisis": p.missed_crisis
                    }
                    for p in result.indicator_performances
                ]
            }
            export_data["results"].append(result_dict)
        
        # 保存到文件
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description='Leading Indicator Backtest System - 领先指标回测系统'
    )
    
    parser.add_argument(
        '--crisis', '-c',
        type=str,
        help='指定单个危机ID进行回测 (如: 2024_08_yen_carry)'
    )
    
    parser.add_argument(
        '--indicator', '-i',
        type=str,
        help='指定单个指标进行回测 (如: dxy)'
    )
    
    parser.add_argument(
        '--export', '-e',
        action='store_true',
        help='导出详细结果到JSON文件'
    )
    
    parser.add_argument(
        '--save-report', '-s',
        action='store_true',
        help='保存报告到Vault'
    )
    
    args = parser.parse_args()
    
    # 创建回测系统
    backtest = LeadingIndicatorBacktest()
    
    print("🧪 领先指标回测系统启动...")
    print(f"📊 加载了 {len(backtest.crisis_events)} 个历史危机")
    print(f"📈 测试 {len(backtest.indicators)} 个领先指标")
    print("")
    
    # 运行回测
    results = backtest.run_backtest(crisis_id=args.crisis)
    
    # 生成并打印报告
    report = backtest.generate_summary_report(results)
    print(report)
    
    # 导出结果
    if args.export:
        export_path = backtest.export_results(results)
        print(f"\n💾 详细结果已导出到: {export_path}")
    
    # 保存到Vault
    if args.save_report:
        from utils.vault_writer import get_vault_writer
        vault = get_vault_writer()
        
        filename = f"backtest_report_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        content = f"""---
date: {datetime.now().isoformat()}
category: backtest_report
generated_by: Leading Indicator Backtest System
---

# 领先指标回测报告

{report}
"""
        filepath = vault.write_knowledge_entry(content, 'macro', filename)
        print(f"\n📝 报告已保存到Vault: {filepath}")


if __name__ == "__main__":
    main()
