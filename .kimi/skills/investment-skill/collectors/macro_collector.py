"""
Macro Collector - Collect macroeconomic data
Federal Reserve, World Bank, and other sources
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import pandas as pd
import requests
from io import StringIO


class MacroCollector:
    """Collect macroeconomic indicators"""
    
    FRED_API_BASE = "https://api.stlouisfed.org/fred"
    
    # Common FRED series IDs
    FRED_SERIES = {
        'fed_balance_sheet': 'WALCL',           # Federal Reserve Total Assets
        'fed_rate': 'DFF',                       # Federal Funds Effective Rate
        'treasury_10y': 'DGS10',                 # 10-Year Treasury Rate
        'treasury_2y': 'DGS2',                   # 2-Year Treasury Rate
        'sofr': 'SOFR',                          # Secured Overnight Financing Rate
        'move_index': 'MOVE',                    # MOVE Index (bond volatility)
        'usd_index': 'DTWEXBGS',                 # Trade Weighted US Dollar Index
        'cpi': 'CPIAUCSL',                       # Consumer Price Index
        'core_cpi': 'CPILFESL',                  # Core CPI
        'ppi': 'PPIACO',                         # Producer Price Index
        'unemployment': 'UNRATE',                # Unemployment Rate
        'nonfarm_payroll': 'PAYEMS',             # Nonfarm Payrolls
        'm2_money': 'M2SL',                      # M2 Money Supply
    }
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize macro collector
        
        Args:
            api_key: FRED API key (optional, some data available without)
        """
        self.api_key = api_key
        self.session = requests.Session()
    
    def get_fed_balance_sheet(self) -> Optional[Dict]:
        """Get Federal Reserve balance sheet data"""
        try:
            url = f"{self.FRED_API_BASE}/series/observations"
            params = {
                'series_id': self.FRED_SERIES['fed_balance_sheet'],
                'api_key': self.api_key,
                'file_type': 'json',
                'sort_order': 'desc',
                'limit': 10,
            }
            
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                observations = data.get('observations', [])
                
                if observations:
                    latest = observations[0]
                    prev = observations[1] if len(observations) > 1 else latest
                    
                    current = float(latest['value'])
                    previous = float(prev['value'])
                    
                    return {
                        'indicator': 'Fed Balance Sheet',
                        'date': latest['date'],
                        'value': current,
                        'change': current - previous,
                        'change_pct': (current / previous - 1) * 100 if previous != 0 else 0,
                        'unit': 'USD Billions',
                    }
            
            return None
        except Exception as e:
            print(f"❌ Error fetching Fed balance sheet: {e}")
            return None
    
    def get_treasury_yields(self) -> Optional[Dict]:
        """Get US Treasury yields"""
        try:
            results = {}
            
            for name, series_id in [
                ('10Y', self.FRED_SERIES['treasury_10y']),
                ('2Y', self.FRED_SERIES['treasury_2y']),
            ]:
                url = f"{self.FRED_API_BASE}/series/observations"
                params = {
                    'series_id': series_id,
                    'api_key': self.api_key,
                    'file_type': 'json',
                    'sort_order': 'desc',
                    'limit': 5,
                }
                
                response = self.session.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    observations = data.get('observations', [])
                    
                    if observations:
                        latest = observations[0]
                        prev_week = observations[-1]
                        
                        results[name] = {
                            'date': latest['date'],
                            'rate': float(latest['value']),
                            'weekly_change': float(latest['value']) - float(prev_week['value']),
                        }
            
            # Calculate spread
            if '10Y' in results and '2Y' in results:
                results['10Y2Y_spread'] = results['10Y']['rate'] - results['2Y']['rate']
            
            return results
        except Exception as e:
            print(f"❌ Error fetching Treasury yields: {e}")
            return None
    
    def get_dollar_index(self) -> Optional[Dict]:
        """Get US Dollar Index (DXY)"""
        try:
            # Use FRED data if available, otherwise scrape from investing.com
            url = f"{self.FRED_API_BASE}/series/observations"
            params = {
                'series_id': self.FRED_SERIES['usd_index'],
                'api_key': self.api_key,
                'file_type': 'json',
                'sort_order': 'desc',
                'limit': 5,
            }
            
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                observations = data.get('observations', [])
                
                if observations:
                    latest = observations[0]
                    
                    return {
                        'indicator': 'US Dollar Index',
                        'date': latest['date'],
                        'value': float(latest['value']),
                        'alert_level': self._get_dxy_alert(float(latest['value'])),
                    }
            
            return None
        except Exception as e:
            print(f"❌ Error fetching Dollar Index: {e}")
            return None
    
    def get_sofr_rate(self) -> Optional[Dict]:
        """Get SOFR (Secured Overnight Financing Rate)"""
        try:
            url = f"{self.FRED_API_BASE}/series/observations"
            params = {
                'series_id': self.FRED_SERIES['sofr'],
                'api_key': self.api_key,
                'file_type': 'json',
                'sort_order': 'desc',
                'limit': 5,
            }
            
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                observations = data.get('observations', [])
                
                if observations:
                    latest = observations[0]
                    
                    return {
                        'indicator': 'SOFR',
                        'date': latest['date'],
                        'rate': float(latest['value']),
                        'alert': float(latest['value']) > 5.5,
                    }
            
            return None
        except Exception as e:
            print(f"❌ Error fetching SOFR: {e}")
            return None
    
    def get_liquidity_metrics(self) -> Optional[Dict]:
        """Get comprehensive liquidity metrics
        
        Calculates Net Liquidity = Fed Balance Sheet - TGA - Reverse Repo
        """
        try:
            # This is a simplified version
            # Full calculation would need TGA and ON RRP data
            
            fed_bs = self.get_fed_balance_sheet()
            yields = self.get_treasury_yields()
            dxy = self.get_dollar_index()
            
            metrics = {
                'fed_balance_sheet': fed_bs,
                'treasury_yields': yields,
                'dollar_index': dxy,
                'timestamp': datetime.now().isoformat(),
            }
            
            # Calculate overall liquidity assessment
            if fed_bs and dxy:
                metrics['liquidity_assessment'] = self._assess_liquidity(fed_bs, dxy)
            
            return metrics
        except Exception as e:
            print(f"❌ Error calculating liquidity metrics: {e}")
            return None
    
    def get_yield_curve(self) -> Optional[pd.DataFrame]:
        """Get current yield curve data"""
        try:
            maturities = ['1M', '3M', '6M', '1Y', '2Y', '5Y', '10Y', '30Y']
            series_map = {
                '1M': 'DGS1MO',
                '3M': 'DGS3MO',
                '6M': 'DGS6MO',
                '1Y': 'DGS1',
                '2Y': 'DGS2',
                '5Y': 'DGS5',
                '10Y': 'DGS10',
                '30Y': 'DGS30',
            }
            
            data = []
            for maturity, series_id in series_map.items():
                url = f"{self.FRED_API_BASE}/series/observations"
                params = {
                    'series_id': series_id,
                    'api_key': self.api_key,
                    'file_type': 'json',
                    'sort_order': 'desc',
                    'limit': 1,
                }
                
                response = self.session.get(url, params=params, timeout=10)
                
                if response.status_code == 200:
                    result = response.json()
                    observations = result.get('observations', [])
                    
                    if observations:
                        data.append({
                            'maturity': maturity,
                            'yield': float(observations[0]['value']),
                            'date': observations[0]['date'],
                        })
            
            return pd.DataFrame(data) if data else None
        except Exception as e:
            print(f"❌ Error fetching yield curve: {e}")
            return None
    
    def _get_dxy_alert(self, value: float) -> str:
        """Get alert level for DXY"""
        if value > 105:
            return "STRONG_USD"
        elif value < 100:
            return "WEAK_USD"
        return "NEUTRAL"
    
    def _assess_liquidity(self, fed_bs: Dict, dxy: Dict) -> str:
        """Assess overall liquidity conditions"""
        alerts = []
        
        # Check Fed balance sheet trend
        if fed_bs.get('change_pct', 0) < -5:
            alerts.append("Fed balance sheet contracting >5%")
        
        # Check DXY
        if dxy.get('value', 100) > 105:
            alerts.append("Dollar strength may tighten global liquidity")
        
        if alerts:
            return f"TIGHTENING: {'; '.join(alerts)}"
        
        return "NEUTRAL"


# Convenience functions
def get_macro_collector(api_key: Optional[str] = None) -> MacroCollector:
    """Get macro collector instance"""
    return MacroCollector(api_key)
