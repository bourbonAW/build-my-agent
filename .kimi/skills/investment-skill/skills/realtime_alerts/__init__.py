"""
Realtime Alerts Skill - Continuous monitoring and instant alerting
实时监控预警系统 - 持续监控并在触发条件时立即通知
"""
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from skills.fund_monitor import FundMonitor
from skills.macro_liquidity import MacroLiquidityMonitor
from collectors.eastmoney_collector import fetch_funds
from collectors.yahoo_collector import get_yahoo_collector
from utils.vault_writer import get_vault_writer


@dataclass
class AlertNotification:
    """Alert notification structure"""
    timestamp: str
    alert_type: str  # fund, macro, market
    severity: str    # info, warning, alert, critical
    title: str
    message: str
    data: Dict
    
    def to_console(self) -> str:
        """Format for console output"""
        emoji_map = {
            'info': '🔵',
            'warning': '🟡', 
            'alert': '🔴',
            'critical': '🚨'
        }
        emoji = emoji_map.get(self.severity, '⚪')
        return f"{emoji} [{self.alert_type.upper()}] {self.title}\n   {self.message}\n   Time: {self.timestamp}"
    
    def to_markdown(self) -> str:
        """Format for markdown"""
        emoji_map = {
            'info': '🔵',
            'warning': '🟡',
            'alert': '🔴', 
            'critical': '🚨'
        }
        emoji = emoji_map.get(self.severity, '⚪')
        return f"""### {emoji} {self.title}

**Type:** {self.alert_type}  
**Severity:** {self.severity}  
**Time:** {self.timestamp}

{self.message}

---
"""


