"""
AKShare Collector - Chinese market data collection using AKShare
Free, open-source Python library for Chinese financial data
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import pandas as pd

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("⚠️  AKShare not installed. Install with: pip install akshare")


class AKShareCollector:
    """Collect Chinese market data using AKShare"""
    
    def __init__(self):
        if not AKSHARE_AVAILABLE:
            raise ImportError("AKShare is required. Install with: pip install akshare")
    
    def get_fund_nav(self, fund_code: str) -> Optional[Dict]:
        """Get fund NAV history
        
        Args:
            fund_code: Fund code (e.g., "000216")
            
        Returns:
            Dictionary with NAV data
        """
        try:
            # Get fund NAV history
            df = ak.fund_open_fund_daily_em()
            
            # Filter for specific fund
            fund_data = df[df['基金代码'] == fund_code]
            
            if fund_data.empty:
                return None
            
            latest = fund_data.iloc[0]
            
            return {
                'code': fund_code,
                'name': latest.get('基金简称', ''),
                'nav': float(latest.get('单位净值', 0)),
                'accumulated_nav': float(latest.get('累计净值', 0)),
                'daily_change': float(latest.get('日增长率', 0)),
                'date': latest.get('日期', datetime.now().strftime('%Y-%m-%d')),
            }
        except Exception as e:
            print(f"❌ Error fetching NAV for {fund_code}: {e}")
            return None
    
    def get_fund_performance(self, fund_code: str) -> Optional[Dict]:
        """Get fund performance metrics
        
        Args:
            fund_code: Fund code
            
        Returns:
            Dictionary with performance data
        """
        try:
            # Get fund info
            df = ak.fund_individual_basic_info_xq(symbol=fund_code)
            
            # Extract performance metrics
            performance = {}
            for _, row in df.iterrows():
                item = row.get('item', '')
                value = row.get('value', '')
                
                if '近1月' in item:
                    performance['return_1m'] = self._parse_percent(value)
                elif '近3月' in item:
                    performance['return_3m'] = self._parse_percent(value)
                elif '近6月' in item:
                    performance['return_6m'] = self._parse_percent(value)
                elif '近1年' in item:
                    performance['return_1y'] = self._parse_percent(value)
                elif '今年来' in item:
                    performance['return_ytd'] = self._parse_percent(value)
            
            return performance
        except Exception as e:
            print(f"❌ Error fetching performance for {fund_code}: {e}")
            return None
    
    def get_index_quote(self, index_code: str) -> Optional[Dict]:
        """Get index quote
        
        Args:
            index_code: Index code (e.g., "000300" for CSI 300)
            
        Returns:
            Dictionary with index data
        """
        try:
            # Get real-time quote
            df = ak.stock_zh_index_daily_em(symbol=index_code)
            
            if df.empty:
                return None
            
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            
            return {
                'code': index_code,
                'date': latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else str(latest['date']),
                'open': float(latest['open']),
                'high': float(latest['high']),
                'low': float(latest['low']),
                'close': float(latest['close']),
                'volume': float(latest['volume']),
                'change_pct': (latest['close'] / prev['close'] - 1) * 100 if prev['close'] != 0 else 0,
            }
        except Exception as e:
            print(f"❌ Error fetching index {index_code}: {e}")
            return None
    
    def get_stock_quote(self, stock_code: str) -> Optional[Dict]:
        """Get stock quote
        
        Args:
            stock_code: Stock code with exchange prefix (e.g., "sh600519")
            
        Returns:
            Dictionary with stock data
        """
        try:
            # Get real-time quote
            df = ak.stock_zh_a_spot_em()
            
            # Filter for specific stock
            stock_data = df[df['代码'] == stock_code.replace('sh', '').replace('sz', '')]
            
            if stock_data.empty:
                return None
            
            latest = stock_data.iloc[0]
            
            return {
                'code': stock_code,
                'name': latest.get('名称', ''),
                'price': float(latest.get('最新价', 0)),
                'change': float(latest.get('涨跌幅', 0)),
                'volume': float(latest.get('成交量', 0)),
                'turnover': float(latest.get('成交额', 0)),
            }
        except Exception as e:
            print(f"❌ Error fetching stock {stock_code}: {e}")
            return None
    
    def get_etf_list(self) -> pd.DataFrame:
        """Get all ETF list"""
        try:
            return ak.fund_etf_category_sina(symbol="ETF基金")
        except Exception as e:
            print(f"❌ Error fetching ETF list: {e}")
            return pd.DataFrame()
    
    def get_fund_list(self) -> pd.DataFrame:
        """Get all mutual fund list"""
        try:
            return ak.fund_open_fund_daily_em()
        except Exception as e:
            print(f"❌ Error fetching fund list: {e}")
            return pd.DataFrame()
    
    def get_hk_index(self, index_symbol: str = "HSI") -> Optional[Dict]:
        """Get Hong Kong index
        
        Args:
            index_symbol: Index symbol (e.g., "HSI" for Hang Seng)
            
        Returns:
            Dictionary with index data
        """
        try:
            df = ak.index_investing_global_area_index_name_code(symbol="香港")
            
            # Find specific index
            index_data = df[df['名称'].str.contains(index_symbol, na=False)]
            
            if index_data.empty:
                return None
            
            # Get detailed quote
            code = index_data.iloc[0].get('代码', '')
            quote_df = ak.index_investing_global(symbol=code, period="每日")
            
            if quote_df.empty:
                return None
            
            latest = quote_df.iloc[-1]
            
            return {
                'code': index_symbol,
                'date': str(latest.get('日期', datetime.now())),
                'close': float(latest.get('收盘', 0)),
                'open': float(latest.get('开盘', 0)),
                'high': float(latest.get('最高', 0)),
                'low': float(latest.get('最低', 0)),
                'volume': float(latest.get('成交量', 0)),
            }
        except Exception as e:
            print(f"❌ Error fetching HK index {index_symbol}: {e}")
            return None
    
    def get_macro_data(self, indicator: str) -> Optional[pd.DataFrame]:
        """Get macro economic data
        
        Args:
            indicator: Indicator name (e.g., "中国国债收益率", "货币供应量")
            
        Returns:
            DataFrame with macro data
        """
        try:
            if "国债" in indicator or "yield" in indicator.lower():
                return ak.bond_zh_us_rate()
            elif "货币" in indicator or "M2" in indicator:
                return ak.macro_china_money_supply()
            elif "CPI" in indicator:
                return ak.macro_china_cpi()
            elif "PPI" in indicator:
                return ak.macro_china_ppi()
            else:
                return None
        except Exception as e:
            print(f"❌ Error fetching macro data {indicator}: {e}")
            return None
    
    def _parse_percent(self, value: str) -> Optional[float]:
        """Parse percentage string"""
        try:
            if isinstance(value, str):
                # Remove % and convert
                cleaned = value.replace('%', '').replace('+', '').strip()
                return float(cleaned)
            return float(value)
        except:
            return None


# Convenience functions
def get_collector() -> Optional[AKShareCollector]:
    """Get AKShare collector instance"""
    if AKSHARE_AVAILABLE:
        return AKShareCollector()
    return None
