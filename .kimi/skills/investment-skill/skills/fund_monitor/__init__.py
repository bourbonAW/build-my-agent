"""
Fund Monitor Skill - Monitor portfolio funds and detect anomalies
"""
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
import yaml
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.eastmoney_collector import fetch_funds, FundData
from collectors.akshare_collector import get_collector as get_ak_collector
from utils.vault_writer import get_vault_writer
from utils.data_cache import get_cache


@dataclass
class FundAlert:
    """Fund alert structure"""
    fund_code: str
    fund_name: str
    alert_type: str
    severity: str  # info, warning, alert
    message: str
    value: float
    threshold: float
    timestamp: str


class FundMonitor:
    """Monitor portfolio funds and generate reports"""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize fund monitor
        
        Args:
            config_path: Path to portfolio config. Defaults to config/portfolio.yaml
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "portfolio.yaml"
        
        self.config = self._load_config(config_path)
        self.funds = self.config.get('portfolio', {}).get('funds', [])
        self.alerts_config = self.config.get('alerts', {})
        self.benchmarks = self.config.get('benchmarks', {})
        
        self.cache = get_cache()
        self.vault = get_vault_writer()
    
    def _load_config(self, path: str) -> Dict:
        """Load YAML configuration"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"❌ Error loading config: {e}")
            return {}
    
    def monitor_all(self, alerts_only: bool = False) -> Dict:
        """Monitor all portfolio funds
        
        Args:
            alerts_only: If True, only return funds with alerts
            
        Returns:
            Dictionary with monitoring results
        """
        print("📊 Fund Monitor - Checking portfolio...")
        print(f"   Monitoring {len(self.funds)} funds\n")
        
        # Fetch fund data
        fund_codes = [f['code'] for f in self.funds]
        fund_data_list = fetch_funds(fund_codes)
        
        # Create lookup
        fund_data_map = {f.code: f for f in fund_data_list}
        
        # Analyze each fund
        results = []
        alerts = []
        
        for fund_config in self.funds:
            code = fund_config['code']
            data = fund_data_map.get(code)
            
            if data:
                result = self._analyze_fund(fund_config, data)
                results.append(result)
                
                # Check for alerts
                fund_alerts = self._check_alerts(fund_config, data, result)
                alerts.extend(fund_alerts)
            else:
                print(f"⚠️  Could not fetch data for {code}")
        
        # Generate report
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_funds': len(self.funds),
            'funds_with_data': len(results),
            'funds': results,
            'alerts': alerts,
            'alert_count': len(alerts),
            'summary': self._generate_summary(results),
        }
        
        # Save to vault
        self._save_report(report, alerts_only)
        
        return report
    
    def _analyze_fund(self, config: Dict, data: FundData) -> Dict:
        """Analyze individual fund"""
        result = {
            'code': config['code'],
            'name': data.name or config['name'],
            'category': config.get('category', 'unknown'),
            'region': config.get('region', 'unknown'),
            'nav': data.nav,
            'nav_date': data.nav_date,
            'daily_change': data.daily_change,
            'daily_change_amount': data.daily_change_amount,
            'return_1m': data.return_1m,
            'return_3m': data.return_3m,
            'return_6m': data.return_6m,
            'return_1y': data.return_1y,
            'fund_size': data.fund_size,
            'manager': data.manager,
        }
        
        # Calculate P&L if holdings data available
        shares = config.get('shares')
        cost_basis = config.get('cost_basis')
        
        if shares and cost_basis:
            result['shares'] = shares
            result['cost_basis'] = cost_basis
            result['position_value'] = shares * data.nav
            result['cost_value'] = shares * cost_basis
            result['unrealized_pnl'] = result['position_value'] - result['cost_value']
            result['unrealized_pnl_pct'] = (data.nav / cost_basis - 1) * 100
        
        return result
    
    def _check_alerts(self, config: Dict, data: FundData, result: Dict) -> List[FundAlert]:
        """Check for alert conditions"""
        alerts = []
        now = datetime.now().isoformat()
        
        # Daily decline alert
        threshold = self.alerts_config.get('daily_decline_threshold', -3.0)
        if data.daily_change <= threshold:
            alerts.append(FundAlert(
                fund_code=config['code'],
                fund_name=data.name or config['name'],
                alert_type="daily_decline",
                severity="warning",
                message=f"Daily decline {data.daily_change:.2f}% below threshold {threshold}%",
                value=data.daily_change,
                threshold=threshold,
                timestamp=now,
            ))
        
        # Daily surge alert
        threshold = self.alerts_config.get('daily_surge_threshold', 5.0)
        if data.daily_change >= threshold:
            alerts.append(FundAlert(
                fund_code=config['code'],
                fund_name=data.name or config['name'],
                alert_type="daily_surge",
                severity="info",
                message=f"Daily surge {data.daily_change:.2f}% above threshold {threshold}%",
                value=data.daily_change,
                threshold=threshold,
                timestamp=now,
            ))
        
        # Check consecutive declines (would need historical data)
        # This is a simplified version
        
        return alerts
    
    def _generate_summary(self, results: List[Dict]) -> Dict:
        """Generate portfolio summary"""
        if not results:
            return {}
        
        total_funds = len(results)
        
        # Calculate statistics
        daily_changes = [f['daily_change'] for f in results if f.get('daily_change') is not None]
        
        summary = {
            'avg_daily_change': sum(daily_changes) / len(daily_changes) if daily_changes else 0,
            'max_daily_change': max(daily_changes) if daily_changes else 0,
            'min_daily_change': min(daily_changes) if daily_changes else 0,
            'funds_up': sum(1 for c in daily_changes if c > 0),
            'funds_down': sum(1 for c in daily_changes if c < 0),
            'funds_flat': sum(1 for c in daily_changes if c == 0),
        }
        
        # Calculate portfolio P&L if holdings available
        position_values = [f.get('position_value', 0) for f in results]
        cost_values = [f.get('cost_value', 0) for f in results]
        
        if any(position_values) and any(cost_values):
            summary['total_position_value'] = sum(position_values)
            summary['total_cost_value'] = sum(cost_values)
            summary['total_unrealized_pnl'] = summary['total_position_value'] - summary['total_cost_value']
            summary['total_unrealized_pnl_pct'] = (
                summary['total_position_value'] / summary['total_cost_value'] - 1
            ) * 100 if summary['total_cost_value'] > 0 else 0
        
        return summary
    
    def _save_report(self, report: Dict, alerts_only: bool):
        """Save report to vault"""
        # Generate markdown content
        content = self._format_report_markdown(report)
        
        # Write to vault
        date = datetime.now()
        suffix = "fund_alert" if alerts_only else "fund_report"
        filepath = self.vault.write_daily_report(content, date, suffix)
        
        print(f"\n💾 Report saved to: {filepath}")
    
    def _format_report_markdown(self, report: Dict) -> str:
        """Format report as markdown"""
        date = datetime.now().strftime('%Y-%m-%d')
        
        md = f"""# Fund Portfolio Report - {date}