class RealtimeAlertSystem:
    """
    Real-time alert monitoring system
    
    Features:
    - Continuous monitoring mode (daemon)
    - One-time check mode
    - Multiple alert channels (console, file, vault)
    - Configurable check intervals
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize real-time alert system"""
        self.fund_monitor = FundMonitor(config_path)
        self.macro_monitor = MacroLiquidityMonitor()
        self.vault = get_vault_writer()
        self.yahoo = get_yahoo_collector()
        
        # Alert history
        self.alert_history: List[AlertNotification] = []
        self.last_check_time: Optional[datetime] = None
        
        # Alert deduplication (prevent spam)
        self.recent_alerts: Dict[str, datetime] = {}
        self.deduplication_window = timedelta(minutes=30)
    
    def check_now(self, alert_types: List[str] = ['fund', 'macro']) -> List[AlertNotification]:
        """
        Perform immediate alert check (one-time)
        
        Args:
            alert_types: Types of alerts to check ['fund', 'macro', 'market']
            
        Returns:
            List of triggered alerts
        """
        alerts = []
        self.last_check_time = datetime.now()
        
        print(f"\n🔍 Checking for alerts at {self.last_check_time.strftime('%H:%M:%S')}...")
        
        # 1. Fund Alerts
        if 'fund' in alert_types:
            print("  📊 Checking portfolio funds...")
            fund_alerts = self._check_fund_alerts()
            alerts.extend(fund_alerts)
        
        # 2. Macro Alerts  
        if 'macro' in alert_types:
            print("  🌍 Checking macro conditions...")
            macro_alerts = self._check_macro_alerts()
            alerts.extend(macro_alerts)
        
        # 3. Market Alerts (VIX, major indices)
        if 'market' in alert_types:
            print("  📈 Checking market indicators...")
            market_alerts = self._check_market_alerts()
            alerts.extend(market_alerts)
        
        # Process and deduplicate alerts
        new_alerts = self._process_alerts(alerts)
        
        if new_alerts:
            print(f"\n🚨 {len(new_alerts)} new alert(s) triggered!")
            for alert in new_alerts:
                print(f"\n{alert.to_console()}")
            
            # Save to vault
            self._save_alerts(new_alerts)
        else:
            print("\n✅ No new alerts")
        
        return new_alerts
    
    def monitor_continuously(self, 
                            interval: int = 300,  # 5 minutes default
                            alert_types: List[str] = ['fund', 'macro'],
                            on_alert: Optional[Callable] = None):
        """
        Run continuous monitoring (daemon mode)
        
        Args:
            interval: Check interval in seconds
            alert_types: Types of alerts to monitor
            on_alert: Callback function when alert is triggered
        """
        print(f"\n🔄 Starting continuous monitoring...")
        print(f"   Check interval: {interval} seconds ({interval/60:.1f} minutes)")
        print(f"   Alert types: {', '.join(alert_types)}")
        print(f"   Press Ctrl+C to stop\n")
        
        try:
            while True:
                alerts = self.check_now(alert_types)
                
                # Execute callback if provided
                if on_alert and alerts:
                    on_alert(alerts)
                
                # Sleep until next check
                next_check = datetime.now() + timedelta(seconds=interval)
                print(f"\n💤 Next check at {next_check.strftime('%H:%M:%S')}")
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 Monitoring stopped by user")
            self._print_summary()
    
    def _clean_fund_name(self, name: str) -> str:
        """Clean fund name by removing HTML artifacts and extra whitespace"""
        if not name:
            return "Unknown"
        # Remove HTML artifacts
        name = name.replace('\n', ' ').replace('\r', '').strip()
        name = name.replace('查看相关ETF>', '').strip()
        # Normalize whitespace
        name = ' '.join(name.split())
        return name
    
    def _check_fund_alerts(self) -> List[AlertNotification]:
        """Check for fund-specific alerts"""
        alerts = []
        
        # Get fund data
        fund_codes = [f['code'] for f in self.fund_monitor.funds]
        fund_data = fetch_funds(fund_codes[:5])  # Limit for performance
        
        for fund_config in self.fund_monitor.funds:
            code = fund_config['code']
            data = next((f for f in fund_data if f.code == code), None)
            
            if not data:
                continue
            
            # Clean fund name
            fund_name = self._clean_fund_name(data.name or fund_config.get('name', code))
            
            # Check daily decline
            threshold = self.fund_monitor.alerts_config.get('daily_decline_threshold', -3.0)
            if data.daily_change <= threshold:
                alerts.append(AlertNotification(
                    timestamp=datetime.now().isoformat(),
                    alert_type='fund',
                    severity='warning',
                    title=f'{fund_name} ({code}) - Significant Decline',
                    message=f'Daily decline of {data.daily_change:.2f}% exceeds threshold of {threshold}%',
                    data={
                        'fund_code': code,
                        'fund_name': fund_name,
                        'nav': data.nav,
                        'daily_change': data.daily_change,
                        'threshold': threshold
                    }
                ))
            
            # Check daily surge
            surge_threshold = self.fund_monitor.alerts_config.get('daily_surge_threshold', 5.0)
            if data.daily_change >= surge_threshold:
                alerts.append(AlertNotification(
                    timestamp=datetime.now().isoformat(),
                    alert_type='fund',
                    severity='info',
                    title=f'{fund_name} ({code}) - Strong Rally',
                    message=f'Daily surge of {data.daily_change:.2f}% exceeds threshold of {surge_threshold}%',
                    data={
                        'fund_code': code,
                        'fund_name': fund_name,
                        'nav': data.nav,
                        'daily_change': data.daily_change,
                        'threshold': surge_threshold
                    }
                ))
            
            # Check portfolio P&L if holdings exist
            shares = fund_config.get('shares')
            cost_basis = fund_config.get('cost_basis')
            if shares and cost_basis:
                pnl_pct = (data.nav / cost_basis - 1) * 100
                
                # Alert if significant loss from cost basis
                if pnl_pct <= -10:
                    alerts.append(AlertNotification(
                        timestamp=datetime.now().isoformat(),
                        alert_type='fund',
                        severity='alert',
                        title=f'{data.name} ({code}) - Portfolio Loss Alert',
                        message=f'Unrealized loss of {pnl_pct:.2f}% from cost basis ¥{cost_basis}',
                        data={
                            'fund_code': code,
                            'fund_name': data.name,
                            'cost_basis': cost_basis,
                            'current_nav': data.nav,
                            'pnl_pct': pnl_pct
                        }
                    ))
        
        return alerts
    
    def _check_macro_alerts(self) -> List[AlertNotification]:
        """Check for macro-level alerts"""
        alerts = []
        
        if not self.yahoo:
            return alerts
        
        # Check VIX
        vix_data = self.yahoo.get_index_data('VIX')
        if vix_data:
            vix_value = vix_data.get('close', 0)
            
            if vix_value > 25:
                alerts.append(AlertNotification(
                    timestamp=datetime.now().isoformat(),
                    alert_type='macro',
                    severity='warning',
                    title='High Volatility Alert (VIX)',
                    message=f'VIX at {vix_value:.2f}, indicating elevated market volatility',
                    data={'vix': vix_value, 'level': 'high'}
                ))
            elif vix_value > 30:
                alerts.append(AlertNotification(
                    timestamp=datetime.now().isoformat(),
                    alert_type='macro',
                    severity='alert',
                    title='Extreme Volatility Alert (VIX)',
                    message=f'VIX at {vix_value:.2f}, indicating extreme fear in markets',
                    data={'vix': vix_value, 'level': 'extreme'}
                ))
        
        # Check major indices
        spx = self.yahoo.get_index_data('SPX')
        if spx and abs(spx.get('change_pct', 0)) > 2:
            change = spx['change_pct']
            alerts.append(AlertNotification(
                timestamp=datetime.now().isoformat(),
                alert_type='macro',
                severity='warning' if abs(change) > 3 else 'info',
                title=f'S&P 500 Significant Move ({change:+.2f}%)',
                message=f'S&P 500 moved {change:+.2f}%, affecting US equity exposure',
                data={'index': 'SPX', 'change_pct': change}
            ))
        
        return alerts
    
    def _check_market_alerts(self) -> List[AlertNotification]:
        """Check general market alerts"""
        alerts = []
        
        # Check SOX (semiconductor index)
        if self.yahoo:
            sox = self.yahoo.get_index_data('SOX')
            if sox and abs(sox.get('change_pct', 0)) > 3:
                change = sox['change_pct']
                alerts.append(AlertNotification(
                    timestamp=datetime.now().isoformat(),
                    alert_type='market',
                    severity='warning',
                    title=f'Semiconductor Index (SOX) Alert ({change:+.2f}%)',
                    message=f'Philadelphia Semiconductor Index moved {change:+.2f}%, impacting chip holdings',
                    data={'symbol': 'SOX', 'change_pct': change}
                ))
        
        return alerts
    
    def _process_alerts(self, alerts: List[AlertNotification]) -> List[AlertNotification]:
        """Process and deduplicate alerts"""
        new_alerts = []
        now = datetime.now()
        
        for alert in alerts:
            # Create unique key for alert
            alert_key = f"{alert.alert_type}:{alert.title}"
            
            # Check if this alert was recently triggered
            last_triggered = self.recent_alerts.get(alert_key)
            if last_triggered and (now - last_triggered) < self.deduplication_window:
                # Skip duplicate alert
                continue
            
            # New alert
            self.recent_alerts[alert_key] = now
            new_alerts.append(alert)
            self.alert_history.append(alert)
        
        # Cleanup old alerts from dedup cache
        cutoff = now - self.deduplication_window
        self.recent_alerts = {
            k: v for k, v in self.recent_alerts.items() 
            if v > cutoff
        }
        
        return new_alerts
    
    def _save_alerts(self, alerts: List[AlertNotification]):
        """Save alerts to vault"""
        date = datetime.now()
        
        # Create alerts summary
        content = f"""---
date: {date.strftime('%Y-%m-%d')}
category: alert
generated_by: Realtime Alert System
---

# Real-time Alerts - {date.strftime('%Y-%m-%d %H:%M')}

## New Alerts ({len(alerts)})

"""
        
        for alert in alerts:
            content += alert.to_markdown()
        
        # Append to daily alert file
        filename = f"{date.strftime('%Y-%m-%d')}_alerts.md"
        filepath = self.vault.daily_path / filename
        
        if filepath.exists():
            with open(filepath, 'a', encoding='utf-8') as f:
                for alert in alerts:
                    f.write(alert.to_markdown())
        else:
            filepath.write_text(content, encoding='utf-8')
        
        print(f"   💾 Alerts saved to: {filepath}")
    
    def _print_summary(self):
        """Print monitoring summary"""
        if not self.alert_history:
            print("\n📊 No alerts during monitoring period")
            return
        
        print(f"\n📊 Monitoring Summary:")
        print(f"   Total alerts: {len(self.alert_history)}")
        print(f"   Fund alerts: {sum(1 for a in self.alert_history if a.alert_type == 'fund')}")
        print(f"   Macro alerts: {sum(1 for a in self.alert_history if a.alert_type == 'macro')}")
        print(f"   Market alerts: {sum(1 for a in self.alert_history if a.alert_type == 'market')}")


