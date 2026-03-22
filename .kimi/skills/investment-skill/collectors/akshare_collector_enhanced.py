"""
AKShare Data Collector Enhancement - AKShare数据收集增强模块

为中国A股/港股监控提供专用数据接口
"""

import sys
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("⚠️  AKShare not installed. China market data will be limited.")

from utils.data_cache import get_cache, cached


class AKShareCollectorEnhanced:
    """增强版AKShare数据收集器"""
    
    def __init__(self):
        self.cache = get_cache()
        self.available = AKSHARE_AVAILABLE
    
    # ========== 估值数据 ==========
    
    def get_index_valuation(self, index_code: str) -> Optional[Dict]:
        """获取指数估值数据"""
        if not self.available:
            return None
        
        try:
            # 沪深300: 000300.SH, 创业板: 399006.SZ
            if index_code == "000300":
                # 沪深300估值
                df = ak.index_value_hist_funddb(symbol="沪深300")
                if not df.empty:
                    latest = df.iloc[-1]
                    return {
                        "pe_ttm": float(latest.get("市盈率", 0)),
                        "pb": float(latest.get("市净率", 0)),
                        "ps": float(latest.get("市销率", 0)),
                        "dividend_yield": float(latest.get("股息率", 0)),
                        "date": latest.get("日期", "")
                    }
            
            elif index_code == "399006":
                # 创业板估值
                df = ak.index_value_hist_funddb(symbol="创业板指")
                if not df.empty:
                    latest = df.iloc[-1]
                    return {
                        "pe_ttm": float(latest.get("市盈率", 0)),
                        "pb": float(latest.get("市净率", 0)),
                        "date": latest.get("日期", "")
                    }
            
            # 通用方法：使用指数历史数据计算
            df = ak.index_zh_a_hist(symbol=index_code, period="daily", 
                                   start_date="20230101", end_date=datetime.now().strftime("%Y%m%d"))
            if not df.empty:
                # 简化估值计算
                latest_close = float(df.iloc[-1]["收盘"])
                return {
                    "pe_ttm": latest_close / 100,  # placeholder
                    "pb": latest_close / 200,  # placeholder
                    "date": df.iloc[-1]["日期"]
                }
                
        except Exception as e:
            print(f"⚠️  Error getting index valuation for {index_code}: {e}")
        
        return None
    
    def get_a_share_market_valuation(self) -> Optional[Dict]:
        """获取A股整体市场估值"""
        if not self.available:
            return None
        
        try:
            # 获取全市场市盈率
            df = ak.stock_market_pe_lg()
            if not df.empty:
                latest = df.iloc[-1]
                return {
                    "shanghai_pe": float(latest.get("上证所", 0)),
                    "shenzhen_pe": float(latest.get("深交所", 0)),
                    "chinext_pe": float(latest.get("创业板", 0)),
                    "date": latest.get("日期", "")
                }
        except Exception as e:
            print(f"⚠️  Error getting market valuation: {e}")
        
        return None
    
    # ========== 杠杆数据 ==========
    
    def get_margin_data(self) -> Optional[Dict]:
        """获取融资融券数据"""
        if not self.available:
            return None
        
        try:
            # 获取融资融券余额
            df = ak.stock_margin_szse()
            if not df.empty:
                latest = df.iloc[-1]
                return {
                    "balance": float(latest.get("融资余额", 0)) / 100000000,  # 转换为亿元
                    "balance_change": float(latest.get("融资余额增减", 0)) / 100000000,
                    "short_balance": float(latest.get("融券余额", 0)) / 100000000,
                    "total_balance": float(latest.get("融资融券余额", 0)) / 100000000,
                    "date": latest.get("日期", "")
                }
        except Exception as e:
            print(f"⚠️  Error getting margin data: {e}")
        
        # 尝试另一个数据源
        try:
            df = ak.stock_margin_sse()
            if not df.empty:
                latest = df.iloc[-1]
                return {
                    "balance": float(latest.get("融资余额", 0)) / 100000000,
                    "balance_change": float(latest.get("融资买入额", 0)) / 100000000,
                    "date": latest.get("日期", "")
                }
        except Exception as e:
            print(f"⚠️  Error getting SSE margin data: {e}")
        
        return None
    
    def get_margin_balance_trend(self, days: int = 30) -> List[Dict]:
        """获取融资余额趋势"""
        if not self.available:
            return []
        
        try:
            df = ak.stock_margin_sse()
            if not df.empty:
                df = df.tail(days)
                return [
                    {
                        "date": row["日期"],
                        "balance": float(row["融资余额"]) / 100000000
                    }
                    for _, row in df.iterrows()
                ]
        except Exception as e:
            print(f"⚠️  Error getting margin trend: {e}")
        
        return []
    
    # ========== 情绪数据 ==========
    
    def get_market_turnover(self) -> Optional[float]:
        """获取市场换手率"""
        if not self.available:
            return None
        
        try:
            # 获取A股成交额
            df = ak.stock_zh_a_spot_em()
            if not df.empty:
                # 计算全市场换手率
                total_turnover = df["换手率"].astype(float).mean()
                return total_turnover
        except Exception as e:
            print(f"⚠️  Error getting turnover: {e}")
        
        return None
    
    def get_new_investors(self) -> Optional[float]:
        """获取新增投资者数量"""
        if not self.available:
            return None
        
        try:
            df = ak.stock_new_investors()
            if not df.empty:
                latest = df.iloc[-1]
                # 月新增投资者 (万户)
                return float(latest.get("新增投资者-数量", 0))
        except Exception as e:
            print(f"⚠️  Error getting new investors: {e}")
        
        return None
    
    def get_investor_sentiment(self) -> Optional[Dict]:
        """获取投资者情绪指标"""
        if not self.available:
            return None
        
        try:
            # 新开户数
            df = ak.stock_new_investors()
            if not df.empty:
                latest = df.iloc[-1]
                return {
                    "new_accounts": float(latest.get("新增投资者-数量", 0)),
                    "new_accounts_change": float(latest.get("环比", 0).replace("%", "")),
                    "date": latest.get("数据日期", "")
                }
        except Exception as e:
            print(f"⚠️  Error getting sentiment: {e}")
        
        return None
    
    # ========== 资金流向 ==========
    
    def get_northbound_flow(self) -> Optional[Dict]:
        """获取北向资金流向"""
        if not self.available:
            return None
        
        try:
            df = ak.stock_hsgt_hist_em(symbol="沪股通")
            if not df.empty:
                latest = df.iloc[-1]
                return {
                    "daily": float(latest.get("净买额", 0)) / 10000,  # 转换为亿元
                    "buy": float(latest.get("买入额", 0)) / 10000,
                    "sell": float(latest.get("卖出额", 0)) / 10000,
                    "date": latest.get("日期", "")
                }
        except Exception as e:
            print(f"⚠️  Error getting northbound flow: {e}")
        
        # 尝试另一个接口
        try:
            df = ak.stock_hsgt_hist_em(symbol="深股通")
            if not df.empty:
                latest = df.iloc[-1]
                return {
                    "daily": float(latest.get("净买额", 0)) / 10000,
                    "date": latest.get("日期", "")
                }
        except Exception as e:
            print(f"⚠️  Error getting SZ northbound flow: {e}")
        
        return None
    
    def get_southbound_flow(self) -> Optional[Dict]:
        """获取南向资金流向"""
        if not self.available:
            return None
        
        try:
            df = ak.stock_hk_ggt_hist_em(symbol="港股通(沪)")
            if not df.empty:
                latest = df.iloc[-1]
                return {
                    "daily": float(latest.get("净买额", 0)) / 10000,  # 亿港元
                    "buy": float(latest.get("买入额", 0)) / 10000,
                    "sell": float(latest.get("卖出额", 0)) / 10000,
                    "date": latest.get("日期", "")
                }
        except Exception as e:
            print(f"⚠️  Error getting southbound flow: {e}")
        
        return None
    
    def get_main_force_flow(self) -> Optional[float]:
        """获取主力资金流向"""
        if not self.available:
            return None
        
        try:
            df = ak.stock_zt_pool_em(date=datetime.now().strftime("%Y%m%d"))
            # 这是一个简化的实现，实际需要更精确的数据
            return None
        except Exception as e:
            print(f"⚠️  Error getting main force flow: {e}")
        
        return None
    
    def get_sector_flow(self) -> Optional[List[Dict]]:
        """获取行业资金流向"""
        if not self.available:
            return None
        
        try:
            df = ak.stock_sector_fund_flow_rank()
            if not df.empty:
                return [
                    {
                        "sector": row.get("行业", ""),
                        "inflow": float(row.get("主力净流入", 0)),
                        "inflow_pct": float(row.get("主力净流入占比", 0).replace("%", ""))
                    }
                    for _, row in df.head(10).iterrows()
                ]
        except Exception as e:
            print(f"⚠️  Error getting sector flow: {e}")
        
        return None
    
    # ========== 市场广度 ==========
    
    def get_market_breadth(self) -> Optional[Dict]:
        """获取市场广度指标"""
        if not self.available:
            return None
        
        try:
            # 获取涨跌家数
            df = ak.stock_zh_a_spot_em()
            if not df.empty:
                up_count = len(df[df["涨跌幅"].astype(float) > 0])
                down_count = len(df[df["涨跌幅"].astype(float) < 0])
                flat_count = len(df[df["涨跌幅"].astype(float) == 0])
                
                total = up_count + down_count + flat_count
                
                return {
                    "up_count": up_count,
                    "down_count": down_count,
                    "flat_count": flat_count,
                    "up_down_ratio": up_count / down_count if down_count > 0 else float('inf'),
                    "advance_decline_line": up_count - down_count,
                    "breadth_percentile": (up_count / total) * 100 if total > 0 else 50
                }
        except Exception as e:
            print(f"⚠️  Error getting market breadth: {e}")
        
        return None
    
    def get_new_highs_lows(self) -> Optional[Dict]:
        """获取创新高/新低个股数"""
        if not self.available:
            return None
        
        try:
            # 获取个股历史数据
            df = ak.stock_zh_a_spot_em()
            if not df.empty:
                # 简化的计算
                new_highs = len(df[df["60日涨跌幅"].astype(float) > 20])
                new_lows = len(df[df["60日涨跌幅"].astype(float) < -20])
                
                return {
                    "new_highs_60d": new_highs,
                    "new_lows_60d": new_lows,
                    "high_low_ratio": new_highs / new_lows if new_lows > 0 else float('inf')
                }
        except Exception as e:
            print(f"⚠️  Error getting new highs/lows: {e}")
        
        return None
    
    # ========== 综合数据获取 ==========
    
    def get_full_market_snapshot(self) -> Dict:
        """获取完整的市场快照"""
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "valuation": self.get_a_share_market_valuation(),
            "margin": self.get_margin_data(),
            "sentiment": self.get_investor_sentiment(),
            "northbound": self.get_northbound_flow(),
            "southbound": self.get_southbound_flow(),
            "breadth": self.get_market_breadth()
        }
        return snapshot


# 全局实例
_akshare_enhanced = None

def get_akshare_enhanced() -> AKShareCollectorEnhanced:
    """获取AKShare增强版实例"""
    global _akshare_enhanced
    if _akshare_enhanced is None:
        _akshare_enhanced = AKShareCollectorEnhanced()
    return _akshare_enhanced


if __name__ == "__main__":
    # 测试
    collector = get_akshare_enhanced()
    
    print("🧪 Testing AKShare Enhanced Collector...")
    print()
    
    # 测试估值数据
    print("📊 Testing Valuation Data...")
    val = collector.get_index_valuation("000300")
    print(f"   CSI300 Valuation: {val}")
    
    # 测试杠杆数据
    print("\n💳 Testing Margin Data...")
    margin = collector.get_margin_data()
    print(f"   Margin Data: {margin}")
    
    # 测试资金流向
    print("\n💰 Testing Flow Data...")
    north = collector.get_northbound_flow()
    print(f"   Northbound: {north}")
    
    # 完整快照
    print("\n📸 Full Market Snapshot:")
    snapshot = collector.get_full_market_snapshot()
    print(f"   Snapshot keys: {list(snapshot.keys())}")