**Generated:** {report['timestamp']}
**Funds Monitored:** {report['funds_with_data']} / {report['total_funds']}
**Alerts:** {report['alert_count']}

## Summary

"""
        
        summary = report.get('summary', {})
        if summary:
            md += f"""- **Average Daily Change:** {summary.get('avg_daily_change', 0):.2f}%
- **Best Performer:** +{summary.get('max_daily_change', 0):.2f}%
- **Worst Performer:** {summary.get('min_daily_change', 0):.2f}%
- **Up/Down/Flat:** {summary.get('funds_up', 0)} / {summary.get('funds_down', 0)} / {summary.get('funds_flat', 0)}

"""
            
            # Portfolio P&L
            if 'total_unrealized_pnl' in summary:
                pnl = summary['total_unrealized_pnl']
                pnl_pct = summary['total_unrealized_pnl_pct']
                emoji = "📈" if pnl >= 0 else "📉"
                md += f"""### Portfolio P&L
- **Total Position Value:** ¥{summary['total_position_value']:,.2f}
- **Total Cost Basis:** ¥{summary['total_cost_value']:,.2f}
- **Unrealized P&L:** {emoji} ¥{pnl:,.2f} ({pnl_pct:+.2f}%)

"""
        
        # Alerts section
        if report['alerts']:
            md += "## Alerts\n\n"
            for alert in report['alerts']:
                emoji = "🔴" if alert.severity == "alert" else "🟡" if alert.severity == "warning" else "🔵"
                # Clean alert fund name
                alert_name = alert.fund_name.replace('\n', ' ').replace('\r', '').strip()
                alert_name = ' '.join(alert_name.split())  # Normalize whitespace
                md += f"{emoji} **{alert_name}** ({alert.fund_code})\n"
                md += f"   - {alert.message}\n"
                md += f"   - Value: {alert.value:.2f}% (Threshold: {alert.threshold}%)\n\n"
        
        # Fund details
        md += "## Fund Details\n\n"
        md += "| Fund | NAV | Daily Change | 1M | 3M | 6M | 1Y |\n"
        md += "|------|-----|--------------|-----|-----|-----|-----|\n"
        
        for fund in report['funds']:
            change_emoji = "📈" if fund.get('daily_change', 0) >= 0 else "📉"
            # Clean fund name: remove newlines and extra spaces, then truncate
            fund_name = fund.get('name', 'Unknown').replace('\n', ' ').replace('\r', '').strip()
            fund_name = ' '.join(fund_name.split())  # Normalize whitespace
            fund_name = fund_name[:25] + '...' if len(fund_name) > 25 else fund_name
            md += f"| {fund_name} | {fund.get('nav', 'N/A')} | "
            md += f"{change_emoji} {fund.get('daily_change', 0):+.2f}% | "
            md += f"{fund.get('return_1m', 'N/A')} | "
            md += f"{fund.get('return_3m', 'N/A')} | "
            md += f"{fund.get('return_6m', 'N/A')} | "
            md += f"{fund.get('return_1y', 'N/A')} |\n"
        
        md += f"""

