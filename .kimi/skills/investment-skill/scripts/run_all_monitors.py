#!/usr/bin/env python3
"""
Run All Monitors - 一键运行所有监控模块

Usage:
    python scripts/run_all_monitors.py
    python scripts/run_all_monitors.py --quick  # 跳过耗时模块
"""

import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

def run_monitor(module_name, description):
    """运行单个监控模块"""
    print(f"\n{'='*60}")
    print(f"🔄 Running: {description}")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            [sys.executable, f"skills/{module_name}/__init__.py"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )
        
        duration = time.time() - start_time
        
        # 打印输出
        if result.stdout:
            print(result.stdout)
        
        if result.returncode == 0:
            print(f"✅ {description} completed in {duration:.1f}s")
            return True, duration
        else:
            print(f"❌ {description} failed with code {result.returncode}")
            if result.stderr:
                print(f"Error: {result.stderr}")
            return False, duration
            
    except subprocess.TimeoutExpired:
        print(f"⏱️ {description} timed out after 5 minutes")
        return False, 300
    except Exception as e:
        print(f"❌ {description} error: {e}")
        return False, 0

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run all investment monitoring modules')
    parser.add_argument('--quick', action='store_true', 
                       help='Skip time-consuming modules')
    parser.add_argument('--skip-china', action='store_true',
                       help='Skip China market monitor (slow due to AKShare)')
    args = parser.parse_args()
    
    print("🚀 Investment Agent - Running All Monitors")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Quick mode: {args.quick}")
    
    # 定义监控模块
    monitors = [
        ("fund_monitor", "Fund Portfolio Monitor"),
        ("leading_indicator_alerts", "Leading Indicator Alerts"),
        ("macro_liquidity", "Macro Liquidity Monitor"),
        ("semiconductor_tracker", "Semiconductor Industry Tracker"),
        ("daily_summary", "Daily Summary"),
    ]
    
    # 中国监控较慢，可选
    if not args.skip_china:
        monitors.insert(2, ("china_market_monitor", "China A-share/HK Market Monitor"))
    
    results = []
    total_start = time.time()
    
    # 顺序运行所有模块
    for module, description in monitors:
        success, duration = run_monitor(module, description)
        results.append({
            'module': module,
            'description': description,
            'success': success,
            'duration': duration
        })
    
    total_duration = time.time() - total_start
    
    # 汇总报告
    print(f"\n{'='*60}")
    print("📊 SUMMARY REPORT")
    print(f"{'='*60}")
    
    success_count = sum(1 for r in results if r['success'])
    total_count = len(results)
    
    print(f"\nTotal modules: {total_count}")
    print(f"Successful: {success_count} ✅")
    print(f"Failed: {total_count - success_count} ❌")
    print(f"Total time: {total_duration:.1f}s")
    
    print(f"\nModule breakdown:")
    for r in results:
        status = "✅" if r['success'] else "❌"
        print(f"  {status} {r['description']}: {r['duration']:.1f}s")
    
    # 生成综合报告提示
    print(f"\n{'='*60}")
    print("📝 Next Steps:")
    print(f"{'='*60}")
    print("1. Check generated reports in vault-notes/daily/")
    print("2. Review comprehensive report for action items")
    print("3. Check warning levels and adjust positions if needed")
    
    if success_count == total_count:
        print(f"\n✨ All monitors completed successfully!")
        return 0
    else:
        print(f"\n⚠️  Some monitors failed. Check logs above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
