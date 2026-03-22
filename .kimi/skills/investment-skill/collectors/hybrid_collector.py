"""
Hybrid Collector - Fast API first, Playwright fallback

Strategy:
1. Try fast HTTP API first (0.1s, works for 83% funds)
2. If empty/fails, try Playwright (5-10s, covers 100%)
3. Cache results to minimize slow calls
"""
import asyncio
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
import time

from .fast_collector import fetch_fund_fast as fast_fetch, FundData as FastFundData
from .eastmoney_collector import EastMoneyCollector, FundData

# Handle both relative and absolute imports
try:
    from ..utils.data_cache import cached
except ImportError:
    # Fallback: define no-op cache decorator if not available
    def cached(ttl=300):
        def decorator(func):
            return func
        return decorator


class HybridCollector:
    """
    Intelligent collector that uses fast API first,
    falls back to Playwright only when necessary
    """
    
    def __init__(self):
        self.playwright_collector: Optional[EastMoneyCollector] = None
        self._playwright_available = None
    
    def _check_playwright(self) -> bool:
        """Check if Playwright is available"""
        if self._playwright_available is None:
            try:
                from playwright.async_api import async_playwright
                self._playwright_available = True
            except ImportError:
                self._playwright_available = False
        return self._playwright_available
    
    @cached(ttl=300)  # 5 minute cache
    def fetch_fund(self, fund_code: str) -> Optional[FundData]:
        """
        Fetch fund data with automatic fallback
        
        Order:
        1. Fast API (0.1s)
        2. Playwright fallback (5-10s) if fast fails
        """
        # Step 1: Try fast API
        fast_result = fast_fetch(fund_code)
        
        if fast_result and fast_result.name:
            # Convert FastFundData to FundData
            return FundData(
                code=fast_result.code,
                name=fast_result.name,
                nav=fast_result.nav,
                nav_date=fast_result.nav_date,
                daily_change=fast_result.daily_change,
                daily_change_amount=0.0,
            )
        
        # Step 2: Fallback to Playwright
        print(f"   ⚠️  Fast API failed for {fund_code}, trying Playwright fallback...")
        return self._fetch_with_playwright(fund_code)
    
    def _fetch_with_playwright(self, fund_code: str) -> Optional[FundData]:
        """Fetch using Playwright (slow but reliable)"""
        if not self._check_playwright():
            print(f"   ❌ Playwright not available, skipping {fund_code}")
            return None
        
        async def _fetch():
            async with EastMoneyCollector() as collector:
                return await collector.fetch_fund_data(fund_code)
        
        try:
            return asyncio.run(_fetch())
        except Exception as e:
            print(f"   ❌ Playwright fetch failed for {fund_code}: {e}")
            return None
    
    def fetch_funds_batch(self, fund_codes: List[str], max_workers: int = 5) -> List[FundData]:
        """
        Batch fetch with intelligent fallback
        
        Optimizations:
        - Parallel fast API calls for all funds
        - Collect failures
        - Batch fallback to Playwright (if needed)
        """
        print(f"📊 Hybrid Collector: Fetching {len(fund_codes)} funds...")
        
        # Phase 1: Fast parallel fetch for all
        print("   Phase 1: Fast API (parallel)...")
        fast_results = {}
        failed_codes = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_code = {
                executor.submit(fast_fetch, code): code 
                for code in fund_codes
            }
            
            for future in future_to_code:
                code = future_to_code[future]
                try:
                    result = future.result(timeout=10)
                    if result and result.name:
                        fast_results[code] = FundData(
                            code=result.code,
                            name=result.name,
                            nav=result.nav,
                            nav_date=result.nav_date,
                            daily_change=result.daily_change,
                            daily_change_amount=0.0,
                        )
                    else:
                        failed_codes.append(code)
                except Exception as e:
                    print(f"   ⚠️  Fast fetch failed for {code}: {e}")
                    failed_codes.append(code)
        
        success_count = len(fast_results)
        print(f"   ✅ Fast API: {success_count}/{len(fund_codes)} succeeded")
        
        # Phase 2: Playwright fallback for failures
        if failed_codes and self._check_playwright():
            print(f"   Phase 2: Playwright fallback ({len(failed_codes)} funds)...")
            
            async def _fetch_all_fallback():
                async with EastMoneyCollector() as collector:
                    tasks = [
                        collector.fetch_fund_data(code)
                        for code in failed_codes
                    ]
                    return await asyncio.gather(*tasks, return_exceptions=True)
            
            try:
                fallback_results = asyncio.run(_fetch_all_fallback())
                for code, result in zip(failed_codes, fallback_results):
                    if isinstance(result, FundData):
                        fast_results[code] = result
                        print(f"      ✅ Playwright recovered {code}")
                    elif isinstance(result, Exception):
                        print(f"      ❌ Playwright failed for {code}: {result}")
                    else:
                        print(f"      ❌ Playwright no data for {code}")
            except Exception as e:
                print(f"   ❌ Playwright fallback failed: {e}")
        
        final_results = list(fast_results.values())
        print(f"\n📈 Final: {len(final_results)}/{len(fund_codes)} funds retrieved")
        
        return final_results


# Convenience functions
def fetch_fund(fund_code: str) -> Optional[FundData]:
    """Fetch single fund with fallback"""
    collector = HybridCollector()
    return collector.fetch_fund(fund_code)


def fetch_funds(fund_codes: List[str], max_workers: int = 5) -> List[FundData]:
    """Fetch multiple funds with fallback"""
    collector = HybridCollector()
    return collector.fetch_funds_batch(fund_codes, max_workers)


if __name__ == "__main__":
    # Test
    test_codes = ['019455', '000216', '007910', '013402']
    
    print("=" * 60)
    print("Hybrid Collector Test")
    print("=" * 60)
    
    start = time.time()
    results = fetch_funds(test_codes)
    elapsed = time.time() - start
    
    print(f"\n{'=' * 60}")
    print(f"Total time: {elapsed:.2f}s")
    for r in results:
        print(f"  {r.code}: {r.name} ({r.daily_change:+.2f}%)")