---
*Generated by Investment Agent Fund Monitor*
"""
        
        return md
    
    def print_report(self, report: Dict):
        """Print report to console"""
        print("\n" + "="*60)
        print("FUND PORTFOLIO REPORT")
        print("="*60)
        
        summary = report.get('summary', {})
        print(f"\n📊 Summary:")
        print(f"   Funds Monitored: {report['funds_with_data']} / {report['total_funds']}")
        print(f"   Alerts: {report['alert_count']}")
        print(f"   Avg Daily Change: {summary.get('avg_daily_change', 0):+.2f}%")
        
        if 'total_unrealized_pnl' in summary:
            pnl = summary['total_unrealized_pnl']
            pnl_pct = summary['total_unrealized_pnl_pct']
            print(f"   Total P&L: {'📈' if pnl >= 0 else '📉'} ¥{pnl:,.2f} ({pnl_pct:+.2f}%)")
        
        if report['alerts']:
            print(f"\n🔔 Alerts ({len(report['alerts'])}):")
            for alert in report['alerts']:
                emoji = "🔴" if alert.severity == "alert" else "🟡"
                print(f"   {emoji} {alert.fund_code}: {alert.message}")
        
        print("\n💾 Report saved to vault")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Monitor portfolio funds')
    parser.add_argument('--alert', action='store_true', help='Show only alerts')
    parser.add_argument('--code', type=str, help='Monitor specific fund code')
    
    args = parser.parse_args()
    
    monitor = FundMonitor()
    
    if args.code:
        # Monitor specific fund
        print(f"🔍 Monitoring fund: {args.code}")
        # TODO: Implement single fund monitoring
    else:
        # Monitor all
        report = monitor.monitor_all(alerts_only=args.alert)
        monitor.print_report(report)


if __name__ == "__main__":
    main()
