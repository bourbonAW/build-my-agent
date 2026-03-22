#!/usr/bin/env python3
"""
Investment Agent - Main entry point
Orchestrates all investment analysis skills
"""
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Add skill directory to path
sys.path.insert(0, str(Path(__file__).parent))

from skills.fund_monitor import FundMonitor
from skills.macro_liquidity import MacroLiquidityMonitor
from skills.daily_summary import DailySummary
from skills.semiconductor_tracker import SemiconductorTracker


def run_fund_monitor(alerts_only: bool = False):
    """Run fund monitoring"""
    print("\n" + "="*70)
    print("🔍 FUND MONITOR")
    print("="*70)
    
    monitor = FundMonitor()
    report = monitor.monitor_all(alerts_only=alerts_only)
    monitor.print_report(report)
    
    return report


def run_macro_liquidity(alerts_only: bool = False):
    """Run macro liquidity analysis"""
    print("\n" + "="*70)
    print("🌍 MACRO LIQUIDITY MONITOR")
    print("="*70)
    
    monitor = MacroLiquidityMonitor()
    results = monitor.analyze(alerts_only=alerts_only)
    monitor.print_report(results)
    
    return results


def run_daily_summary():
    """Run daily summary generation"""
    print("\n" + "="*70)
    print("📰 DAILY SUMMARY")
    print("="*70)
    
    summary = DailySummary()
    results = summary.generate()
    summary.print_report(results)
    
    return results


def run_semiconductor_tracker(weekly: bool = False):
    """Run semiconductor tracking"""
    print("\n" + "="*70)
    print("🔬 SEMICONDUCTOR TRACKER")
    print("="*70)
    
    tracker = SemiconductorTracker()
    results = tracker.analyze(weekly=weekly)
    tracker.print_report(results)
    
    return results


def run_all(quick: bool = False):
    """Run all skills in sequence"""
    print("\n" + "🚀" * 35)
    print("  INVESTMENT AGENT - COMPLETE DAILY ANALYSIS")
    print("🚀" * 35)
    
    start_time = datetime.now()
    
    # Always run fund monitor
    fund_report = run_fund_monitor(alerts_only=False)
    
    # Run macro liquidity
    macro_report = run_macro_liquidity(alerts_only=False)
    
    # Run daily summary (includes all data)
    if not quick:
        daily_report = run_daily_summary()
    
    # Run semiconductor tracker periodically (not every day)
    if not quick:
        semi_report = run_semiconductor_tracker(weekly=False)
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print("\n" + "="*70)
    print("✅ ANALYSIS COMPLETE")
    print("="*70)
    print(f"\n⏱️  Total duration: {duration:.1f} seconds")
    print("📁 Reports saved to vault-notes/daily/ and vault-notes/knowledge/investment/")
    print("\n💡 Next steps:")
    print("   - Review daily reports in Obsidian")
    print("   - Check alerts in fund_monitor reports")
    print("   - Follow up on watchlist items")
    
    return {
        'fund_report': fund_report,
        'macro_report': macro_report,
        'duration': duration,
    }


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Investment Agent - Automated investment analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                        # Run all skills
  %(prog)s --quick                # Quick mode (skip daily summary)
  %(prog)s fund-monitor           # Monitor portfolio funds
  %(prog)s fund-monitor --alert   # Show only alerts
  %(prog)s macro-liquidity        # Check macro conditions
  %(prog)s daily-summary          # Generate daily report
  %(prog)s semi-tracker           # Track semiconductor industry
  %(prog)s semi-tracker --weekly  # Weekly deep dive

For more information, see SKILL.md
        """
    )
    
    parser.add_argument(
        'command',
        nargs='?',
        choices=['fund-monitor', 'macro-liquidity', 'daily-summary', 'semi-tracker', 'all'],
        default='all',
        help='Command to run (default: all)'
    )
    
    parser.add_argument(
        '--alert', '-a',
        action='store_true',
        help='Show only alerts (for fund-monitor and macro-liquidity)'
    )
    
    parser.add_argument(
        '--weekly', '-w',
        action='store_true',
        help='Generate weekly analysis (for semi-tracker)'
    )
    
    parser.add_argument(
        '--quick', '-q',
        action='store_true',
        help='Quick mode - skip detailed analysis'
    )
    
    parser.add_argument(
        '--version', '-v',
        action='version',
        version='%(prog)s 1.0.0'
    )
    
    args = parser.parse_args()
    
    try:
        if args.command == 'fund-monitor':
            run_fund_monitor(alerts_only=args.alert)
        
        elif args.command == 'macro-liquidity':
            run_macro_liquidity(alerts_only=args.alert)
        
        elif args.command == 'daily-summary':
            run_daily_summary()
        
        elif args.command == 'semi-tracker':
            run_semiconductor_tracker(weekly=args.weekly)
        
        else:  # 'all' or default
            run_all(quick=args.quick)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
