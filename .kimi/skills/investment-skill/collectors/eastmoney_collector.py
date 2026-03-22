"""
EastMoney Collector - Web scraping fund data from EastMoney
Uses Playwright for browser automation
"""
import asyncio
import re
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass

# Note: Playwright import will be available after installation
# For now, we create the structure
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@dataclass
class FundData:
    """Fund data structure"""
    code: str
    name: str
    nav: float                      # Net Asset Value
    nav_date: str                   # NAV date
    daily_change: float             # Daily change percentage
    daily_change_amount: float      # Daily change in currency
    
    # Performance data
    return_1m: Optional[float] = None
    return_3m: Optional[float] = None
    return_6m: Optional[float] = None
    return_1y: Optional[float] = None
    return_ytd: Optional[float] = None
    
    # Additional info
    fund_type: Optional[str] = None
    risk_level: Optional[str] = None
    fund_size: Optional[float] = None   # In billions
    manager: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'name': self.name,
            'nav': self.nav,
            'nav_date': self.nav_date,
            'daily_change': self.daily_change,
            'daily_change_amount': self.daily_change_amount,
            'return_1m': self.return_1m,
            'return_3m': self.return_3m,
            'return_6m': self.return_6m,
            'return_1y': self.return_1y,
            'return_ytd': self.return_ytd,
            'fund_type': self.fund_type,
            'risk_level': self.risk_level,
            'fund_size': self.fund_size,
            'manager': self.manager,
        }