def main():
    """Main entry point for CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Real-time Investment Alert System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # One-time check (default)
  %(prog)s --monitor          # Continuous monitoring
  %(prog)s --interval 600     # Check every 10 minutes
  %(prog)s --type fund,macro  # Check only fund and macro alerts
        """
    )
    
    parser.add_argument(
        '--monitor', '-m',
        action='store_true',
        help='Enable continuous monitoring mode'
    )
    
    parser.add_argument(
        '--interval', '-i',
        type=int,
        default=300,
        help='Check interval in seconds (default: 300 = 5 minutes)'
    )
    
    parser.add_argument(
        '--type', '-t',
        type=str,
        default='fund,macro,market',
        help='Comma-separated alert types to check (default: fund,macro,market)'
    )
    
    args = parser.parse_args()
    
    # Parse alert types
    alert_types = [t.strip() for t in args.type.split(',')]
    
    # Initialize alert system
    alert_system = RealtimeAlertSystem()
    
    if args.monitor:
        # Continuous monitoring mode
        alert_system.monitor_continuously(
            interval=args.interval,
            alert_types=alert_types
        )
    else:
        # One-time check
        alerts = alert_system.check_now(alert_types)
        
        if not alerts:
            print("\n✅ No alerts at this time")
        else:
            print(f"\n{'='*60}")
            print(f"ALERT CHECK COMPLETE - {len(alerts)} alert(s) found")
            print(f"{'='*60}")


if __name__ == "__main__":
    main()
