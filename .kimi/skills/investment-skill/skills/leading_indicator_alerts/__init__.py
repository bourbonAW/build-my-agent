"""
Leading Indicator Alert System - 领先指标预警系统（完整版）
基于先行指标预测市场变动，而非事后价格提醒

包含指标：
1. 美日利差（套利交易 unwind）
2. DXY美元指数（全球流动性）
3. MOVE/VIX指数（市场恐慌）
4. 收益率曲线（衰退预警）
5. 信用利差（企业债压力）
6. SOFR-OIS利差（银行间压力）
7. TED利差（离岸美元流动性）
8. 高收益债利差（风险情绪）
9. 期限溢价（持有长期债券的补偿）
10. 铜金比（经济周期）
"""
import sys
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.yahoo_collector import get_yahoo_collector
from collectors.macro_collector import get_macro_collector
from utils.vault_writer import get_vault_writer
from utils.data_cache import get_cache, cached
from skills.leading_indicator_alerts.historical_patterns import (
    HistoricalPatternManager, match_historical_patterns
)


@dataclass
class LeadingSignal:
    """领先指标信号"""
    indicator_name: str          # 指标名称
    current_value: float         # 当前值
    change_1d: float            # 1日变动
    change_1w: float            # 1周变动
    direction: str              # "rising", "falling", "neutral"
    severity: str               # "normal", "elevated", "critical"
    implication: str            # 含义解释
    historical_pattern: str     # 历史模式
    timeframe: str              # 预计影响时间窗口


@dataclass
class StrategicRecommendation:
    """战略建议"""
    action: str                 # "increase", "reduce", "hold", "hedge"
    urgency: str               # "immediate", "this_week", "monitor"
    confidence: str            # "high", "medium", "low"
    rationale: str             # 建议理由
    affected_positions: List[str]  # 影响的持仓
    risk_level: str            # "high", "medium", "low"


@dataclass
class EarlyWarningReport:
    """早期预警报告"""
    timestamp: str
    warning_level: str         # "green", "yellow", "orange", "red"
    liquidity_assessment: str  # 流动性评估
    key_signals: List[LeadingSignal]
    historical_match: Optional[str]  # 匹配的历史模式
    recommendations: List[StrategicRecommendation]
    forward_looking_summary: str  # 前瞻性总结


