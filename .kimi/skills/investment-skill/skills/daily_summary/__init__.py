"""
Daily Summary Skill - Generate comprehensive daily market summary
"""
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.eastmoney_collector import fetch_funds
from collectors.yahoo_collector import get_yahoo_collector
from collectors.akshare_collector import get_collector as get_ak_collector
from utils.vault_writer import get_vault_writer
from utils.data_cache import get_cache


class DailySummary:
    """Generate daily market summary with global markets and portfolio performance"""
    
    def __init__(self):
        self.yahoo = get_yahoo_collector()
        self.ak = get_ak_collector()
        self.vault = get_vault_writer()
        self.cache = get_cache()
    
    def generate(self, target_date: Optional[datetime] = None) -> Dict:
        """Generate daily summary report
        
        Args:
            target_date: Target date (defaults to today)
            
        Returns:
            Dictionary with summary data
        """
        date = target_date or datetime.now()
        print(f"📰 Generating Daily Summary for {date.strftime('%Y-%m-%d')}...\n")
        
        results = {
            'date': date.strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'global_markets': {},
            'portfolio_summary': {},
            'news_highlights': [],
            'watchlist': [],
            'strategy_notes': '',
        }
        
        # 1. Global Market Overview
        print("🌍 Collecting global market data...")
        results['global_markets'] = self._collect_global_markets()
        
        # 2. Portfolio Summary
        print("💼 Collecting portfolio data...")
        results['portfolio_summary'] = self._collect_portfolio_summary()
        
        # 3. Generate watchlist
        print("📋 Generating watchlist...")
        results['watchlist'] = self._generate_watchlist(results)
        
        # 4. Strategy notes
        print("📝 Generating strategy notes...")
        results['strategy_notes'] = self._generate_strategy_notes(results)
        
        # 5. News highlights (placeholder)
        results['news_highlights'] = self._collect_news_highlights()
        
        # Save report
        self._save_report(results)
        
        return results
    
    def _collect_global_markets(self) -> Dict:
        """Collect global market data"""
        markets = {}
        
        # US Markets
        if self.yahoo:
            # S&P 500
            spx = self.yahoo.get_index_data('SPX')
            if spx:
                markets['sp500'] = {
                    'name': 'S&P 500',
                    'value': spx['close'],
                    'change': spx['change'],
                    'change_pct': spx['change_pct'],
                }
            
            # NASDAQ 100
            ndx = self.yahoo.get_index_data('NDX')
            if ndx:
                markets['nasdaq100'] = {
                    'name': 'NASDAQ 100',
                    'value': ndx['close'],
                    'change': ndx['change'],
                    'change_pct': ndx['change_pct'],
                }
            
            # Semiconductor Index
            sox = self.yahoo.get_index_data('SOX')
            if sox:
                markets['sox'] = {
                    'name': 'Philadelphia Semiconductor',
                    'value': sox['close'],
                    'change': sox['change'],
                    'change_pct': sox['change_pct'],
                }
            
            # VIX
            vix = self.yahoo.get_index_data('VIX')
            if vix:
                markets['vix'] = {
                    'name': 'VIX',
                    'value': vix['close'],
                    'level': self._vix_level(vix['close']),
                }
        
        # Hong Kong
        if self.ak:
            hsi = self.ak.get_hk_index('HSI')
            if hsi:
                markets['hsi'] = {
                    'name': 'Hang Seng Index',
                    'value': hsi['close'],
                    'change_pct': 0,  # Would need previous close
                }
        
        # China A-shares
        if self.ak:
            csi300 = self.ak.get_index_quote('000300')
            if csi300:
                markets['csi300'] = {
                    'name': 'CSI 300',
                    'value': csi300['close'],
                    'change': csi300['change_pct'],
                    'change_pct': csi300['change_pct'],
                }
        
        return markets
    
    def _collect_portfolio_summary(self) -> Dict:
        """Collect portfolio summary"""
        summary = {
            'funds_tracked': 12,
            'funds_with_data': 0,
            'avg_performance': 0,
            'best_performer': None,
            'worst_performer': None,
        }
        
        # Fund codes from portfolio
        fund_codes = [
            '019455', '000216', '018167', '007300', '007910',
            '008887', '501312', '050025', '161125', '016532',
            '017091', '013402'
        ]
        
        # Fetch fund data
        fund_data = fetch_funds(fund_codes[:5])  # Limit for performance
        
        if fund_data:
            summary['funds_with_data'] = len(fund_data)
            
            # Calculate average daily change
            changes = [f.daily_change for f in fund_data if f.daily_change is not None]
            if changes:
                summary['avg_performance'] = sum(changes) / len(changes)
                
                # Best and worst
                best = max(fund_data, key=lambda x: x.daily_change or 0)
                worst = min(fund_data, key=lambda x: x.daily_change or 0)
                
                summary['best_performer'] = {
                    'code': best.code,
                    'name': best.name,
                    'change': best.daily_change,
                }
                summary['worst_performer'] = {
                    'code': worst.code,
                    'name': worst.name,
                    'change': worst.daily_change,
                }
        
        return summary
    
    def _generate_watchlist(self, results: Dict) -> List[Dict]:
        """Generate today's watchlist"""
        watchlist = []
        
        # Always watch semiconductor funds if SOX is volatile
        sox = results['global_markets'].get('sox', {})
        if sox and abs(sox.get('change_pct', 0)) > 2:
            watchlist.append({
                'item': 'Semiconductor Funds',
                'codes': ['019455', '007300', '008887'],
                'reason': f'SOX moved {sox["change_pct"]:+.2f}%',
                'priority': 'high',
            })
        
        # Watch gold if there are macro alerts
        vix = results['global_markets'].get('vix', {})
        if vix and vix.get('value', 0) > 20:
            watchlist.append({
                'item': 'Gold ETF',
                'codes': ['000216'],
                'reason': f'VIX at {vix["value"]:.2f} indicates risk-off environment',
                'priority': 'medium',
            })
        
        # Watch US equity if USD is strong
        # (Would need DXY data from macro collector)
        
        # Watch HK tech if Hang Seng is moving
        hsi = results['global_markets'].get('hsi', {})
        if hsi and abs(hsi.get('change_pct', 0)) > 1.5:
            watchlist.append({
                'item': 'HK Tech',
                'codes': ['013402'],
                'reason': f'HSI moved {hsi["change_pct"]:+.2f}%',
                'priority': 'medium',
            })
        
        return watchlist
    
    def _generate_strategy_notes(self, results: Dict) -> str:
        """Generate strategy notes based on market conditions"""
        notes = []
        
        # Check VIX for market sentiment
        vix = results['global_markets'].get('vix', {})
        if vix:
            vix_value = vix.get('value', 20)
            if vix_value > 25:
                notes.append("⚠️ High volatility (VIX > 25). Consider defensive positioning.")
            elif vix_value < 15:
                notes.append("✅ Low volatility environment favorable for risk assets.")
        
        # Check yield curve (would need from macro data)
        # For now, placeholder
        notes.append("📊 Monitor Fed policy signals and treasury yield movements.")
        
        # Portfolio-specific notes
        portfolio = results['portfolio_summary']
        if portfolio.get('avg_performance', 0) < -2:
            notes.append("📉 Portfolio showing weakness. Review stop-loss levels.")
        elif portfolio.get('avg_performance', 0) > 2:
            notes.append("📈 Strong portfolio performance. Consider profit-taking on winners.")
        
        return "\n".join(notes)
    
    def _collect_news_highlights(self) -> List[str]:
        """Collect news highlights (placeholder)"""
        # In full implementation, this would scrape news sources
        return [
            "Monitor Federal Reserve communications for policy clues",
            "Watch semiconductor earnings reports this week",
            "China policy developments may impact HK tech stocks",
        ]
    
    def _vix_level(self, value: float) -> str:
        """Assess VIX level"""
        if value > 30:
            return "HIGH"
        elif value > 20:
            return "ELEVATED"
        elif value < 15:
            return "LOW"
        return "NORMAL"
    
    def _save_report(self, results: Dict):
        """Save report to vault"""
        content = self._format_report_markdown(results)
        
        # Write to daily notes
        date = datetime.strptime(results['date'], '%Y-%m-%d')
        filepath = self.vault.write_daily_report(content, date, "investment")
        
        print(f"\n💾 Report saved to: {filepath}")
    
    def _format_report_markdown(self, results: Dict) -> str:
        """Format report as markdown"""
        date = results['date']
        
        md = f"""# Investment Daily Summary - {date}

**Generated:** {results['timestamp']}

## Global Market Overview

"""
        
        # US Markets
        md += "### US Markets\n\n"
        for key in ['sp500', 'nasdaq100', 'sox']:
            market = results['global_markets'].get(key)
            if market:
                emoji = "📈" if market.get('change_pct', 0) >= 0 else "📉"
                md += f"- **{market['name']}:** {emoji} {market.get('change_pct', 0):+.2f}%\n"
        md += "\n"
        
        # Asian Markets
        md += "### Asian Markets\n\n"
        for key in ['hsi', 'csi300']:
            market = results['global_markets'].get(key)
            if market:
                emoji = "📈" if market.get('change_pct', 0) >= 0 else "📉"
                md += f"- **{market['name']}:** {emoji} {market.get('change_pct', 0):+.2f}%\n"
        md += "\n"
        
        # VIX
        vix = results['global_markets'].get('vix')
        if vix:
            emoji = "🔴" if vix.get('value', 0) > 25 else "🟡" if vix.get('value', 0) > 20 else "🟢"
            md += f"### Volatility (VIX)\n- **Level:** {emoji} {vix['value']:.2f} ({vix.get('level', 'NORMAL')})\n\n"
        
        # Portfolio Summary
        md += "## Portfolio Summary\n\n"
        portfolio = results['portfolio_summary']
        md += f"- **Funds Tracked:** {portfolio.get('funds_tracked', 0)}\n"
        md += f"- **Average Daily Change:** {portfolio.get('avg_performance', 0):+.2f}%\n"
        
        if portfolio.get('best_performer'):
            best = portfolio['best_performer']
            md += f"- **Best Performer:** {best['name']} ({best['code']}) +{best['change']:.2f}%\n"
        
        if portfolio.get('worst_performer'):
            worst = portfolio['worst_performer']
            md += f"- **Worst Performer:** {worst['name']} ({worst['code']}) {worst['change']:.2f}%\n"
        
        md += "\n"
        
        # Watchlist
        if results['watchlist']:
            md += "## Today's Watchlist\n\n"
            for item in results['watchlist']:
                priority_emoji = "🔴" if item['priority'] == 'high' else "🟡"
                md += f"{priority_emoji} **{item['item']}** ({', '.join(item['codes'])})\n"
                md += f"   - {item['reason']}\n\n"
        
        # News Highlights
        if results['news_highlights']:
            md += "## Key Events & News\n\n"
            for news in results['news_highlights']:
                md += f"- {news}\n"
            md += "\n"
        
        # Strategy Notes
        if results['strategy_notes']:
            md += "## Strategy Notes\n\n"
            md += results['strategy_notes'] + "\n\n"
        
        # Links to related notes
        md += """## Related

- [[knowledge/investment/portfolio/allocation|Portfolio Allocation]]
- [[knowledge/investment/macro/|Macro Analysis]]
- [[knowledge/investment/industries/semiconductor/|Semiconductor Industry]]

---
*Generated by Investment Agent Daily Summary*
"""
        
        return md
    
    def print_report(self, results: Dict):
        """Print report to console"""
        print("\n" + "="*60)
        print("DAILY INVESTMENT SUMMARY")
        print("="*60)
        
        print(f"\n📅 Date: {results['date']}")
        
        # Markets
        print(f"\n🌍 Global Markets:")
        for key, market in results['global_markets'].items():
            if 'change_pct' in market:
                emoji = "📈" if market['change_pct'] >= 0 else "📉"
                print(f"   {emoji} {market['name']}: {market['change_pct']:+.2f}%")
        
        # Portfolio
        portfolio = results['portfolio_summary']
        print(f"\n💼 Portfolio:")
        print(f"   Avg Daily Change: {portfolio.get('avg_performance', 0):+.2f}%")
        
        if portfolio.get('best_performer'):
            print(f"   Best: {portfolio['best_performer']['name']} +{portfolio['best_performer']['change']:.2f}%")
        
        # Watchlist
        if results['watchlist']:
            print(f"\n📋 Watchlist ({len(results['watchlist'])} items)")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate daily investment summary')
    parser.add_argument('--date', type=str, help='Target date (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    summary = DailySummary()
    
    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d')
    
    results = summary.generate(target_date)
    summary.print_report(results)


if __name__ == "__main__":
    main()
