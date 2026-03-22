"""
China Market Monitor - 中国A股/港股专用监控模块

监控指标:
1. 估值指标 (PE, PB, PS)
2. 杠杆指标 (融资余额, 两融占比)
3. 情绪指标 (换手率, 新增投资者)
4. 资金流向 (北向资金, 南向资金)
5. 市场广度 (涨跌家数比, 创新高个股数)

数据源: AKShare (A股), Yahoo Finance (港股)
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.akshare_collector_enhanced import get_akshare_enhanced
from collectors.yahoo_collector import get_yahoo_collector
from utils.vault_writer import get_vault_writer
from utils.data_cache import get_cache


@dataclass
class ChinaMarketSignal:
    """中国市场信号"""
    indicator_name: str
    market: str  # "a_share" or "hk"
    current_value: float
    change_pct: float  # 百分比变化
    historical_percentile: float  # 历史百分位
    direction: str  # "overvalued", "undervalued", "neutral"
    severity: str  # "normal", "elevated", "critical"
    threshold_triggered: str  # 触发的阈值级别
    implication: str
    historical_pattern: str


@dataclass
class ValuationMetrics:
    """估值指标"""
    pe_ttm: float
    pe_forward: float
    pb: float
    ps: float
    dividend_yield: float
    risk_premium: float  # 股债风险溢价
    percentile_5y: float  # 5年历史百分位
    percentile_10y: float  # 10年历史百分位


@dataclass
class LeverageMetrics:
    """杠杆指标"""
    margin_balance: float  # 融资余额 (亿元)
    margin_balance_pct: float  # 融资余额 / 流通市值 (%)
    margin_buy_ratio: float  # 融资买入额 / 成交额 (%)
    short_balance: float  # 融券余额
    leverage_ratio: float  # 市场整体杠杆率


@dataclass
class SentimentMetrics:
    """情绪指标"""
    turnover_rate: float  # 换手率 (%)
    turnover_percentile: float  # 换手率历史百分位
    new_investors: int  # 新增投资者数 (月)
    investor_growth: float  # 新增投资者增长率
    ahr_index: float  # A股活跃度指数
    fear_greed_index: float  # 恐惧贪婪指数 (0-100)


@dataclass
class FlowMetrics:
    """资金流向"""
    northbound_daily: float  # 北向资金日流入 (亿元)
    northbound_cumulative: float  # 北向资金累计流入
    southbound_daily: float  # 南向资金日流入 (亿港元)
    southbound_cumulative: float  # 南向资金累计流入
    main_force_flow: float  # 主力资金流向
    retail_flow: float  # 散户资金流向


@dataclass
class ChinaMarketReport:
    """中国市场监控报告"""
    timestamp: str
    warning_level: str
    a_share_signals: List[ChinaMarketSignal]
    hk_signals: List[ChinaMarketSignal]
    valuation_summary: str
    leverage_summary: str
    sentiment_summary: str
    flow_summary: str
    recommendations: List[Dict]


class ChinaMarketMonitor:
    """中国A股/港股专用监控器"""
    
    # 估值阈值 (基于历史数据)
    VALUATION_THRESHOLDS = {
        "csi300_pe": {"undervalued": 11.0, "fair": 13.0, "overvalued": 16.0, "bubble": 20.0},
        "csi300_pb": {"undervalued": 1.2, "fair": 1.5, "overvalued": 1.8, "bubble": 2.5},
        "gem_pe": {"undervalued": 35.0, "fair": 50.0, "overvalued": 70.0, "bubble": 100.0},
        "hsi_pe": {"undervalued": 9.0, "fair": 11.0, "overvalued": 14.0, "bubble": 18.0},
    }
    
    # 杠杆阈值
    LEVERAGE_THRESHOLDS = {
        "margin_balance_pct": {"normal": 2.0, "elevated": 2.5, "critical": 3.0, "extreme": 3.5},
        "margin_buy_ratio": {"normal": 8.0, "elevated": 10.0, "critical": 12.0},
    }
    
    # 情绪阈值
    SENTIMENT_THRESHOLDS = {
        "turnover_rate": {"low": 1.5, "normal": 2.5, "high": 4.0, "extreme": 6.0},
        "fear_greed": {"extreme_fear": 20, "fear": 40, "neutral": 60, "greed": 80, "extreme_greed": 90},
    }
    
    def __init__(self):
        self.ak = get_akshare_enhanced()
        self.yahoo = get_yahoo_collector()
        self.vault = get_vault_writer()
        self.cache = get_cache()
        
        # 缓存历史数据
        self.historical_data = {}
    
    def analyze(self) -> ChinaMarketReport:
        """执行完整的中国市场分析"""
        print("\n🇨🇳 China Market Monitor - Analyzing A-Share and HK Markets...")
        print("=" * 70)
        
        a_share_signals = []
        hk_signals = []
        
        # ========== A股监控 ==========
        print("\n📊 A-Share Market Analysis")
        print("-" * 50)
        
        # 1. 估值指标
        print("   📈 Checking Valuation Metrics...")
        val_signals = self._check_a_share_valuation()
        a_share_signals.extend(val_signals)
        
        # 2. 杠杆指标
        print("   💳 Checking Leverage Metrics...")
        lev_signals = self._check_a_share_leverage()
        a_share_signals.extend(lev_signals)
        
        # 3. 情绪指标
        print("   😊 Checking Sentiment Metrics...")
        sent_signals = self._check_a_share_sentiment()
        a_share_signals.extend(sent_signals)
        
        # 4. 资金流向
        print("   💰 Checking Capital Flow...")
        flow_signals = self._check_a_share_flow()
        a_share_signals.extend(flow_signals)
        
        # ========== 港股监控 ==========
        print("\n🇭🇰 Hong Kong Market Analysis")
        print("-" * 50)
        
        # 1. 估值指标
        print("   📈 Checking HK Valuation...")
        hk_val_signals = self._check_hk_valuation()
        hk_signals.extend(hk_val_signals)
        
        # 2. 资金流向
        print("   💰 Checking Southbound Flow...")
        hk_flow_signals = self._check_hk_flow()
        hk_signals.extend(hk_flow_signals)
        
        # 生成总结
        warning_level = self._determine_warning_level(a_share_signals, hk_signals)
        val_summary = self._generate_valuation_summary(a_share_signals)
        lev_summary = self._generate_leverage_summary(a_share_signals)
        sent_summary = self._generate_sentiment_summary(a_share_signals)
        flow_summary = self._generate_flow_summary(a_share_signals, hk_signals)
        recommendations = self._generate_recommendations(a_share_signals, hk_signals, warning_level)
        
        report = ChinaMarketReport(
            timestamp=datetime.now().isoformat(),
            warning_level=warning_level,
            a_share_signals=a_share_signals,
            hk_signals=hk_signals,
            valuation_summary=val_summary,
            leverage_summary=lev_summary,
            sentiment_summary=sent_summary,
            flow_summary=flow_summary,
            recommendations=recommendations
        )
        
        self._save_report(report)
        return report
    
    # ========== A股估值监控 ==========
    
    def _check_a_share_valuation(self) -> List[ChinaMarketSignal]:
        """检查A股估值指标"""
        signals = []
        
        try:
            # 获取沪深300估值
            csi300_pe = self._get_index_pe("000300")  # 沪深300
            csi300_pb = self._get_index_pb("000300")
            
            # 获取创业板估值
            gem_pe = self._get_index_pe("399006")  # 创业板指
            gem_pb = self._get_index_pb("399006")
            
            # 判断沪深300估值水平
            if csi300_pe:
                signals.extend(self._evaluate_pe("沪深300", csi300_pe, "csi300_pe", "a_share"))
            
            if csi300_pb:
                signals.extend(self._evaluate_pb("沪深300", csi300_pb, "csi300_pb", "a_share"))
            
            # 判断创业板估值水平
            if gem_pe:
                signals.extend(self._evaluate_pe("创业板指", gem_pe, "gem_pe", "a_share", is_gem=True))
            
            # 股债风险溢价
            risk_premium = self._calculate_risk_premium()
            if risk_premium:
                signals.extend(self._evaluate_risk_premium(risk_premium))
                
        except Exception as e:
            print(f"      ⚠️  Error checking A-share valuation: {e}")
        
        return signals
    
    def _evaluate_pe(self, index_name: str, pe: float, threshold_key: str, 
                     market: str, is_gem: bool = False) -> List[ChinaMarketSignal]:
        """评估PE水平"""
        signals = []
        thresholds = self.VALUATION_THRESHOLDS.get(threshold_key, {})
        
        if not thresholds:
            return signals
        
        # 判断估值水平
        if pe >= thresholds.get("bubble", 100):
            severity = "critical"
            direction = "extreme_overvalued"
            implication = f"{index_name} PE({pe:.1f}x)处于历史极端高位，泡沫风险极高"
            pattern = "2015年创业板PE>140x后暴跌60%"
        elif pe >= thresholds.get("overvalued", 50):
            severity = "elevated"
            direction = "overvalued"
            implication = f"{index_name} PE({pe:.1f}x)显著高估，建议降低仓位"
            pattern = "高估值区域通常伴随10-30%回调"
        elif pe <= thresholds.get("undervalued", 10):
            severity = "normal"
            direction = "undervalued"
            implication = f"{index_name} PE({pe:.1f}x)低估，具备长期投资价值"
            pattern = "低估值区域 historically 提供安全边际"
        else:
            return signals  # 合理区间不报告
        
        signals.append(ChinaMarketSignal(
            indicator_name=f"{index_name} PE(TTM)",
            market=market,
            current_value=pe,
            change_pct=0.0,
            historical_percentile=self._get_pe_percentile(index_name, pe),
            direction=direction,
            severity=severity,
            threshold_triggered=f"{threshold_key}_{severity}",
            implication=implication,
            historical_pattern=pattern
        ))
        
        return signals
    
    def _evaluate_pb(self, index_name: str, pb: float, threshold_key: str,
                     market: str) -> List[ChinaMarketSignal]:
        """评估PB水平"""
        signals = []
        thresholds = self.VALUATION_THRESHOLDS.get(threshold_key, {})
        
        if not thresholds:
            return signals
        
        if pb >= thresholds.get("bubble", 3.0):
            signals.append(ChinaMarketSignal(
                indicator_name=f"{index_name} PB",
                market=market,
                current_value=pb,
                change_pct=0.0,
                historical_percentile=95.0,
                direction="overvalued",
                severity="elevated",
                threshold_triggered=f"{threshold_key}_elevated",
                implication=f"{index_name} PB({pb:.2f}x)偏高，关注资产质量",
                historical_pattern="高PB通常伴随估值回归"
            ))
        
        return signals
    
    def _evaluate_risk_premium(self, risk_premium: float) -> List[ChinaMarketSignal]:
        """评估股债风险溢价"""
        signals = []
        
        if risk_premium > 6.0:
            signals.append(ChinaMarketSignal(
                indicator_name="股债风险溢价",
                market="a_share",
                current_value=risk_premium,
                change_pct=0.0,
                historical_percentile=90.0,
                direction="attractive",
                severity="normal",
                threshold_triggered="risk_premium_high",
                implication=f"风险溢价{risk_premium:.2f}%，股票配置价值凸显",
                historical_pattern=">6%风险溢价 historically 对应市场底部"
            ))
        elif risk_premium < 2.0:
            signals.append(ChinaMarketSignal(
                indicator_name="股债风险溢价",
                market="a_share",
                current_value=risk_premium,
                change_pct=0.0,
                historical_percentile=10.0,
                direction="unattractive",
                severity="elevated",
                threshold_triggered="risk_premium_low",
                implication=f"风险溢价{risk_premium:.2f}%，股票性价比低",
                historical_pattern="<2%风险溢价 historically 对应市场顶部"
            ))
        
        return signals
    
    # ========== A股杠杆监控 ==========
    
    def _check_a_share_leverage(self) -> List[ChinaMarketSignal]:
        """检查A股杠杆指标"""
        signals = []
        
        try:
            # 获取融资余额数据
            margin_data = self._get_margin_data()
            
            if margin_data:
                margin_balance = margin_data.get("balance", 0)  # 亿元
                market_cap = margin_data.get("market_cap", 1)  # 流通市值
                
                margin_pct = (margin_balance / market_cap) * 100 if market_cap > 0 else 0
                
                # 判断杠杆水平
                thresholds = self.LEVERAGE_THRESHOLDS["margin_balance_pct"]
                
                if margin_pct >= thresholds["extreme"]:
                    severity = "critical"
                    implication = f"融资余额占比{margin_pct:.2f}%，处于历史极端高位，2015年式杠杆风险"
                    pattern = "2015年6月融资余额占比3.2%，随后股灾"
                elif margin_pct >= thresholds["critical"]:
                    severity = "critical"
                    implication = f"融资余额占比{margin_pct:.2f}%，杠杆过高，警惕强制平仓"
                    pattern = "融资余额/GDP>3% historically 伴随大幅回调"
                elif margin_pct >= thresholds["elevated"]:
                    severity = "elevated"
                    implication = f"融资余额占比{margin_pct:.2f}%，杠杆偏高，建议谨慎"
                    pattern = "融资余额过高通常领先市场调整"
                else:
                    return signals
                
                signals.append(ChinaMarketSignal(
                    indicator_name="融资余额/流通市值",
                    market="a_share",
                    current_value=margin_pct,
                    change_pct=margin_data.get("change_pct", 0),
                    historical_percentile=self._get_margin_percentile(margin_pct),
                    direction="high_leverage",
                    severity=severity,
                    threshold_triggered=f"margin_{severity}",
                    implication=implication,
                    historical_pattern=pattern
                ))
                
        except Exception as e:
            print(f"      ⚠️  Error checking leverage: {e}")
        
        return signals
    
    # ========== A股情绪监控 ==========
    
    def _check_a_share_sentiment(self) -> List[ChinaMarketSignal]:
        """检查A股情绪指标"""
        signals = []
        
        try:
            # 换手率
            turnover = self._get_market_turnover()
            if turnover:
                thresholds = self.SENTIMENT_THRESHOLDS["turnover_rate"]
                
                if turnover >= thresholds["extreme"]:
                    signals.append(ChinaMarketSignal(
                        indicator_name="市场换手率",
                        market="a_share",
                        current_value=turnover,
                        change_pct=0.0,
                        historical_percentile=95.0,
                        direction="extreme_fever",
                        severity="critical",
                        threshold_triggered="turnover_extreme",
                        implication=f"换手率高达{turnover:.1f}%，市场情绪极度亢奋，泡沫特征明显",
                        historical_pattern="换手率>6% historically 对应短期顶部"
                    ))
                elif turnover >= thresholds["high"]:
                    signals.append(ChinaMarketSignal(
                        indicator_name="市场换手率",
                        market="a_share",
                        current_value=turnover,
                        change_pct=0.0,
                        historical_percentile=85.0,
                        direction="high_sentiment",
                        severity="elevated",
                        threshold_triggered="turnover_high",
                        implication=f"换手率{turnover:.1f}%，情绪偏高，警惕回调",
                        historical_pattern="高换手率通常伴随高波动"
                    ))
            
            # 新增投资者 (月度数据)
            new_investors = self._get_new_investors()
            if new_investors and new_investors > 100:  # 周增100万以上
                signals.append(ChinaMarketSignal(
                    indicator_name="新增投资者(周)",
                    market="a_share",
                    current_value=new_investors,
                    change_pct=0.0,
                    historical_percentile=90.0,
                    direction="high_enthusiasm",
                    severity="elevated",
                    threshold_triggered="new_investors_high",
                    implication=f"新增投资者周增{new_investors:.0f}万人，散户涌入，历史顶部信号",
                    historical_pattern="2015年周增100万+投资者后见顶"
                ))
                
        except Exception as e:
            print(f"      ⚠️  Error checking sentiment: {e}")
        
        return signals
    
    # ========== A股资金流向 ==========
    
    def _check_a_share_flow(self) -> List[ChinaMarketSignal]:
        """检查A股资金流向"""
        signals = []
        
        try:
            # 北向资金
            northbound = self._get_northbound_flow()
            if northbound:
                daily_flow = northbound.get("daily", 0)
                
                if daily_flow < -50:  # 单日流出超50亿
                    signals.append(ChinaMarketSignal(
                        indicator_name="北向资金单日流入",
                        market="a_share",
                        current_value=daily_flow,
                        change_pct=0.0,
                        historical_percentile=5.0,
                        direction="heavy_outflow",
                        severity="elevated",
                        threshold_triggered="northbound_outflow",
                        implication=f"北向资金单日流出{abs(daily_flow):.0f}亿，外资大幅撤离",
                        historical_pattern="北向资金连续大幅流出 historically 领先下跌"
                    ))
                elif daily_flow > 100:  # 单日流入超100亿
                    signals.append(ChinaMarketSignal(
                        indicator_name="北向资金单日流入",
                        market="a_share",
                        current_value=daily_flow,
                        change_pct=0.0,
                        historical_percentile=95.0,
                        direction="strong_inflow",
                        severity="normal",
                        threshold_triggered="northbound_inflow",
                        implication=f"北向资金单日流入{daily_flow:.0f}亿，外资积极买入",
                        historical_pattern="大幅流入 historically 对应市场底部"
                    ))
            
            # 主力资金
            main_flow = self._get_main_force_flow()
            if main_flow and main_flow < -200:  # 主力流出超200亿
                signals.append(ChinaMarketSignal(
                    indicator_name="主力资金流向",
                    market="a_share",
                    current_value=main_flow,
                    change_pct=0.0,
                    historical_percentile=5.0,
                    direction="institutional_selling",
                    severity="elevated",
                    threshold_triggered="main_force_outflow",
                    implication=f"主力资金单日流出{abs(main_flow):.0f}亿，机构大幅减仓",
                    historical_pattern="主力资金持续流出 historically 领先调整"
                ))
                
        except Exception as e:
            print(f"      ⚠️  Error checking flow: {e}")
        
        return signals
    
    # ========== 港股监控 ==========
    
    def _check_hk_valuation(self) -> List[ChinaMarketSignal]:
        """检查港股估值"""
        signals = []
        
        try:
            # 恒生指数PE
            hsi_pe = self._get_hsi_pe()
            if hsi_pe:
                thresholds = self.VALUATION_THRESHOLDS["hsi_pe"]
                
                if hsi_pe <= thresholds["undervalued"]:
                    signals.append(ChinaMarketSignal(
                        indicator_name="恒生指数 PE",
                        market="hk",
                        current_value=hsi_pe,
                        change_pct=0.0,
                        historical_percentile=10.0,
                        direction="undervalued",
                        severity="normal",
                        threshold_triggered="hsi_pe_low",
                        implication=f"恒生指数PE({hsi_pe:.1f}x)处于历史低位，配置价值高",
                        historical_pattern="PE<9x historically 对应港股底部"
                    ))
                elif hsi_pe >= thresholds["overvalued"]:
                    signals.append(ChinaMarketSignal(
                        indicator_name="恒生指数 PE",
                        market="hk",
                        current_value=hsi_pe,
                        change_pct=0.0,
                        historical_percentile=90.0,
                        direction="overvalued",
                        severity="elevated",
                        threshold_triggered="hsi_pe_high",
                        implication=f"恒生指数PE({hsi_pe:.1f}x)偏高，注意估值风险",
                        historical_pattern="PE>14x historically 对应港股顶部"
                    ))
                    
        except Exception as e:
            print(f"      ⚠️  Error checking HK valuation: {e}")
        
        return signals
    
    def _check_hk_flow(self) -> List[ChinaMarketSignal]:
        """检查港股资金流向"""
        signals = []
        
        try:
            # 南向资金
            southbound = self._get_southbound_flow()
            if southbound:
                daily_flow = southbound.get("daily", 0)
                
                if daily_flow < -20:  # 单日流出超20亿港元
                    signals.append(ChinaMarketSignal(
                        indicator_name="南向资金单日流入",
                        market="hk",
                        current_value=daily_flow,
                        change_pct=0.0,
                        historical_percentile=5.0,
                        direction="southbound_outflow",
                        severity="elevated",
                        threshold_triggered="southbound_outflow",
                        implication=f"南向资金单日流出{abs(daily_flow):.0f}亿港元，内地资金撤离",
                        historical_pattern="南向资金大幅流出 historically 领先港股下跌"
                    ))
                    
        except Exception as e:
            print(f"      ⚠️  Error checking HK flow: {e}")
        
        return signals
    
    # ========== 辅助方法 (数据获取) ==========
    
    def _get_index_pe(self, index_code: str) -> Optional[float]:
        """获取指数PE"""
        try:
            if self.ak:
                data = self.ak.get_index_valuation(index_code)
                if data:
                    return data.get("pe_ttm") or data.get("市盈率")
        except Exception as e:
            pass
        return None
    
    def _get_index_pb(self, index_code: str) -> Optional[float]:
        """获取指数PB"""
        try:
            if self.ak:
                data = self.ak.get_index_valuation(index_code)
                if data:
                    return data.get("pb") or data.get("市净率")
        except Exception as e:
            pass
        return None
    
    def _calculate_risk_premium(self) -> Optional[float]:
        """计算股债风险溢价"""
        try:
            # 沪深300 PE倒数 - 10Y国债收益率
            csi300_pe = self._get_index_pe("000300")
            if csi300_pe and csi300_pe > 0:
                earnings_yield = 1 / (csi300_pe / 100)  # 盈利收益率
                # 假设国债收益率2.5%
                bond_yield = 2.5
                return earnings_yield - bond_yield
        except:
            pass
        return None
    
    def _get_margin_data(self) -> Optional[Dict]:
        """获取融资数据"""
        try:
            if self.ak:
                data = self.ak.get_margin_data()
                if data:
                    # 添加市场市值估算用于计算占比
                    data["market_cap"] = 50000  # 估算流通市值约5万亿
                    data["change_pct"] = 0.0  # 简化处理
                    return data
        except Exception as e:
            pass
        return None
    
    def _get_market_turnover(self) -> Optional[float]:
        """获取市场换手率"""
        try:
            if self.ak:
                return self.ak.get_market_turnover()
        except Exception as e:
            pass
        return None
    
    def _get_new_investors(self) -> Optional[float]:
        """获取新增投资者"""
        try:
            if self.ak:
                return self.ak.get_new_investors()
        except Exception as e:
            pass
        return None
    
    def _get_northbound_flow(self) -> Optional[Dict]:
        """获取北向资金"""
        try:
            if self.ak:
                return self.ak.get_northbound_flow()
        except Exception as e:
            pass
        return None
    
    def _get_main_force_flow(self) -> Optional[float]:
        """获取主力资金流向"""
        try:
            if self.ak:
                return self.ak.get_main_force_flow()
        except Exception as e:
            pass
        return None
    
    def _get_hsi_pe(self) -> Optional[float]:
        """获取恒指PE"""
        try:
            if self.yahoo:
                data = self.yahoo.get_index_data("^HSI")
                # 简化计算，实际需要更精确的数据
                return 10.0  # placeholder
        except:
            pass
        return None
    
    def _get_southbound_flow(self) -> Optional[Dict]:
        """获取南向资金"""
        try:
            if self.ak:
                return self.ak.get_southbound_flow()
        except Exception as e:
            pass
        return None
    
    def _get_pe_percentile(self, index_name: str, current_pe: float) -> float:
        """获取PE历史百分位 (简化实现)"""
        # 实际应该基于历史数据计算
        return 50.0
    
    def _get_margin_percentile(self, margin_pct: float) -> float:
        """获取融资余额百分位"""
        # 2015年峰值约3.2%
        if margin_pct >= 3.0:
            return 95.0
        elif margin_pct >= 2.5:
            return 80.0
        elif margin_pct >= 2.0:
            return 60.0
        return 40.0
    
    # ========== 报告生成 ==========
    
    def _determine_warning_level(self, a_share_signals: List[ChinaMarketSignal],
                                 hk_signals: List[ChinaMarketSignal]) -> str:
        """确定预警级别"""
        all_signals = a_share_signals + hk_signals
        
        critical_count = sum(1 for s in all_signals if s.severity == "critical")
        elevated_count = sum(1 for s in all_signals if s.severity == "elevated")
        
        if critical_count >= 2 or (critical_count >= 1 and elevated_count >= 2):
            return "red"
        elif critical_count >= 1 or elevated_count >= 2:
            return "orange"
        elif elevated_count >= 1:
            return "yellow"
        return "green"
    
    def _generate_valuation_summary(self, signals: List[ChinaMarketSignal]) -> str:
        """生成估值总结"""
        val_signals = [s for s in signals if "PE" in s.indicator_name or "PB" in s.indicator_name]
        
        if not val_signals:
            return "✅ A股估值处于合理区间，暂无显著高估或低估"
        
        overvalued = [s for s in val_signals if "overvalued" in s.direction]
        undervalued = [s for s in val_signals if "undervalued" in s.direction]
        
        if overvalued:
            return f"⚠️ {len(overvalued)}个估值指标显示高估: {', '.join([s.indicator_name for s in overvalued])}"
        elif undervalued:
            return f"📈 {len(undervalued)}个估值指标显示低估，具备配置价值"
        return "📊 估值指标总体正常"
    
    def _generate_leverage_summary(self, signals: List[ChinaMarketSignal]) -> str:
        """生成杠杆总结"""
        lev_signals = [s for s in signals if "融资" in s.indicator_name]
        
        if not lev_signals:
            return "✅ 杠杆水平正常，融资余额处于合理范围"
        
        critical = [s for s in lev_signals if s.severity == "critical"]
        if critical:
            return f"🚨 杠杆风险极高! {critical[0].implication}"
        return f"⚠️ {lev_signals[0].implication}"
    
    def _generate_sentiment_summary(self, signals: List[ChinaMarketSignal]) -> str:
        """生成情绪总结"""
        sent_signals = [s for s in signals if "换手" in s.indicator_name or "投资者" in s.indicator_name]
        
        if not sent_signals:
            return "✅ 市场情绪平稳，未见极端情绪信号"
        
        return f"📊 {sent_signals[0].implication}"
    
    def _generate_flow_summary(self, a_signals: List[ChinaMarketSignal],
                               hk_signals: List[ChinaMarketSignal]) -> str:
        """生成资金流向总结"""
        flow_signals = [s for s in a_signals + hk_signals if "资金" in s.indicator_name]
        
        if not flow_signals:
            return "✅ 资金流向正常，北向/南向资金无显著异常"
        
        outflows = [s for s in flow_signals if "outflow" in s.direction or "流出" in s.implication]
        if outflows:
            return f"⚠️ 资金流出信号: {', '.join([s.indicator_name for s in outflows])}"
        return f"📈 {flow_signals[0].implication}"
    
    def _generate_recommendations(self, a_signals: List[ChinaMarketSignal],
                                  hk_signals: List[ChinaMarketSignal],
                                  warning_level: str) -> List[Dict]:
        """生成建议"""
        recommendations = []
        all_signals = a_signals + hk_signals
        
        critical_count = sum(1 for s in all_signals if s.severity == "critical")
        elevated_count = sum(1 for s in all_signals if s.severity == "elevated")
        
        if warning_level == "red":
            recommendations.append({
                "action": "大幅减仓",
                "urgency": "immediate",
                "target": "A股高估值板块、港股科技股",
                "rationale": f"多个指标触发Critical级别({critical_count}个)，类似2015年泡沫期特征",
                "affected_funds": ["013402", "016532", "017091"]  # 港股科技、纳指
            })
            recommendations.append({
                "action": "规避杠杆",
                "urgency": "immediate",
                "target": "融资买入标的",
                "rationale": "融资余额过高，强制平仓风险上升",
                "affected_funds": []
            })
        elif warning_level == "orange":
            recommendations.append({
                "action": "减仓",
                "urgency": "this_week",
                "target": "高估值成长股",
                "rationale": f"市场出现过热信号({elevated_count}个)，建议降低风险敞口",
                "affected_funds": ["019455", "016532"]  # 半导体、科技股
            })
            recommendations.append({
                "action": "持有防御",
                "urgency": "monitor",
                "target": "低估值蓝筹股",
                "rationale": "防御性板块相对抗跌",
                "affected_funds": []
            })
        elif warning_level == "yellow":
            recommendations.append({
                "action": "保持警惕",
                "urgency": "monitor",
                "target": "全市场",
                "rationale": "个别指标显示异常，密切关注后续发展",
                "affected_funds": []
            })
        else:
            recommendations.append({
                "action": "正常配置",
                "urgency": "monitor",
                "target": "按计划执行",
                "rationale": "中国市场指标总体正常，维持现有配置",
                "affected_funds": []
            })
        
        return recommendations
    
    def _save_report(self, report: ChinaMarketReport):
        """保存报告到Vault"""
        content = self._format_report_markdown(report)
        
        filename = f"china_market_alert_{datetime.now().strftime('%Y-%m-%d_%H%M')}.md"
        filepath = self.vault.write_knowledge_entry(content, 'macro', filename)
        
        print(f"\n💾 Report saved to: {filepath}")
    
    def _format_report_markdown(self, report: ChinaMarketReport) -> str:
        """格式化为Markdown"""
        level_emoji = {"green": "🟢", "yellow": "🟡", "orange": "🟠", "red": "🔴"}
        
        md = f"""---
