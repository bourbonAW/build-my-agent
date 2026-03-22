"""
Semiconductor Tracker Skill - Track semiconductor industry trends
"""
import sys
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.yahoo_collector import get_yahoo_collector
from collectors.eastmoney_collector import fetch_funds
from utils.vault_writer import get_vault_writer


class SemiconductorTracker:
    """Track semiconductor industry and correlation with portfolio funds"""
    
    def __init__(self):
        self.yahoo = get_yahoo_collector()
        self.vault = get_vault_writer()
        
        # Portfolio semiconductor funds
        self.portfolio_funds = [
            {'code': '019455', 'name': '华泰柏瑞中韩半导体ETF', 'region': 'korea_china'},
            {'code': '007300', 'name': '国联安中证半导体ETF', 'region': 'china'},
            {'code': '008887', 'name': '华夏国证半导体芯片ETF', 'region': 'china'},
        ]
    
    def analyze(self, weekly: bool = False) -> Dict:
        """Run semiconductor industry analysis
        
        Args:
            weekly: If True, generate weekly deep dive
            
        Returns:
            Dictionary with analysis results
        """
        print("🔬 Semiconductor Tracker - Analyzing industry trends...\n")
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'weekly' if weekly else 'daily',
            'sox_index': {},
            'major_chips': {},
            'memory_prices': {},
            'portfolio_correlation': {},
            'trend_analysis': {},
            'alerts': [],
        }
        
        # 1. SOX Index Analysis
        print("📊 Analyzing SOX Index...")
        results['sox_index'] = self._analyze_sox()
        
        # 2. Major Chip Stocks
        print("💻 Analyzing major chip stocks...")
        results['major_chips'] = self._analyze_chip_stocks()
        
        # 3. Memory Prices (placeholder for DRAM/NAND)
        if weekly:
            print("💾 Checking memory prices...")
            results['memory_prices'] = self._check_memory_prices()
        
        # 4. Portfolio Correlation
        print("📈 Analyzing portfolio correlation...")
        results['portfolio_correlation'] = self._analyze_portfolio_correlation()
        
        # 5. Trend Analysis
        print("📉 Trend analysis...")
        results['trend_analysis'] = self._analyze_trends(results)
        
        # 6. Alerts
        results['alerts'] = self._check_alerts(results)
        
        # Save report
        self._save_report(results, weekly)
        
        return results
    
    def _analyze_sox(self) -> Dict:
        """Analyze Philadelphia Semiconductor Index"""
        result = {
            'current': None,
            'trend': 'neutral',
            'support_resistance': {},
        }
        
        if self.yahoo:
            # Current data
            sox = self.yahoo.get_index_data('SOX')
            if sox:
                result['current'] = {
                    'value': sox['close'],
                    'change': sox['change'],
                    'change_pct': sox['change_pct'],
                    'date': sox['date'],
                }
                
                # Determine trend
                if sox['change_pct'] > 2:
                    result['trend'] = 'strong_bullish'
                elif sox['change_pct'] > 0:
                    result['trend'] = 'bullish'
                elif sox['change_pct'] < -2:
                    result['trend'] = 'strong_bearish'
                elif sox['change_pct'] < 0:
                    result['trend'] = 'bearish'
            
            # Historical for support/resistance
            hist = self.yahoo.get_historical_data('SOX', period='3mo')
            if hist is not None and not hist.empty:
                result['support_resistance'] = {
                    'support_20d': hist['Low'].tail(20).min(),
                    'resistance_20d': hist['High'].tail(20).max(),
                    'avg_volume': hist['Volume'].mean(),
                }
        
        return result
    
    def _analyze_chip_stocks(self) -> Dict:
        """Analyze major semiconductor stocks"""
        stocks = {}
        
        if self.yahoo:
            # Get Magnificent 7 tech stocks
            mag7 = self.yahoo.get_magnificent_seven()
            
            # Focus on semiconductor-related
            chip_symbols = ['NVDA', 'AMD', 'AVGO', 'QCOM', 'INTC']
            
            for symbol in chip_symbols:
                if symbol in mag7:
                    data = mag7[symbol]
                    stocks[symbol] = {
                        'price': data.get('price'),
                        'change_pct': data.get('change_pct'),
                        'pe_ratio': data.get('pe_ratio'),
                    }
        
        return stocks
    
    def _check_memory_prices(self) -> Dict:
        """Check memory chip prices (placeholder)"""
        # In full implementation, this would scrape DRAMeXchange or similar
        return {
            'note': 'Memory price data would be collected from DRAMeXchange',
            'trend': 'stable',
            'dram_trend': 'flat',
            'nand_trend': 'flat',
        }
    
    def _analyze_portfolio_correlation(self) -> Dict:
        """Analyze correlation between SOX and portfolio funds"""
        correlation = {
            'funds': {},
            'overall_sentiment': 'neutral',
        }
        
        # Fetch portfolio fund data
        fund_codes = [f['code'] for f in self.portfolio_funds]
        fund_data = fetch_funds(fund_codes)
        
        sox_change = 0
        if self.yahoo:
            sox = self.yahoo.get_index_data('SOX')
            if sox:
                sox_change = sox.get('change_pct', 0)
        
        for fund in fund_data:
            fund_change = fund.daily_change or 0
            
            # Simple correlation check
            correlation_strength = 'high' if abs(fund_change - sox_change) < 1 else 'moderate'
            
            correlation['funds'][fund.code] = {
                'name': fund.name,
                'daily_change': fund_change,
                'sox_change': sox_change,
                'correlation': correlation_strength,
                'direction': 'aligned' if (fund_change > 0) == (sox_change > 0) else 'divergent',
            }
        
        # Overall sentiment
        aligned_count = sum(1 for f in correlation['funds'].values() if f['direction'] == 'aligned')
        if aligned_count >= len(correlation['funds']) * 0.7:
            correlation['overall_sentiment'] = 'highly_correlated'
        elif aligned_count <= len(correlation['funds']) * 0.3:
            correlation['overall_sentiment'] = 'divergent'
        
        return correlation
    
    def _analyze_trends(self, results: Dict) -> Dict:
        """Analyze overall trends"""
        sox = results.get('sox_index', {})
        chips = results.get('major_chips', {})
        
        trends = {
            'momentum': 'neutral',
            'breadth': 'neutral',
            'key_observations': [],
        }
        
        # Check SOX momentum
        sox_current = sox.get('current', {})
        if sox_current:
            change_pct = sox_current.get('change_pct', 0)
            
            if change_pct > 3:
                trends['momentum'] = 'strong_up'
                trends['key_observations'].append(f"SOX surged {change_pct:+.2f}%, strong momentum")
            elif change_pct > 1:
                trends['momentum'] = 'up'
                trends['key_observations'].append(f"SOX up {change_pct:+.2f}%, positive momentum")
            elif change_pct < -3:
                trends['momentum'] = 'strong_down'
                trends['key_observations'].append(f"SOX dropped {change_pct:.2f}%, negative momentum")
            elif change_pct < -1:
                trends['momentum'] = 'down'
                trends['key_observations'].append(f"SOX down {change_pct:.2f}%, weakening momentum")
        
        # Check chip stock breadth
        if chips:
            up_count = sum(1 for s in chips.values() if s.get('change_pct', 0) > 0)
            total = len(chips)
            
            if up_count / total > 0.7:
                trends['breadth'] = 'broadly_positive'
            elif up_count / total < 0.3:
                trends['breadth'] = 'broadly_negative'
        
        return trends
    
    def _check_alerts(self, results: Dict) -> List[Dict]:
        """Check for alerts"""
        alerts = []
        
        # SOX significant move
        sox = results.get('sox_index', {})
        sox_current = sox.get('current', {})
        if sox_current:
            change = sox_current.get('change_pct', 0)
            if abs(change) > 4:
                alerts.append({
                    'type': 'sox_major_move',
                    'severity': 'alert' if abs(change) > 5 else 'warning',
                    'message': f"SOX moved {change:+.2f}% - significant volatility",
                    'value': change,
                })
        
        # Portfolio divergence
        correlation = results.get('portfolio_correlation', {})
        if correlation.get('overall_sentiment') == 'divergent':
            alerts.append({
                'type': 'portfolio_divergence',
                'severity': 'warning',
                'message': 'Portfolio funds diverging from SOX trend - investigate',
            })
        
        # Trend change
        trends = results.get('trend_analysis', {})
        momentum = trends.get('momentum', '')
        if 'strong' in momentum:
            direction = 'uptrend' if 'up' in momentum else 'downtrend'
            alerts.append({
                'type': 'trend_acceleration',
                'severity': 'info',
                'message': f'Semiconductor sector entering strong {direction}',
            })
        
        return alerts
    
    def _save_report(self, results: Dict, weekly: bool):
        """Save report to vault"""
        content = self._format_report_markdown(results, weekly)
        
        # Write to knowledge base
        date = datetime.now()
        if weekly:
            filename = f"weekly_analysis_{date.strftime('%Y-W%W')}.md"
        else:
            filename = f"daily_analysis_{date.strftime('%Y-%m-%d')}.md"
        
        filepath = self.vault.write_knowledge_entry(
            content, 
            'industries/semiconductor', 
            filename
        )
        
        print(f"\n💾 Report saved to: {filepath}")
    
    def _format_report_markdown(self, results: Dict, weekly: bool) -> str:
        """Format report as markdown"""
        date = datetime.now().strftime('%Y-%m-%d')
        analysis_type = "Weekly Deep Dive" if weekly else "Daily Analysis"
        
        md = f"""# Semiconductor Industry {analysis_type} - {date}

**Analysis Type:** {analysis_type}
**Generated:** {results['timestamp']}

## SOX Index Analysis

"""
        
        sox = results['sox_index']
        sox_current = sox.get('current', {})
        if sox_current:
            emoji = "📈" if sox_current.get('change_pct', 0) >= 0 else "📉"
            md += f"""### Current Status
- **Value:** {sox_current.get('value', 'N/A')}
- **Daily Change:** {emoji} {sox_current.get('change_pct', 0):+.2f}%
- **Trend:** {sox.get('trend', 'neutral').replace('_', ' ').title()}
- **Date:** {sox_current.get('date', 'N/A')}

"""
            
            sr = sox.get('support_resistance', {})
            if sr:
                md += f"""### Key Levels
- **20-Day Support:** {sr.get('support_20d', 'N/A')}
- **20-Day Resistance:** {sr.get('resistance_20d', 'N/A')}

"""
        
        # Major Chip Stocks
        if results['major_chips']:
            md += "## Major Chip Stocks\n\n"
            md += "| Stock | Price | Change | P/E |\n"
            md += "|-------|-------|--------|-----|\n"
            
            for symbol, data in results['major_chips'].items():
                emoji = "📈" if data.get('change_pct', 0) >= 0 else "📉"
                md += f"| {symbol} | ${data.get('price', 'N/A')} | {emoji} {data.get('change_pct', 0):+.2f}% | {data.get('pe_ratio', 'N/A')} |\n"
            
            md += "\n"
        
        # Portfolio Correlation
        correlation = results['portfolio_correlation']
        if correlation.get('funds'):
            md += "## Portfolio Correlation\n\n"
            md += f"**Overall Sentiment:** {correlation.get('overall_sentiment', 'neutral').replace('_', ' ').title()}\n\n"
            
            md += "| Fund | Daily Change | SOX Change | Correlation | Direction |\n"
            md += "|------|--------------|------------|-------------|-----------|\n"
            
            for code, fund_corr in correlation['funds'].items():
                emoji = "✅" if fund_corr.get('direction') == 'aligned' else "⚠️"
                md += f"| {fund_corr.get('name', code)[:20]}... | {fund_corr.get('daily_change', 0):+.2f}% | "
                md += f"{fund_corr.get('sox_change', 0):+.2f}% | "
                md += f"{fund_corr.get('correlation', 'unknown')} | {emoji} {fund_corr.get('direction', 'unknown')} |\n"
            
            md += "\n"
        
        # Trend Analysis
        trends = results['trend_analysis']
        if trends.get('key_observations'):
            md += "## Trend Analysis\n\n"
            md += f"**Momentum:** {trends.get('momentum', 'neutral').replace('_', ' ').title()}\n\n"
            md += f"**Breadth:** {trends.get('breadth', 'neutral').replace('_', ' ').title()}\n\n"
            md += "### Key Observations\n\n"
            for obs in trends['key_observations']:
                md += f"- {obs}\n"
            md += "\n"
        
        # Alerts
        if results['alerts']:
            md += "## Alerts\n\n"
            for alert in results['alerts']:
                emoji = "🔴" if alert['severity'] == 'alert' else "🟡" if alert['severity'] == 'warning' else "🔵"
                md += f"{emoji} **{alert['type'].replace('_', ' ').title()}**\n"
                md += f"   - {alert['message']}\n\n"
        
        # Memory Prices (if weekly)
        if weekly and results.get('memory_prices'):
            md += "## Memory Market\n\n"
            md += f"- **DRAM Trend:** {results['memory_prices'].get('dram_trend', 'stable')}\n"
            md += f"- **NAND Trend:** {results['memory_prices'].get('nand_trend', 'stable')}\n\n"
        
        # Related portfolio funds
        md += """## Related Portfolio Funds

- [[华泰柏瑞中韩半导体ETF|019455]] - Korea/China semiconductor exposure
- [[国联安中证半导体ETF|007300]] - China A-share semiconductor
- [[华夏国证半导体芯片ETF|008887]] - China chip index

---
*Generated by Investment Agent Semiconductor Tracker*
*Data Sources: Yahoo Finance, EastMoney*
"""
        
        return md
    
    def print_report(self, results: Dict):
        """Print report to console"""
        print("\n" + "="*60)
        print("SEMICONDUCTOR INDUSTRY ANALYSIS")
        print("="*60)
        
        # SOX
        sox = results.get('sox_index', {}).get('current', {})
        if sox:
            emoji = "📈" if sox.get('change_pct', 0) >= 0 else "📉"
            print(f"\n🔬 SOX Index: {emoji} {sox.get('change_pct', 0):+.2f}%")
            print(f"   Value: {sox.get('value', 'N/A')}")
        
        # Alerts
        if results['alerts']:
            print(f"\n🔔 Alerts ({len(results['alerts'])}):")
            for alert in results['alerts'][:3]:
                emoji = "🔴" if alert['severity'] == 'alert' else "🟡"
                print(f"   {emoji} {alert['message']}")
        
        # Correlation
        corr = results.get('portfolio_correlation', {})
        print(f"\n📈 Portfolio Correlation: {corr.get('overall_sentiment', 'neutral').replace('_', ' ')}")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Track semiconductor industry')
    parser.add_argument('--weekly', action='store_true', help='Generate weekly deep dive')
    
    args = parser.parse_args()
    
    tracker = SemiconductorTracker()
    results = tracker.analyze(weekly=args.weekly)
    tracker.print_report(results)


if __name__ == "__main__":
    main()