class LeadingIndicatorMonitor:
    """
    领先指标监控系统 - 完整版
    
    核心理念：监控先行指标，而非滞后价格
    """
    
    def __init__(self):
        self.yahoo = get_yahoo_collector()
        self.macro = get_macro_collector()
        self.vault = get_vault_writer()
        self.cache = get_cache()
        self.session = requests.Session()
        
        # 历史数据缓存
        self.historical_data = {}
    
    def analyze(self) -> EarlyWarningReport:
        """
        执行完整领先指标分析
        """
        print("\n🔮 Leading Indicator Analysis - Looking Ahead...")
        print("   Analyzing early warning signals...\n")
        
        signals = []
        
        # 1. 美日利差（全球流动性核心指标）
        print("   💱 Checking US-Japan yield spread...")
        signal = self._check_us_jp_spread()
        if signal:
            signals.append(signal)
        
        # 2. DXY美元指数（全球美元流动性）
        print("   💵 Checking Dollar Index...")
        signal = self._check_dxy_liquidity()
        if signal:
            signals.append(signal)
        
        # 3. MOVE指数（美债波动率）
        print("   📈 Checking MOVE index...")
        signal = self._check_move_index()
        if signal:
            signals.append(signal)
        
        # 4. 收益率曲线（衰退预警）
        print("   📉 Checking yield curve...")
        signal = self._check_yield_curve()
        if signal:
            signals.append(signal)
        
        # 5. 信用利差（企业债压力）
        print("   🏢 Checking credit spreads...")
        signal = self._check_credit_spreads()
        if signal:
            signals.append(signal)
        
        # 6. SOFR-OIS利差（银行间压力）
        print("   🏦 Checking SOFR-OIS spread...")
        signal = self._check_sofr_ois_spread()
        if signal:
            signals.append(signal)
        
        # 7. 高收益债利差（风险情绪）
        print("   📊 Checking high yield spreads...")
        signal = self._check_high_yield_spread()
        if signal:
            signals.append(signal)
        
        # 8. TED利差（离岸美元流动性）
        print("   🌊 Checking TED spread...")
        signal = self._check_ted_spread()
        if signal:
            signals.append(signal)
        
        # 9. 期限溢价（长期债券风险）
        print("   ⏱️  Checking term premium...")
        signal = self._check_term_premium()
        if signal:
            signals.append(signal)
        
        # 10. 铜金比（经济周期）
        print("   🥉/🥇 Checking copper-gold ratio...")
        signal = self._check_copper_gold_ratio()
        if signal:
            signals.append(signal)
        
        # 评估整体环境
        liquidity_assessment = self._assess_liquidity_environment(signals)
        historical_match = self._match_historical_pattern(signals)
        recommendations = self._generate_recommendations(signals, liquidity_assessment)
        warning_level = self._determine_warning_level(signals, liquidity_assessment)
        forward_summary = self._generate_forward_summary(signals, recommendations)
        
        report = EarlyWarningReport(
            timestamp=datetime.now().isoformat(),
            warning_level=warning_level,
            liquidity_assessment=liquidity_assessment,
            key_signals=signals,
            historical_match=historical_match,
            recommendations=recommendations,
            forward_looking_summary=forward_summary
        )
        
        self._save_report(report)
        return report
    
    # ==================== 核心领先指标实现 ====================
    
    def _check_us_jp_spread(self) -> Optional[LeadingSignal]:
        """
        美日2年期利差 - 全球流动性核心指标
        
        逻辑：利差收窄 → 套利交易吸引力下降 → 资金回流日本
        危险阈值：< 3.0% (Critical), < 4.0% (Elevated)
        历史：2024年8月利差收窄至3.5%以下，随后全球市场暴跌
        """
        try:
            yields = self.macro.get_treasury_yields()
            if not yields or '2Y' not in yields:
                return None
            
            us_2y = yields['2Y']['rate']
            
            # 获取日债2Y（通过Yahoo Finance）
            jp_yield = self._get_japanese_yield()
            if not jp_yield:
                jp_yield = 0.5  # 默认估计值
            
            spread = us_2y - jp_yield
            
            # 获取历史数据计算变动
            historical = self._get_spread_history('us_jp_2y', days=7)
            change_1d = self._calculate_change(spread, historical, 1)
            change_1w = self._calculate_change(spread, historical, 5)
            
            # 判断严重程度
            if spread < 3.0:
                severity = "critical"
                direction = "falling"
                implication = f"利差收窄至{spread:.2f}%，套利交易 unwind 风险极高，可能引发全球市场暴跌"
            elif spread < 4.0:
                severity = "elevated"
                direction = "falling"
                implication = f"利差收窄至{spread:.2f}%，警惕套利交易平仓压力"
            elif spread < 4.5:
                severity = "normal"
                direction = "falling"
                implication = f"利差{spread:.2f}%，趋于收窄，建议密切关注"
            else:
                return None  # 正常范围不报告
            
            return LeadingSignal(
                indicator_name="美日2年期利差 (US2Y-JP2Y Spread)",
                current_value=spread,
                change_1d=change_1d,
                change_1w=change_1w,
                direction=direction,
                severity=severity,
                implication=implication,
                historical_pattern="2024年8月利差收窄至3.5%以下，随后全球股市暴跌10-15%",
                timeframe="1-7 days"
            )
        except Exception as e:
            print(f"      ⚠️  Error checking US-JP spread: {e}")
            return None
    
    def _check_dxy_liquidity(self) -> Optional[LeadingSignal]:
        """
        美元指数DXY - 全球美元流动性晴雨表
        
        逻辑：DXY > 105 → 强势美元 → 新兴市场资金外流 → 流动性收紧
        危险阈值：> 107 (Critical), > 105 (Elevated)
        历史：2022年DXY飙升至114，导致全球科技股暴跌30-50%
        """
        try:
            dxy_data = self.macro.get_dollar_index()
            if not dxy_data:
                return None
            
            dxy = dxy_data.get('value', 100)
            
            # 获取历史变动
            historical = self._get_dxy_history(days=7)
            change_1d = self._calculate_change(dxy, historical, 1)
            change_1w = self._calculate_change(dxy, historical, 5)
            
            # 判断方向
            direction = "rising" if change_1d > 0 else "falling" if change_1d < 0 else "neutral"
            
            if dxy > 107:
                return LeadingSignal(
                    indicator_name="美元指数 (DXY) - 全球美元流动性",
                    current_value=dxy,
                    change_1d=change_1d,
                    change_1w=change_1w,
                    direction=direction,
                    severity="critical",
                    implication=f"美元极度强势({dxy:.1f})，严重流动性紧缩，QDII基金面临巨大压力",
                    historical_pattern="2022年DXY升至114，纳斯达克暴跌33%，新兴市场货币危机",
                    timeframe="1-4 weeks"
                )
            elif dxy > 105:
                return LeadingSignal(
                    indicator_name="美元指数 (DXY) - 全球美元流动性",
                    current_value=dxy,
                    change_1d=change_1d,
                    change_1w=change_1w,
                    direction=direction,
                    severity="elevated",
                    implication=f"美元强势({dxy:.1f})，全球流动性收紧，建议降低海外资产配置",
                    historical_pattern="2022年DXY>105期间，科技股普遍回调20-30%",
                    timeframe="1-4 weeks"
                )
            elif dxy > 103 and change_1d > 0.5:
                # 快速上涨但未达阈值
                return LeadingSignal(
                    indicator_name="美元指数 (DXY) - 全球美元流动性",
                    current_value=dxy,
                    change_1d=change_1d,
                    change_1w=change_1w,
                    direction="rising",
                    severity="normal",
                    implication=f"美元快速上涨(+{change_1d:.2f}%)，警惕进一步走强风险",
                    historical_pattern="美元快速升值通常先于风险资产下跌",
                    timeframe="1-2 weeks"
                )
            
            return None
        except Exception as e:
            print(f"      ⚠️  Error checking DXY: {e}")
            return None
    
    def _check_move_index(self) -> Optional[LeadingSignal]:
        """
        MOVE指数 - 美债波动率（债券市场的VIX）
        
        逻辑：MOVE > 120 → 美债市场动荡 → 流动性紧张 → 风险资产承压
        危险阈值：> 140 (Critical), > 120 (Elevated)
        历史：2008年、2020年3月MOVE飙升，随后股市暴跌
        """
        try:
            # 尝试获取真实MOVE指数
            move_value = self._get_move_index()
            
            if move_value is None and self.yahoo:
                # 使用VIX作为代理
                vix = self.yahoo.get_index_data('VIX')
                if vix:
                    move_value = vix.get('close', 20)
                    is_proxy = True
                else:
                    return None
            else:
                is_proxy = False
            
            # 获取历史
            historical = self._get_volatility_history(days=7)
            change_1d = self._calculate_change(move_value, historical, 1)
            change_1w = self._calculate_change(move_value, historical, 5)
            
            direction = "rising" if change_1d > 0 else "falling" if change_1d < 0 else "neutral"
            indicator_name = "MOVE指数 (Treasury Volatility)" if not is_proxy else "VIX指数 (Market Volatility Proxy)"
            
            if move_value > 140 or (is_proxy and move_value > 35):
                return LeadingSignal(
                    indicator_name=indicator_name,
                    current_value=move_value,
                    change_1d=change_1d,
                    change_1w=change_1w,
                    direction=direction,
                    severity="critical",
                    implication=f"{'MOVE' if not is_proxy else 'VIX'}高达{move_value:.1f}，债市/股市极度恐慌，流动性危机风险",
                    historical_pattern="2008年金融危机MOVE>150，2020年3月MOVE>160，随后股市暴跌30-50%",
                    timeframe="immediate"
                )
            elif move_value > 120 or (is_proxy and move_value > 28):
                return LeadingSignal(
                    indicator_name=indicator_name,
                    current_value=move_value,
                    change_1d=change_1d,
                    change_1w=change_1w,
                    direction=direction,
                    severity="elevated",
                    implication=f"{'MOVE' if not is_proxy else 'VIX'}上升至{move_value:.1f}，债券市场压力显现，建议降低风险敞口",
                    historical_pattern="MOVE>120通常预示1-2周内风险资产大幅波动",
                    timeframe="1-7 days"
                )
            elif move_value > 100 or (is_proxy and move_value > 22):
                return LeadingSignal(
                    indicator_name=indicator_name,
                    current_value=move_value,
                    change_1d=change_1d,
                    change_1w=change_1w,
                    direction=direction,
                    severity="normal",
                    implication=f"{'MOVE' if not is_proxy else 'VIX'}处于{move_value:.1f}，波动率上升，保持警惕",
                    historical_pattern="波动率从低位快速上升往往领先市场调整",
                    timeframe="1-2 weeks"
                )
            
            return None
        except Exception as e:
            print(f"      ⚠️  Error checking MOVE: {e}")
            return None
    
    def _check_yield_curve(self) -> Optional[LeadingSignal]:
        """
        收益率曲线（10Y-2Y）- 衰退预警指标
        
        逻辑：倒挂（10Y<2Y）→ 衰退预警 → 企业盈利下滑 → 股市承压
        危险阈值：负值（倒挂）
        历史：每次倒挂后6-18个月大概率衰退，股市提前6个月反应
        """
        try:
            yields = self.macro.get_treasury_yields()
            if not yields or '10Y2Y_spread' not in yields:
                return None
            
            spread = yields['10Y2Y_spread']
            
            # 获取历史
            historical = self._get_curve_history(days=30)
            change_1d = self._calculate_change(spread, historical, 1)
            change_1w = self._calculate_change(spread, historical, 5)
            
            if spread < -0.5:
                return LeadingSignal(
                    indicator_name="收益率曲线倒挂 (10Y-2Y Spread)",
                    current_value=spread,
                    change_1d=change_1d,
                    change_1w=change_1w,
                    direction="deep_inverted",
                    severity="critical",
                    implication=f"曲线深度倒挂({spread:.2f}%)，强烈衰退信号，价值股优于成长股",
                    historical_pattern="每次深度倒挂后6-18个月100%衰退，股市提前反应",
                    timeframe="6-18 months"
                )
            elif spread < 0:
                return LeadingSignal(
                    indicator_name="收益率曲线倒挂 (10Y-2Y Spread)",
                    current_value=spread,
                    change_1d=change_1d,
                    change_1w=change_1w,
                    direction="inverted",
                    severity="elevated",
                    implication=f"曲线倒挂({spread:.2f}%)，衰退预警，建议增配防御性资产",
                    historical_pattern="1970年以来每次倒挂都伴随衰退",
                    timeframe="6-18 months"
                )
            elif spread < 0.5:
                return LeadingSignal(
                    indicator_name="收益率曲线趋平 (10Y-2Y Spread)",
                    current_value=spread,
                    change_1d=change_1d,
                    change_1w=change_1w,
                    direction="flattening",
                    severity="normal",
                    implication=f"曲线趋于平坦({spread:.2f}%)，经济放缓信号",
                    historical_pattern="曲线从陡峭到平坦通常领先衰退6-12个月",
                    timeframe="3-12 months"
                )
            
            return None
        except Exception as e:
            print(f"      ⚠️  Error checking yield curve: {e}")
            return None
    
    def _check_credit_spreads(self) -> Optional[LeadingSignal]:
        """
        投资级信用利差 - 企业债市场风险
        
        逻辑：利差扩大 → 企业融资成本上升 → 盈利下降 → 裁员/破产
        危险阈值：> 150bp (Elevated), > 200bp (Critical)
        """
        try:
            # 通过LQD（投资级债ETF）价格反推利差
            # 或使用ICE BofA Corporate Option-Adjusted Spreads（需要API）
            
            # 简化：使用LQD vs TLT（国债）的表现差异
            if not self.yahoo:
                return None
            
            lqd = self.yahoo.get_index_data('LQD')  # iShares iBoxx $ Inv Grade Corporate Bond ETF
            tlt = self.yahoo.get_index_data('TLT')  # iShares 20+ Year Treasury Bond ETF
            
            if not lqd or not tlt:
                return None
            
            # 计算相对表现（信用利差代理）
            lqd_change = lqd.get('change_pct', 0)
            tlt_change = tlt.get('change_pct', 0)
            spread_change = lqd_change - tlt_change
            
            # 如果信用债表现明显差于国债，说明利差扩大
            if spread_change < -0.5:
                return LeadingSignal(
                    indicator_name="投资级信用利差 (IG Credit Spread)",
                    current_value=abs(spread_change),
                    change_1d=spread_change,
                    change_1w=0.0,
                    direction="widening",
                    severity="elevated" if spread_change < -1.0 else "normal",
                    implication=f"投资级债券跑输国债{abs(spread_change):.2f}%，企业信用风险上升",
                    historical_pattern="信用利差扩大领先股市下跌3-6个月",
                    timeframe="1-6 months"
                )
            
            return None
        except Exception as e:
            print(f"      ⚠️  Error checking credit spreads: {e}")
            return None
    
    def _check_sofr_ois_spread(self) -> Optional[LeadingSignal]:
        """
        SOFR-OIS利差 - 银行间压力指标
        
        逻辑：利差扩大 → 银行间不信任 → 流动性紧张
        危险阈值：> 50bp (Elevated), > 100bp (Critical)
        历史：2008年利差飙升至364bp，随后雷曼破产
        """
        try:
            # 获取SOFR
            sofr_data = self.macro.get_sofr_rate()
            if not sofr_data:
                return None
            
            sofr = sofr_data.get('rate', 0)
            
            # OIS（隔夜指数互换）通常接近Fed Funds利率
            # 这里使用Fed Funds作为代理
            fed_rate = self._get_fed_funds_rate()
            if not fed_rate:
                return None
            
            spread = sofr - fed_rate
            
            if spread > 0.5:  # 50bp
                return LeadingSignal(
                    indicator_name="SOFR-OIS利差 (Interbank Stress)",
                    current_value=spread,
                    change_1d=0.0,
                    change_1w=0.0,
                    direction="widening",
                    severity="critical" if spread > 1.0 else "elevated",
                    implication=f"SOFR-OIS利差扩大至{spread:.2f}%，银行间流动性紧张，系统性风险上升",
                    historical_pattern="2008年利差飙升至364bp，2020年3月飙升至150bp",
                    timeframe="immediate"
                )
            
            return None
        except Exception as e:
            print(f"      ⚠️  Error checking SOFR-OIS: {e}")
            return None
    
    def _check_high_yield_spread(self) -> Optional[LeadingSignal]:
        """
        高收益债利差（垃圾债）- 风险情绪指标
        
        逻辑：利差扩大 → 风险偏好下降 → 资金逃离高风险资产
        危险阈值：> 500bp (Elevated), > 800bp (Critical)
        """
        try:
            if not self.yahoo:
                return None
            
            # 使用HYG（高收益债ETF）作为代理
            hyg = self.yahoo.get_index_data('HYG')
            lqd = self.yahoo.get_index_data('LQD')
            
            if not hyg or not lqd:
                return None
            
            hyg_change = hyg.get('change_pct', 0)
            lqd_change = lqd.get('change_pct', 0)
            spread_change = hyg_change - lqd_change
            
            if spread_change < -1.0:
                return LeadingSignal(
                    indicator_name="高收益债利差 (High Yield Spread)",
                    current_value=abs(spread_change),
                    change_1d=spread_change,
                    change_1w=0.0,
                    direction="widening",
                    severity="critical" if spread_change < -3.0 else "elevated",
                    implication=f"高收益债跑输投资级债{abs(spread_change):.2f}%，风险情绪急剧恶化",
                    historical_pattern="高收益债利差飙升领先股市暴跌，2008年>2000bp",
                    timeframe="1-4 weeks"
                )
            
            return None
        except Exception as e:
            print(f"      ⚠️  Error checking high yield: {e}")
            return None
    
    def _check_ted_spread(self) -> Optional[LeadingSignal]:
        """
        TED利差 - 离岸美元流动性
        
        逻辑：3M LIBOR - 3M T-Bill，反映离岸美元紧张程度
        危险阈值：> 50bp (Elevated), > 100bp (Critical)
        """
        try:
            # 简化：使用DXY快速上涨作为代理
            dxy_data = self.macro.get_dollar_index()
            if not dxy_data:
                return None
            
            dxy_change = self._get_dxy_change_1d()
            
            if dxy_change and dxy_change > 1.0:
                return LeadingSignal(
                    indicator_name="TED利差代理 (Offshore Dollar Liquidity)",
                    current_value=dxy_change,
                    change_1d=dxy_change,
                    change_1w=0.0,
                    direction="tightening",
                    severity="elevated" if dxy_change > 1.5 else "normal",
                    implication=f"美元快速升值{dxy_change:.2f}%，离岸美元流动性紧张",
                    historical_pattern="TED利差扩大通常伴随新兴市场危机",
                    timeframe="1-2 weeks"
                )
            
            return None
        except Exception as e:
            print(f"      ⚠️  Error checking TED spread: {e}")
            return None
    
    def _check_term_premium(self) -> Optional[LeadingSignal]:
        """
        期限溢价 - 持有长期债券的风险补偿
        
        逻辑：溢价上升 → 长期债券需求下降 → 收益率曲线变陡
        危险阈值：快速上升
        """
        try:
            yields = self.macro.get_treasury_yields()
            if not yields or '10Y' not in yields or '2Y' not in yields:
                return None
            
            term_spread = yields['10Y']['rate'] - yields['2Y']['rate']
            
            if term_spread > 1.0 and self._get_curve_change() > 0.2:
                return LeadingSignal(
                    indicator_name="期限溢价 (Term Premium)",
                    current_value=term_spread,
                    change_1d=self._get_curve_change(),
                    change_1w=0.0,
                    direction="rising",
                    severity="normal",
                    implication=f"期限溢价上升至{term_spread:.2f}%，长期债券风险补偿增加",
                    historical_pattern="期限溢价快速上升往往伴随债券抛售",
                    timeframe="1-4 weeks"
                )
            
            return None
        except Exception as e:
            print(f"      ⚠️  Error checking term premium: {e}")
            return None
    
    def _check_copper_gold_ratio(self) -> Optional[LeadingSignal]:
        """
        铜金比 - 经济周期指标
        
        逻辑：铜（工业需求）/ 金（避险），反映经济预期
        下降 → 经济放缓预期
        """
        try:
            if not self.yahoo:
                return None
            
            copper = self.yahoo.get_commodity_data('HG=F')  # 铜期货
            gold = self.yahoo.get_commodity_data('GC=F')   # 黄金期货
            
            if not copper or not gold:
                return None
            
            ratio = copper['close'] / gold['close']
            
            # 获取历史
            historical = self._get_copper_gold_history(days=30)
            if len(historical) >= 20:
                avg_20d = sum(historical[-20:]) / 20
                change_pct = (ratio / avg_20d - 1) * 100
                
                if change_pct < -5:
                    return LeadingSignal(
                        indicator_name="铜金比 (Copper-Gold Ratio)",
                        current_value=ratio,
                        change_1d=change_pct,
                        change_1w=0.0,
                        direction="falling",
                        severity="elevated" if change_pct < -10 else "normal",
                        implication=f"铜金比下跌{abs(change_pct):.1f}%，经济放缓预期强烈",
                        historical_pattern="铜金比领先经济周期3-6个月",
                        timeframe="3-6 months"
                    )
            
            return None
        except Exception as e:
            print(f"      ⚠️  Error checking copper-gold ratio: {e}")
            return None
    
    # ==================== 辅助方法 ====================
    
    def _get_japanese_yield(self) -> Optional[float]:
        """获取日本国债收益率"""
        try:
            # 通过Yahoo Finance获取日本10Y国债ETF
            if self.yahoo:
                jgb = self.yahoo.get_index_data('JGBL')  # 日本国债ETF
                if jgb:
                    return jgb.get('close', 0) / 100  # 简化为收益率
            return 0.5  # 默认估计值
        except:
            return 0.5
    
    def _get_move_index(self) -> Optional[float]:
        """获取MOVE指数（美债波动率）"""
        try:
            # MOVE指数是Merrill Lynch Option Volatility Estimate Index
            # 可以通过 ^MOVE 或 ^TYVIX 获取
            if self.yahoo:
                move = self.yahoo.get_index_data('^MOVE')
                if move:
                    return move.get('close')
            return None
        except:
            return None
    
    def _get_fed_funds_rate(self) -> Optional[float]:
        """获取联邦基金利率"""
        try:
            # 使用SOFR作为代理
            sofr_data = self.macro.get_sofr_rate()
            if sofr_data:
                return sofr_data.get('rate', 5.33)
            return 5.33  # 当前水平估计
        except:
            return 5.33
    
    def _get_dxy_change_1d(self) -> Optional[float]:
        """获取DXY 1日变动"""
        try:
            if self.yahoo:
                dxy = self.yahoo.get_index_data('DX-Y.NYB')
                if dxy:
                    return dxy.get('change_pct', 0)
            return 0.0
        except:
            return 0.0
    
    def _get_curve_change(self) -> float:
        """获取收益率曲线变化"""
        try:
            historical = self._get_curve_history(days=2)
            if len(historical) >= 2:
                return historical[-1] - historical[-2]
            return 0.0
        except:
            return 0.0
    
    # ==================== 历史数据管理 ====================
    
    def _get_spread_history(self, spread_name: str, days: int) -> List[float]:
        """获取利差历史数据（简化实现）"""
        # 实际应用应该从数据库或API获取
        return self.historical_data.get(spread_name, [])
    
    def _get_dxy_history(self, days: int) -> List[float]:
        """获取DXY历史"""
        return self.historical_data.get('dxy', [])
    
    def _get_volatility_history(self, days: int) -> List[float]:
        """获取波动率历史"""
        return self.historical_data.get('volatility', [])
    
    def _get_curve_history(self, days: int) -> List[float]:
        """获取收益率曲线历史"""
        return self.historical_data.get('yield_curve', [])
    
    def _get_copper_gold_history(self, days: int) -> List[float]:
        """获取铜金比历史"""
        return self.historical_data.get('copper_gold', [])
    
    def _calculate_change(self, current: float, historical: List[float], days: int) -> float:
        """计算变动百分比"""
        if not historical or len(historical) < days:
            return 0.0
        
        prev_value = historical[-min(days, len(historical))]
        if prev_value == 0:
            return 0.0
        
        return (current / prev_value - 1) * 100
    
    # ==================== 评估和推荐 ====================
    
    def _assess_liquidity_environment(self, signals: List[LeadingSignal]) -> str:
        """评估整体流动性环境"""
        if not signals:
            return "✅ 全球流动性环境总体稳定，暂无重大领先指标警示"
        
        critical_count = sum(1 for s in signals if s.severity == "critical")
        elevated_count = sum(1 for s in signals if s.severity == "elevated")
        
        if critical_count >= 3:
            return f"🚨 严重流动性危机！{critical_count}个关键领先指标触发危机级别，历史上类似组合预示大幅下跌"
        elif critical_count >= 1 or elevated_count >= 3:
            return f"⚡ 流动性明显收紧！{elevated_count}个指标显示压力，建议采取防御措施"
        elif elevated_count >= 1:
            return f"⚠️ 流动性环境趋紧，{elevated_count}个指标发出警示，保持警惕"
        else:
            return "📊 个别指标显示轻微压力，整体流动性环境尚属正常"
    
    def _match_historical_pattern(self, signals: List[LeadingSignal]) -> Optional[str]:
        """匹配历史模式 - 使用智能模式匹配系统"""
        # 将LeadingSignal对象转换为字典
        signal_dicts = []
        for s in signals:
            signal_dicts.append({
                'indicator_name': s.indicator_name,
                'current_value': s.current_value,
                'severity': s.severity,
                'direction': s.direction
            })
        
        # 使用历史模式管理器进行匹配
        matches = match_historical_patterns(signal_dicts)
        
        if not matches:
            return None
        
        # 格式化匹配结果
        formatted_patterns = []
        for pattern_name, score, description in matches[:3]:  # 取前3个匹配
            if score > 0.5:  # 只显示匹配度>50%的
                formatted_patterns.append(f"{pattern_name} (匹配度{score*100:.0f}%)")
        
        return " | ".join(formatted_patterns) if formatted_patterns else None
    
    def _generate_recommendations(self, signals: List[LeadingSignal], 
                                 liquidity: str) -> List[StrategicRecommendation]:
        """生成战略建议"""
        recommendations = []
        
        critical_count = sum(1 for s in signals if s.severity == "critical")
        elevated_count = sum(1 for s in signals if s.severity == "elevated")
        
        # 根据风险级别生成建议
        if critical_count >= 3:
            recommendations.append(StrategicRecommendation(
                action="reduce",
                urgency="immediate",
                confidence="high",
                rationale=f"多个领先指标同时触发危机级别({critical_count}个)，历史数据显示类似模式通常导致市场大幅下跌10-30%。建议立即降低风险敞口，保护本金。重点关注：科技股QDII、港股、高beta资产。",
                affected_positions=["016532", "017091", "013402", "019455", "007300", "008887"],
                risk_level="high"
            ))
            
            recommendations.append(StrategicRecommendation(
                action="hedge",
                urgency="this_week",
                confidence="high",
                rationale="建议通过黄金(000216)和有色金属(018167, 007910)进行对冲，历史上在流动性危机中表现相对抗跌。",
                affected_positions=["all_equity"],
                risk_level="medium"
            ))
            
        elif critical_count >= 1 or elevated_count >= 3:
            recommendations.append(StrategicRecommendation(
                action="reduce",
                urgency="this_week",
                confidence="medium",
                rationale=f"流动性指标显示明显压力({elevated_count}个 elevated 信号)，建议本周内逐步降低高beta持仓，增配防御性资产。避免在流动性紧张环境中暴露过多风险。",
                affected_positions=["013402", "016532", "017091", "501312"],
                risk_level="medium"
            ))
            
            recommendations.append(StrategicRecommendation(
                action="hold",
                urgency="monitor",
                confidence="high",
                rationale="核心防御配置（黄金、有色）可继续持有作为对冲，同时监控指标变化。",
                affected_positions=["000216", "018167", "007910"],
                risk_level="low"
            ))
            
        elif elevated_count >= 1:
            recommendations.append(StrategicRecommendation(
                action="hold",
                urgency="monitor",
                confidence="medium",
                rationale=f"个别指标显示压力（{elevated_count}个），但不足以改变整体配置。建议密切监控后续发展，准备应对方案。如指标恶化至elevated以上，考虑减仓。",
                affected_positions=["all"],
                risk_level="low"
            ))
        
        else:
            recommendations.append(StrategicRecommendation(
                action="hold",
                urgency="monitor",
                confidence="high",
                rationale="领先指标显示流动性环境相对稳定，维持当前配置。继续定期监控指标变化，特别是美日利差、DXY、MOVE等核心指标。",
                affected_positions=["all"],
                risk_level="low"
            ))
        
        return recommendations
    
    def _determine_warning_level(self, signals: List[LeadingSignal], liquidity: str) -> str:
        """确定预警级别"""
        if not signals:
            return "green"
        
        critical_count = sum(1 for s in signals if s.severity == "critical")
        elevated_count = sum(1 for s in signals if s.severity == "elevated")
        
        if critical_count >= 3 or (critical_count >= 1 and elevated_count >= 2):
            return "red"
        elif critical_count >= 1 or elevated_count >= 3:
            return "orange"
        elif elevated_count >= 1:
            return "yellow"
        else:
            return "green"
    
    def _generate_forward_summary(self, signals: List[LeadingSignal], 
                                 recommendations: List[StrategicRecommendation]) -> str:
        """生成前瞻性总结"""
        if not signals:
            return "领先指标总体稳定，暂无显著警示信号。市场可能继续沿当前趋势运行，建议维持现有配置并持续监控。重点关注即将发布的美联储议息决议和宏观数据。"
        
        immediate_actions = [r for r in recommendations if r.urgency == "immediate"]
        
        if immediate_actions:
            action_str = "、".join([self._action_cn(a.action) for a in immediate_actions])
            return f"🚨 紧急预警！{len([s for s in signals if s.severity == 'critical'])}个领先指标触发危机级别。历史模式匹配显示类似情况通常导致快速大幅下跌，时间窗口可能只有1-3天。建议立即{action_str}，保护投资组合免受流动性危机冲击。"
        
        this_week_actions = [r for r in recommendations if r.urgency == "this_week"]
        if this_week_actions:
            action_str = "、".join([self._action_cn(a.action) for a in this_week_actions])
            return f"⚠️ 领先指标显示流动性环境趋紧（{len(signals)}个信号）。建议本周内{action_str}，为未来可能的波动做好准备。重点关注美日利差、DXY走势和信用利差变化。"
        
        return f"领先指标出现轻微信号（{len(signals)}个），建议保持警惕并密切监控，暂不需要立即行动。如指标恶化至elevated以上，应考虑调整配置。"
    
    def _action_cn(self, action: str) -> str:
        """动作中文翻译"""
        mapping = {
            "increase": "加仓",
            "reduce": "减仓",
            "hold": "持有",
            "hedge": "对冲"
        }
        return mapping.get(action, action)
    
    def _save_report(self, report: EarlyWarningReport):
        """保存预警报告"""
        content = self._format_report_markdown(report)
        
        filename = f"leading_indicator_alert_{datetime.now().strftime('%Y-%m-%d_%H%M')}.md"
        filepath = self.vault.write_knowledge_entry(content, 'macro', filename)
        
        print(f"\n💾 Report saved to: {filepath}")
    
    def _format_report_markdown(self, report: EarlyWarningReport) -> str:
        """格式化为Markdown"""
        level_emoji = {
            "green": "🟢",
            "yellow": "🟡",
            "orange": "🟠",
            "red": "🔴"
        }
        
        md = f"""---
date: {datetime.now().strftime('%Y-%m-%d %H:%M')}
category: leading_indicator_alert
warning_level: {report.warning_level}
generated_by: Leading Indicator Alert System
---

# 🔮 领先指标预警报告 - {datetime.now().strftime('%Y-%m-%d %H:%M')}

**预警级别:** {level_emoji.get(report.warning_level, '⚪')} {report.warning_level.upper()}
**流动性评估:** {report.liquidity_assessment}

## 📊 关键领先指标信号 ({len(report.key_signals)}个)

"""
        
        for signal in report.key_signals:
            severity_emoji = {"normal": "✅", "elevated": "⚠️", "critical": "🚨"}
            md += f"""### {severity_emoji.get(signal.severity, '⚪')} {signal.indicator_name}

- **当前值:** {signal.current_value:.2f}
- **变动:** 1日 {signal.change_1d:+.2f}%, 1周 {signal.change_1w:+.2f}%
- **方向:** {signal.direction}
- **严重程度:** {signal.severity}
- **含义:** {signal.implication}
- **历史模式:** {signal.historical_pattern}
- **预计时间窗口:** {signal.timeframe}

"""
        
        if report.historical_match:
            md += f"""## 🔄 历史模式匹配

**匹配的模式:** {report.historical_match}

系统识别出当前信号组合与历史危机模式相似，建议采取防御性措施。

"""
        
        md += "## 🎯 战略建议\n\n"
        
        for i, rec in enumerate(report.recommendations, 1):
            urgency_emoji = {
                "immediate": "🚨",
                "this_week": "⚡",
                "monitor": "👁️"
            }
            action_emoji = {
                "increase": "📈",
                "reduce": "📉",
                "hold": "✋",
                "hedge": "🛡️"
            }
            
            md += f"""### {i}. {urgency_emoji.get(rec.urgency, '⚪')} {action_emoji.get(rec.action, '⚪')} {self._action_cn(rec.action).upper()}（{rec.urgency}）

**信心度:** {rec.confidence}  
**风险级别:** {rec.risk_level}  
**影响持仓:** {', '.join(rec.affected_positions)}

{rec.rationale}

"""
        
        md += f"""## 🔭 前瞻性总结

{report.forward_looking_summary}

---

## 📈 指标解释

本报告监控的领先指标包括：

1. **美日利差** - 套利交易 unwind 预警
2. **DXY美元指数** - 全球美元流动性
3. **MOVE/VIX指数** - 市场波动率
4. **收益率曲线** - 衰退预警
5. **信用利差** - 企业债压力
6. **SOFR-OIS利差** - 银行间压力
7. **高收益债利差** - 风险情绪
8. **TED利差** - 离岸美元流动性
9. **期限溢价** - 长期债券风险
10. **铜金比** - 经济周期

**免责声明:** 本报告基于领先指标分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。

*Generated by Investment Agent - Leading Indicator System*  
*Data Sources: Federal Reserve, Yahoo Finance, Market Data*
"""
        
        return md
    
    def print_report(self, report: EarlyWarningReport):
        """打印报告到控制台"""
        level_emoji = {
            "green": "🟢",
            "yellow": "🟡",
            "orange": "🟠",
            "red": "🔴"
        }
        
        print("\n" + "="*70)
        print("LEADING INDICATOR ALERT REPORT - FULL")
        print("="*70)
        
        print(f"\n{level_emoji.get(report.warning_level, '⚪')} Warning Level: {report.warning_level.upper()}")
        print(f"📊 Liquidity: {report.liquidity_assessment}")
        
        if report.historical_match:
            print(f"\n🔄 Historical Pattern Match: {report.historical_match}")
        
        print(f"\n📈 Leading Signals ({len(report.key_signals)}):")
        for signal in report.key_signals:
            sev_emoji = {"normal": "✅", "elevated": "⚠️", "critical": "🚨"}
            print(f"   {sev_emoji.get(signal.severity, '⚪')} {signal.indicator_name}")
            print(f"      Value: {signal.current_value:.2f} | {signal.implication[:60]}...")
        
        print(f"\n🎯 Strategic Recommendations:")
        for rec in report.recommendations:
            act_emoji = {"increase": "📈", "reduce": "📉", "hold": "✋", "hedge": "🛡️"}
            print(f"   {act_emoji.get(rec.action, '⚪')} {self._action_cn(rec.action).upper()} ({rec.urgency})")
            print(f"      {rec.rationale[:70]}...")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Leading Indicator Alert System - Full Version'
    )
    
    parser.add_argument(
        '--monitor', '-m',
        action='store_true',
        help='Enable continuous monitoring mode'
    )
    
    parser.add_argument(
        '--interval', '-i',
        type=int,
        default=3600,
        help='Check interval in seconds (default: 3600 = 1 hour)'
    )
    
    args = parser.parse_args()
    
    monitor = LeadingIndicatorMonitor()
    
    if args.monitor:
        print(f"🔄 Starting continuous leading indicator monitoring...")
        print(f"   Check interval: {args.interval} seconds\n")
        
        try:
            while True:
                report = monitor.analyze()
                monitor.print_report(report)
                
                if report.warning_level in ["orange", "red"]:
                    print("\n🚨 SIGNIFICANT WARNING - Review recommendations above")
                
                next_check = datetime.now() + timedelta(seconds=args.interval)
                print(f"\n💤 Next check at {next_check.strftime('%H:%M:%S')}")
                
                import time
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\n👋 Monitoring stopped")
    else:
        report = monitor.analyze()
        monitor.print_report(report)


if __name__ == "__main__":
    main()