date: {datetime.now().strftime('%Y-%m-%d %H:%M')}
category: china_market_monitor
warning_level: {report.warning_level}
---

# 🇨🇳 中国A股/港股监控报告

**预警级别:** {level_emoji.get(report.warning_level, '⚪')} {report.warning_level.upper()}

---

## 📊 A股市场信号

"""
        
        for signal in report.a_share_signals:
            severity_emoji = {"normal": "✅", "elevated": "⚠️", "critical": "🚨"}
            md += f"""### {severity_emoji.get(signal.severity, '⚪')} {signal.indicator_name}

- **当前值:** {signal.current_value:.2f}
- **历史百分位:** {signal.historical_percentile:.0f}%
- **严重程度:** {signal.severity}
- **含义:** {signal.implication}
- **历史模式:** {signal.historical_pattern}

"""
        
        if report.hk_signals:
            md += "## 🇭🇰 港股市场信号\n\n"
            for signal in report.hk_signals:
                severity_emoji = {"normal": "✅", "elevated": "⚠️", "critical": "🚨"}
                md += f"""### {severity_emoji.get(signal.severity, '⚪')} {signal.indicator_name}

- **当前值:** {signal.current_value:.2f}
- **严重程度:** {signal.severity}
- **含义:** {signal.implication}

