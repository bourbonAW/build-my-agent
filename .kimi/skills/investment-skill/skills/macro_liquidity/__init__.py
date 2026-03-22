"""
Macro Liquidity Skill - Monitor global liquidity conditions
"""
import sys
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.macro_collector import get_macro_collector
from collectors.yahoo_collector import get_yahoo_collector
from utils.vault_writer import get_vault_writer


class MacroLiquidityMonitor:
    """Monitor macro liquidity conditions and their impact on portfolio"""
    
    def __init__(self):
        self.macro = get_macro_collector()
        self.yahoo = get_yahoo_collector()
        self.vault = get_vault_writer()
    
    def analyze(self, alerts_only: bool = False) -> Dict:
        """Run full macro liquidity analysis
        
        Args:
            alerts_only: If True, only return alerts
            
        Returns:
            Dictionary with analysis results
        """
        print("🌍 Macro Liquidity Monitor - Analyzing global conditions...\n")
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'indicators': {},
            'alerts': [],
            'portfolio_impact': {},
        }
        
        # Collect all indicators
        print("📊 Collecting indicators...")
        
        # 1. Federal Reserve Balance Sheet
        print("   - Fed Balance Sheet...")
        results['indicators']['fed_balance_sheet'] = self.macro.get_fed_balance_sheet()
        
        # 2. Treasury Yields
        print("   - Treasury Yields...")
        results['indicators']['treasury_yields'] = self.macro.get_treasury_yields()
        
        # 3. Dollar Index
        print("   - US Dollar Index...")
        results['indicators']['dollar_index'] = self.macro.get_dollar_index()
        
        # 4. SOFR
        print("   - SOFR Rate...")
        results['indicators']['sofr'] = self.macro.get_sofr_rate()
        
        # 5. Gold Price
        print("   - Gold Price...")
        results['indicators']['gold'] = self._get_gold_data()
        
        # 6. Yield Curve
        print("   - Yield Curve...")
        results['indicators']['yield_curve'] = self.macro.get_yield_curve()
        
        # Check for alerts
        print("\n🔍 Checking alert conditions...")
        results['alerts'] = self._check_alerts(results['indicators'])
        
        # Assess portfolio impact
        print("   - Assessing portfolio impact...")
        results['portfolio_impact'] = self._assess_portfolio_impact(results['indicators'])
        
        # Overall assessment
        results['assessment'] = self._overall_assessment(results['indicators'], results['alerts'])
        
        # Save report
        self._save_report(results, alerts_only)
        
        return results
    
    def _get_gold_data(self) -> Optional[Dict]:
        """Get gold price data"""
        if self.yahoo:
            data = self.yahoo.get_commodity_data("GC=F")
            if data:
                return {
                    'price': data.get('close'),
                    'change_pct': data.get('change_pct'),
                    'date': data.get('date'),
                }
        return None
    
    def _check_alerts(self, indicators: Dict) -> List[Dict]:
        """Check for alert conditions"""
        alerts = []
        
        # 1. Fed Balance Sheet contraction
        fed_bs = indicators.get('fed_balance_sheet')
        if fed_bs and fed_bs.get('change_pct', 0) < -5:
            alerts.append({
                'type': 'fed_balance_sheet',
                'severity': 'warning',
                'message': f"Fed balance sheet contracted {fed_bs['change_pct']:.2f}% (>{5}% threshold)",
                'value': fed_bs['change_pct'],
                'threshold': -5.0,
            })
        
        # 2. SOFR spike
        sofr = indicators.get('sofr')
        if sofr and sofr.get('rate', 0) > 5.5:
            alerts.append({
                'type': 'sofr',
                'severity': 'alert',
                'message': f"SOFR rate {sofr['rate']:.2f}% exceeded 5.5% threshold",
                'value': sofr['rate'],
                'threshold': 5.5,
            })
        
        # 3. Dollar strength
        dxy = indicators.get('dollar_index')
        if dxy and dxy.get('value', 100) > 105:
            alerts.append({
                'type': 'dollar_index',
                'severity': 'warning',
                'message': f"Dollar Index {dxy['value']:.2f} indicates strong USD (>105)",
                'value': dxy['value'],
                'threshold': 105.0,
            })
        elif dxy and dxy.get('value', 100) < 100:
            alerts.append({
                'type': 'dollar_index',
                'severity': 'info',
                'message': f"Dollar Index {dxy['value']:.2f} indicates weak USD (<100)",
                'value': dxy['value'],
                'threshold': 100.0,
            })
        
        # 4. Yield curve inversion (2Y > 10Y)
        yields = indicators.get('treasury_yields')
        if yields and '10Y2Y_spread' in yields:
            spread = yields['10Y2Y_spread']
            if spread < 0:
                alerts.append({
                    'type': 'yield_curve',
                    'severity': 'warning',
                    'message': f"Yield curve inverted: 10Y-2Y spread = {spread:.2f}%",
                    'value': spread,
                    'threshold': 0.0,
                })
        
        # 5. Gold price movement (for gold ETF holders)
        gold = indicators.get('gold')
        if gold and abs(gold.get('change_pct', 0)) > 3:
            direction = "surge" if gold['change_pct'] > 0 else "decline"
            alerts.append({
                'type': 'gold',
                'severity': 'info',
                'message': f"Gold price {direction}: {gold['change_pct']:+.2f}%",
                'value': gold['change_pct'],
                'threshold': 3.0 if gold['change_pct'] > 0 else -3.0,
            })
        
        return alerts
    
    def _assess_portfolio_impact(self, indicators: Dict) -> Dict:
        """Assess impact on portfolio categories"""
        impacts = {}
        
        # QDII Funds (US exposure)
        dxy_data = indicators.get('dollar_index')
        dxy = dxy_data.get('value', 100) if dxy_data else 100
        if dxy > 105:
            impacts['us_equity'] = {
                'impact': 'positive',
                'description': f'Strong USD (+{dxy-100:.1f}%) benefits USD-denominated assets',
                'funds_affected': ['050025', '161125', '016532', '017091'],
            }
        elif dxy < 100:
            impacts['us_equity'] = {
                'impact': 'negative',
                'description': f'Weak USD ({dxy-100:.1f}%) reduces returns when converted to CNY',
                'funds_affected': ['050025', '161125', '016532', '017091'],
            }
        
        # Gold Funds
        gold = indicators.get('gold')
        if gold:
            change = gold.get('change_pct', 0)
            impacts['gold'] = {
                'impact': 'positive' if change > 0 else 'negative',
                'description': f'Gold {change:+.2f}% directly impacts gold ETF (000216)',
                'funds_affected': ['000216'],
            }
        
        # Semiconductor (liquidity sensitive)
        fed_bs = indicators.get('fed_balance_sheet')
        if fed_bs and fed_bs.get('change_pct', 0) < -5:
            impacts['semiconductor'] = {
                'impact': 'negative',
                'description': 'Fed balance sheet contraction reduces liquidity, hurting growth stocks',
                'funds_affected': ['019455', '007300', '008887', '501312'],
            }
        
        # Hong Kong (liquidity sensitive)
        if fed_bs and fed_bs.get('change_pct', 0) < -5:
            impacts['hk_tech'] = {
                'impact': 'negative',
                'description': 'Global liquidity tightening particularly affects HK tech',
                'funds_affected': ['013402'],
            }
        
        return impacts
    
    def _overall_assessment(self, indicators: Dict, alerts: List) -> str:
        """Generate overall liquidity assessment"""
        alert_count = len(alerts)
        
        if alert_count == 0:
            return "LIQUIDITY_NEUTRAL"
        
        warning_count = sum(1 for a in alerts if a['severity'] == 'warning')
        alert_count_severe = sum(1 for a in alerts if a['severity'] == 'alert')
        
        if alert_count_severe > 0:
            return "LIQUIDITY_TIGHTENING"
        elif warning_count >= 2:
            return "LIQUIDITY_CAUTION"
        else:
            return "LIQUIDITY_NEUTRAL"
    
    def _save_report(self, results: Dict, alerts_only: bool):
        """Save report to vault"""
        content = self._format_report_markdown(results)
        
        # Write to knowledge base
        date = datetime.now()
        filename = f"liquidity_{date.strftime('%Y-%m')}.md"
        filepath = self.vault.write_knowledge_entry(content, 'macro', filename)
        
        print(f"\n💾 Report saved to: {filepath}")
    
    def _format_report_markdown(self, results: Dict) -> str:
        """Format report as markdown"""
        date = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        assessment_emoji = {
            'LIQUIDITY_TIGHTENING': '🔴',
            'LIQUIDITY_CAUTION': '🟡',
            'LIQUIDITY_NEUTRAL': '🟢',
        }.get(results['assessment'], '⚪')
        
        md = f"""# Macro Liquidity Report - {date}

**Assessment:** {assessment_emoji} {results['assessment'].replace('_', ' ')}
**Alerts:** {len(results['alerts'])}

## Key Indicators

### Federal Reserve Balance Sheet
"""
        
        fed_bs = results['indicators'].get('fed_balance_sheet')
        if fed_bs:
            change_emoji = "📈" if fed_bs.get('change', 0) >= 0 else "📉"
            md += f"""- **Value:** ${fed_bs.get('value', 0):,.0f} Billion
- **Change:** {change_emoji} {fed_bs.get('change_pct', 0):+.2f}%
- **Date:** {fed_bs.get('date', 'N/A')}

"""
        
        # Treasury Yields
        yields = results['indicators'].get('treasury_yields')
        if yields:
            md += "### Treasury Yields\n\n"
            for tenor, data in yields.items():
                if tenor != '10Y2Y_spread':
                    md += f"- **{tenor}:** {data.get('rate', 0):.2f}% (Weekly: {data.get('weekly_change', 0):+.2f}%)\n"
            if '10Y2Y_spread' in yields:
                spread = yields['10Y2Y_spread']
                emoji = "⚠️" if spread < 0 else "✅"
                md += f"- **10Y-2Y Spread:** {emoji} {spread:.2f}%\n"
            md += "\n"
        
        # Dollar Index
        dxy = results['indicators'].get('dollar_index')
        if dxy:
            alert = dxy.get('alert_level', 'NEUTRAL')
            emoji = "🔴" if alert == "STRONG_USD" else "🔵" if alert == "WEAK_USD" else "⚪"
            md += f"""### US Dollar Index (DXY)
- **Value:** {emoji} {dxy.get('value', 0):.2f}
- **Alert Level:** {alert}
- **Date:** {dxy.get('date', 'N/A')}

"""
        
        # SOFR
        sofr = results['indicators'].get('sofr')
        if sofr:
            alert = "⚠️" if sofr.get('alert') else "✅"
            md += f"""### SOFR Rate
- **Rate:** {alert} {sofr.get('rate', 0):.2f}%
- **Date:** {sofr.get('date', 'N/A')}

"""
        
        # Gold
        gold = results['indicators'].get('gold')
        if gold:
            emoji = "📈" if gold.get('change_pct', 0) >= 0 else "📉"
            md += f"""### Gold Price
- **Price:** ${gold.get('price', 0):,.2f}
- **Change:** {emoji} {gold.get('change_pct', 0):+.2f}%

"""
        
        # Alerts
        if results['alerts']:
            md += "## Alerts\n\n"
            for alert in results['alerts']:
                emoji = "🔴" if alert['severity'] == 'alert' else "🟡" if alert['severity'] == 'warning' else "🔵"
                md += f"{emoji} **{alert['type'].replace('_', ' ').title()}**\n"
                md += f"   - {alert['message']}\n"
                md += f"   - Value: {alert['value']:.2f} (Threshold: {alert['threshold']})\n\n"
        
        # Portfolio Impact
        if results['portfolio_impact']:
            md += "## Portfolio Impact\n\n"
            for category, impact in results['portfolio_impact'].items():
                emoji = "📈" if impact['impact'] == 'positive' else "📉"
                md += f"### {category.replace('_', ' ').title()}\n"
                md += f"{emoji} **{impact['impact'].upper()}**\n\n"
                md += f"{impact['description']}\n\n"
                md += f"**Affected Funds:** {', '.join(impact['funds_affected'])}\n\n"
        
        md += """---
*Generated by Investment Agent Macro Liquidity Monitor*
*Data Sources: Federal Reserve, Yahoo Finance*
"""
        
        return md
    
    def print_report(self, results: Dict):
        """Print report to console"""
        print("\n" + "="*60)
        print("MACRO LIQUIDITY REPORT")
        print("="*60)
        
        assessment = results['assessment']
        emoji = {"LIQUIDITY_TIGHTENING": "🔴", "LIQUIDITY_CAUTION": "🟡", "LIQUIDITY_NEUTRAL": "🟢"}.get(assessment, "⚪")
        print(f"\n🌍 Overall Assessment: {emoji} {assessment.replace('_', ' ')}")
        print(f"   Alerts: {len(results['alerts'])}")
        
        if results['alerts']:
            print(f"\n🔔 Alerts:")
            for alert in results['alerts'][:5]:  # Show first 5
                emoji = "🔴" if alert['severity'] == 'alert' else "🟡"
                print(f"   {emoji} {alert['message']}")
        
        # Key metrics
        print(f"\n📊 Key Indicators:")
        fed_bs = results['indicators'].get('fed_balance_sheet')
        if fed_bs:
            print(f"   Fed Balance Sheet: ${fed_bs.get('value', 0):,.0f}B ({fed_bs.get('change_pct', 0):+.2f}%)")
        
        dxy = results['indicators'].get('dollar_index')
        if dxy:
            print(f"   Dollar Index: {dxy.get('value', 0):.2f}")
        
        gold = results['indicators'].get('gold')
        if gold:
            print(f"   Gold: ${gold.get('price', 0):,.2f} ({gold.get('change_pct', 0):+.2f}%)")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Monitor macro liquidity conditions')
    parser.add_argument('--alert', action='store_true', help='Show only alerts')
    
    args = parser.parse_args()
    
    monitor = MacroLiquidityMonitor()
    results = monitor.analyze(alerts_only=args.alert)
    monitor.print_report(results)


if __name__ == "__main__":
    main()