class EastMoneyCollector:
    """Collect fund data from EastMoney (天天基金网)"""
    
    BASE_URL = "https://fund.eastmoney.com"
    
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
    
    async def __aenter__(self):
        if PLAYWRIGHT_AVAILABLE:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
    
    async def fetch_fund_data(self, fund_code: str) -> Optional[FundData]:
        """Fetch fund data from EastMoney
        
        Args:
            fund_code: Fund code (e.g., "019455")
            
        Returns:
            FundData object or None if failed
        """
        if not PLAYWRIGHT_AVAILABLE:
            print("⚠️  Playwright not installed. Install with: pip install playwright")
            print("   Then run: playwright install chromium")
            return None
        
        url = f"{self.BASE_URL}/{fund_code}.html"
        
        try:
            await self.page.goto(url, wait_until="networkidle")
            await asyncio.sleep(2)  # Wait for JS to load
            
            # Extract basic info
            name = await self._extract_text('.fundDetail-tit', fund_code)
            
            # Extract NAV
            nav_text = await self._extract_text('.ui-font-large.ui-color-red, .ui-font-large.ui-color-green, .ui-font-large.ui-color-black', '')
            nav = self._parse_float(nav_text)
            
            # Extract daily change
            change_text = await self._extract_text('.ui-font-middle', '')
            change_pct = self._parse_change_percent(change_text)
            
            # Extract date
            date_text = await self._extract_text('.fundDetail-info .left', '')
            nav_date = self._extract_date(date_text)
            
            # Extract performance metrics
            performance = await self._extract_performance()
            
            # Extract fund info
            fund_type = await self._extract_info_item('基金类型')
            risk_level = await self._extract_info_item('风险等级')
            fund_size = await self._extract_info_item('基金规模')
            manager = await self._extract_info_item('基金经理')
            
            return FundData(
                code=fund_code,
                name=name or f"Fund-{fund_code}",
                nav=nav,
                nav_date=nav_date or datetime.now().strftime('%Y-%m-%d'),
                daily_change=change_pct,
                daily_change_amount=0.0,  # Will calculate
                return_1m=performance.get('1m'),
                return_3m=performance.get('3m'),
                return_6m=performance.get('6m'),
                return_1y=performance.get('1y'),
                return_ytd=performance.get('ytd'),
                fund_type=fund_type,
                risk_level=risk_level,
                fund_size=self._parse_size(fund_size),
                manager=manager,
            )
            
        except Exception as e:
            print(f"❌ Error fetching fund {fund_code}: {e}")
            return None
    
    async def fetch_multiple_funds(self, fund_codes: List[str]) -> List[FundData]:
        """Fetch data for multiple funds
        
        Args:
            fund_codes: List of fund codes
            
        Returns:
            List of FundData objects
        """
        results = []
        for code in fund_codes:
            data = await self.fetch_fund_data(code)
            if data:
                results.append(data)
            await asyncio.sleep(1)  # Rate limiting
        return results
    
    async def _extract_text(self, selector: str, default: str = '') -> str:
        """Extract text from page using selector"""
        try:
            element = await self.page.query_selector(selector)
            if element:
                return await element.inner_text() or default
        except:
            pass
        return default
    
    async def _extract_performance(self) -> Dict[str, float]:
        """Extract performance metrics"""
        performance = {}
        
        # Try to find performance table
        try:
            # Look for common performance labels
            labels = ['近1月', '近3月', '近6月', '近1年', '今年来']
            keys = ['1m', '3m', '6m', '1y', 'ytd']
            
            for label, key in zip(labels, keys):
                cells = await self.page.query_selector_all('td, th, .ui-num, .num')
                for cell in cells:
                    text = await cell.inner_text()
                    if label in text:
                        # Find next cell with value
                        next_cell = await cell.evaluate('el => el.nextElementSibling?.innerText')
                        if next_cell:
                            performance[key] = self._parse_change_percent(next_cell)
                        break
        except:
            pass
        
        return performance
    
    async def _extract_info_item(self, label: str) -> Optional[str]:
        """Extract info item by label"""
        try:
            # Look for label in info table
            elements = await self.page.query_selector_all('th, td, .infoItem, .detail-list dt, .detail-list dd')
            for i, el in enumerate(elements):
                text = await el.inner_text()
                if label in text and i + 1 < len(elements):
                    value = await elements[i + 1].inner_text()
                    return value.strip()
        except:
            pass
        return None
    
    def _parse_float(self, text: str) -> float:
        """Parse float from text"""
        try:
            # Remove currency symbols and commas
            cleaned = re.sub(r'[^\d.\-]', '', text)
            return float(cleaned) if cleaned else 0.0
        except:
            return 0.0
    
    def _parse_change_percent(self, text: str) -> float:
        """Parse percentage change"""
        try:
            # Extract number with sign
            match = re.search(r'([\-+]?\d+\.?\d*)\s*%', text)
            if match:
                return float(match.group(1))
            return 0.0
        except:
            return 0.0
    
    def _extract_date(self, text: str) -> str:
        """Extract date from text"""
        try:
            match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
            if match:
                return match.group(1)
            # Try other formats
            match = re.search(r'(\d{4}年\d{2}月\d{2}日)', text)
            if match:
                date_str = match.group(1)
                return date_str.replace('年', '-').replace('月', '-').replace('日', '')
        except:
            pass
        return datetime.now().strftime('%Y-%m-%d')
    
    def _parse_size(self, text: str) -> Optional[float]:
        """Parse fund size in billions"""
        try:
            if '亿' in text:
                match = re.search(r'(\d+\.?\d*)\s*亿', text)
                if match:
                    return float(match.group(1))
        except:
            pass
        return None


# Synchronous wrapper for convenience
def fetch_fund(fund_code: str) -> Optional[FundData]:
    """Synchronous wrapper to fetch single fund"""
    async def _fetch():
        async with EastMoneyCollector() as collector:
            return await collector.fetch_fund_data(fund_code)
    
    return asyncio.run(_fetch())


def fetch_funds(fund_codes: List[str]) -> List[FundData]:
    """Synchronous wrapper to fetch multiple funds"""
    async def _fetch():
        async with EastMoneyCollector() as collector:
            return await collector.fetch_multiple_funds(fund_codes)
    
    return asyncio.run(_fetch())
