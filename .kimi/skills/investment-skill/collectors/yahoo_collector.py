"""
Yahoo Finance Collector - Global market data collection
Uses yfinance library for free Yahoo Finance data
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import pandas as pd

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("⚠️  yfinance not installed. Install with: pip install yfinance")


class YahooCollector:
    """Collect global market data from Yahoo Finance"""
    
    # Symbol mappings
    INDICES = {
        'SPX': '^GSPC',           # S&P 500
        'DJI': '^DJI',            # Dow Jones
        'IXIC': '^IXIC',          # NASDAQ Composite
        'NDX': '^NDX',            # NASDAQ 100
        'SOX': '^SOX',            # Philadelphia Semiconductor
        'VIX': '^VIX',            # Volatility Index
        'DXY': 'DX-Y.NYB',        # US Dollar Index
        'GLD': 'GC=F',            # Gold futures
        'CL': 'CL=F',             # Crude oil futures
        'BTC': 'BTC-USD',         # Bitcoin
        'HSI': '^HSI',            # Hang Seng Index
        'N225': '^N225',          # Nikkei 225
        'FTSE': '^FTSE',          # FTSE 100
        'GDAXI': '^GDAXI',        # DAX
    }
    
    def __init__(self):
        if not YFINANCE_AVAILABLE:
            raise ImportError("yfinance is required. Install with: pip install yfinance")
    
    def get_index_data(self, symbol: str, period: str = "1d") -> Optional[Dict]:
        """Get index/ETF data
        
        Args:
            symbol: Index symbol (e.g., "SPX", "^GSPC")
            period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            
        Returns:
            Dictionary with market data
        """
        try:
            # Map symbol if needed
            yahoo_symbol = self.INDICES.get(symbol, symbol)
            
            # Get ticker
            ticker = yf.Ticker(yahoo_symbol)
            
            # Get historical data
            hist = ticker.history(period=period)
            
            if hist.empty:
                return None
            
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest
            
            return {
                'symbol': symbol,
                'name': ticker.info.get('shortName', symbol),
                'date': latest.name.strftime('%Y-%m-%d') if hasattr(latest.name, 'strftime') else str(latest.name),
                'open': float(latest['Open']),
                'high': float(latest['High']),
                'low': float(latest['Low']),
                'close': float(latest['Close']),
                'volume': int(latest['Volume']),
                'change': float(latest['Close'] - prev['Close']),
                'change_pct': float((latest['Close'] / prev['Close'] - 1) * 100) if prev['Close'] != 0 else 0,
            }
        except Exception as e:
            print(f"❌ Error fetching {symbol}: {e}")
            return None
    
    def get_stock_data(self, symbol: str) -> Optional[Dict]:
        """Get individual stock data
        
        Args:
            symbol: Stock symbol (e.g., "AAPL", "NVDA")
            
        Returns:
            Dictionary with stock data
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Get current quote
            hist = ticker.history(period="2d")
            
            if hist.empty:
                return None
            
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest
            
            return {
                'symbol': symbol,
                'name': info.get('shortName', symbol),
                'sector': info.get('sector', 'Unknown'),
                'price': float(latest['Close']),
                'change': float(latest['Close'] - prev['Close']),
                'change_pct': float((latest['Close'] / prev['Close'] - 1) * 100) if prev['Close'] != 0 else 0,
                'volume': int(latest['Volume']),
                'market_cap': info.get('marketCap'),
                'pe_ratio': info.get('trailingPE'),
                'pb_ratio': info.get('priceToBook'),
            }
        except Exception as e:
            print(f"❌ Error fetching stock {symbol}: {e}")
            return None
    
    def get_etf_holdings(self, symbol: str) -> Optional[List[Dict]]:
        """Get ETF holdings data
        
        Args:
            symbol: ETF symbol (e.g., "SPY", "QQQ")
            
        Returns:
            List of holdings
        """
        try:
            ticker = yf.Ticker(symbol)
            holdings = ticker.institutional_holders
            
            if holdings is None or holdings.empty:
                return None
            
            return holdings.to_dict('records')
        except Exception as e:
            print(f"❌ Error fetching ETF holdings {symbol}: {e}")
            return None
    
    def get_fx_rate(self, from_currency: str, to_currency: str = "USD") -> Optional[float]:
        """Get foreign exchange rate
        
        Args:
            from_currency: Source currency code (e.g., "CNY", "EUR")
            to_currency: Target currency code (default USD)
            
        Returns:
            Exchange rate
        """
        try:
            symbol = f"{from_currency}{to_currency}=X"
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d")
            
            if hist.empty:
                return None
            
            return float(hist.iloc[-1]['Close'])
        except Exception as e:
            print(f"❌ Error fetching FX rate {from_currency}/{to_currency}: {e}")
            return None
    
    def get_commodity_data(self, symbol: str) -> Optional[Dict]:
        """Get commodity futures data
        
        Args:
            symbol: Commodity symbol (e.g., "GC=F" for gold, "CL=F" for oil)
            
        Returns:
            Dictionary with commodity data
        """
        return self.get_index_data(symbol)
    
    def get_multiple_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get quotes for multiple symbols
        
        Args:
            symbols: List of symbols
            
        Returns:
            Dictionary mapping symbols to their data
        """
        results = {}
        for symbol in symbols:
            data = self.get_index_data(symbol)
            if data:
                results[symbol] = data
        return results
    
    def get_historical_data(self, symbol: str, period: str = "1mo", 
                           interval: str = "1d") -> Optional[pd.DataFrame]:
        """Get historical OHLCV data
        
        Args:
            symbol: Symbol to fetch
            period: Data period
            interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)
            
        Returns:
            DataFrame with historical data
        """
        try:
            yahoo_symbol = self.INDICES.get(symbol, symbol)
            ticker = yf.Ticker(yahoo_symbol)
            return ticker.history(period=period, interval=interval)
        except Exception as e:
            print(f"❌ Error fetching historical data for {symbol}: {e}")
            return None
    
    def get_semiconductor_stocks(self) -> Dict[str, Dict]:
        """Get major semiconductor stocks data
        
        Returns:
            Dictionary with major chip stocks
        """
        chip_stocks = ['NVDA', 'AMD', 'INTC', 'QCOM', 'AVGO', 'TSM', 'ASML']
        return self.get_multiple_quotes(chip_stocks)
    
    def get_magnificent_seven(self) -> Dict[str, Dict]:
        """Get Magnificent 7 stocks data
        
        Returns:
            Dictionary with MAG7 stocks
        """
        mag7 = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA']
        return self.get_multiple_quotes(mag7)
    
    def get_fear_greed_index(self) -> Optional[Dict]:
        """Get CNN Fear & Greed Index data
        
        Note: This requires additional scraping as yfinance doesn't provide it directly
        """
        # Placeholder - would need to implement CNN scraping
        return None


# Convenience functions
def get_yahoo_collector() -> Optional[YahooCollector]:
    """Get Yahoo collector instance"""
    if YFINANCE_AVAILABLE:
        return YahooCollector()
    return None


def quick_quote(symbol: str) -> Optional[Dict]:
    """Quick function to get a quote"""
    collector = get_yahoo_collector()
    if collector:
        return collector.get_index_data(symbol)
    return None