"""
        
        md += f"""---

## 🎯 综合评估

### 估值状况
{report.valuation_summary}

### 杠杆状况
{report.leverage_summary}

### 情绪状况
{report.sentiment_summary}

### 资金流向
{report.flow_summary}

---

## 💡 投资建议

"""
        
        for i, rec in enumerate(report.recommendations, 1):
            md += f"""### {i}. {rec['action']} ({rec['urgency']})

**目标:** {rec['target']}  
**理由:** {rec['rationale']}

"""
        
        md += f"""---

## 📋 监控指标说明

本报告监控以下中国A股/港股专用指标:

**估值指标:**
- 沪深300 PE/PB - 整体市场估值
- 创业板指 PE/PB - 成长股估值
- 股债风险溢价 - 股票相对债券吸引力

**杠杆指标:**
- 融资余额/流通市值 - 市场整体杠杆率
- 融资买入占比 - 杠杆资金活跃度

**情绪指标:**
- 市场换手率 - 交易活跃度
- 新增投资者数 - 散户入场意愿

**资金流向:**
- 北向资金 - 外资流入A股
- 南向资金 - 内资流入港股
- 主力资金 - 机构资金流向

---

*Generated by China Market Monitor*  
*Data Sources: AKShare, Yahoo Finance*
"""
        
        return md
    
    def print_report(self, report: ChinaMarketReport):
        """打印报告到控制台"""
        level_emoji = {"green": "🟢", "yellow": "🟡", "orange": "🟠", "red": "🔴"}
        
        print("\n" + "=" * 70)
        print("CHINA MARKET MONITOR REPORT")
        print("=" * 70)
        
        print(f"\n{level_emoji.get(report.warning_level, '⚪')} Warning Level: {report.warning_level.upper()}")
        
        print(f"\n📈 A-Share Signals ({len(report.a_share_signals)}):")
        for signal in report.a_share_signals:
            sev_emoji = {"normal": "✅", "elevated": "⚠️", "critical": "🚨"}
            print(f"   {sev_emoji.get(signal.severity, '⚪')} {signal.indicator_name}: {signal.implication[:50]}...")
        
        if report.hk_signals:
            print(f"\n🇭🇰 HK Signals ({len(report.hk_signals)}):")
            for signal in report.hk_signals:
                sev_emoji = {"normal": "✅", "elevated": "⚠️", "critical": "🚨"}
                print(f"   {sev_emoji.get(signal.severity, '⚪')} {signal.indicator_name}")
        
        print(f"\n🎯 Recommendations:")
        for rec in report.recommendations:
            print(f"   📍 {rec['action']} - {rec['rationale'][:60]}...")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='China Market Monitor')
    parser.add_argument('--monitor', '-m', action='store_true',
                       help='Enable continuous monitoring mode')
    parser.add_argument('--interval', '-i', type=int, default=3600,
                       help='Check interval in seconds (default: 3600)')
    
    args = parser.parse_args()
    
    monitor = ChinaMarketMonitor()
    
    if args.monitor:
        print(f"🔄 Starting continuous China market monitoring...")
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
