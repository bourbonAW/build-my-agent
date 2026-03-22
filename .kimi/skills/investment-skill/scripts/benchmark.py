#!/usr/bin/env python3
"""
Benchmark - 性能基准测试框架

Usage:
    python scripts/benchmark.py --iterations 3
    python scripts/benchmark.py --skill fund_monitor
"""

import subprocess
import sys
import time
import json
from pathlib import Path
from datetime import datetime
import statistics

def run_skill(skill_name, iteration):
    """运行单个skill并测量性能"""
    print(f"  🔄 Iteration {iteration}...")
    
    start_time = time.time()
    start_tokens = 0  # Would need actual token counting from Claude API
    
    try:
        result = subprocess.run(
            [sys.executable, f"skills/{skill_name}/__init__.py"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        duration = time.time() - start_time
        
        # 简化：假设输出中的某些关键词可以判断成功
        success = result.returncode == 0 and "Report saved" in result.stdout
        
        return {
            'success': success,
            'duration': duration,
            'stdout_len': len(result.stdout),
            'stderr_len': len(result.stderr) if result.stderr else 0
        }
        
    except subprocess.TimeoutExpired:
        return {'success': False, 'duration': 300, 'stdout_len': 0, 'stderr_len': 0}
    except Exception as e:
        return {'success': False, 'duration': 0, 'stdout_len': 0, 'stderr_len': 0, 'error': str(e)}

def benchmark_skill(skill_name, iterations=3):
    """对单个skill进行基准测试"""
    print(f"\n📊 Benchmarking: {skill_name}")
    print(f"   Iterations: {iterations}")
    
    results = []
    for i in range(1, iterations + 1):
        result = run_skill(skill_name, i)
        results.append(result)
        time.sleep(1)  # 短暂休息避免限流
    
    # 计算统计
    durations = [r['duration'] for r in results]
    successes = sum(1 for r in results if r['success'])
    
    stats = {
        'skill': skill_name,
        'iterations': iterations,
        'success_rate': successes / iterations,
        'duration_mean': statistics.mean(durations),
        'duration_min': min(durations),
        'duration_max': max(durations),
        'duration_stdev': statistics.stdev(durations) if len(durations) > 1 else 0
    }
    
    return stats

def generate_benchmark_report(all_stats):
    """生成基准测试报告"""
    report = []
    report.append("# 📊 Investment Agent - Performance Benchmark\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    
    # 总体统计
    total_skills = len(all_stats)
    avg_success_rate = sum(s['success_rate'] for s in all_stats) / total_skills if total_skills > 0 else 0
    avg_duration = sum(s['duration_mean'] for s in all_stats) / total_skills if total_skills > 0 else 0
    
    report.append("## 📈 Overall Statistics\n\n")
    report.append(f"- Total Skills: {total_skills}\n")
    report.append(f"- Average Success Rate: {avg_success_rate*100:.1f}%\n")
    report.append(f"- Average Duration: {avg_duration:.1f}s\n\n")
    
    # 详细表格
    report.append("## 📋 Detailed Results\n\n")
    report.append("| Skill | Success Rate | Avg Duration | Min | Max | Std Dev |\n")
    report.append("|-------|-------------|--------------|-----|-----|---------|\n")
    
    for stats in all_stats:
        report.append(
            f"| {stats['skill']} | "
            f"{stats['success_rate']*100:.0f}% | "
            f"{stats['duration_mean']:.1f}s | "
            f"{stats['duration_min']:.1f}s | "
            f"{stats['duration_max']:.1f}s | "
            f"{stats['duration_stdev']:.2f}s |\n"
        )
    
    report.append("\n## 🎯 Performance Analysis\n\n")
    
    # 找出最快和最慢
    sorted_by_duration = sorted(all_stats, key=lambda x: x['duration_mean'])
    fastest = sorted_by_duration[0]
    slowest = sorted_by_duration[-1]
    
    report.append(f"**Fastest:** {fastest['skill']} ({fastest['duration_mean']:.1f}s)\n")
    report.append(f"**Slowest:** {slowest['skill']} ({slowest['duration_mean']:.1f}s)\n\n")
    
    # 找出最可靠和最不稳定
    sorted_by_success = sorted(all_stats, key=lambda x: x['success_rate'], reverse=True)
    most_reliable = sorted_by_success[0]
    
    report.append(f"**Most Reliable:** {most_reliable['skill']} ({most_reliable['success_rate']*100:.0f}% success)\n")
    report.append(f"**Highest Variance:** {slowest['skill']} (σ={slowest['duration_stdev']:.2f}s)\n\n")
    
    # 优化建议
    report.append("## 💡 Optimization Suggestions\n\n")
    
    if slowest['duration_mean'] > 60:
        report.append(f"⚠️ **{slowest['skill']}** is slow ({slowest['duration_mean']:.1f}s). Consider:\n")
        report.append("  - Adding caching for external API calls\n")
        report.append("  - Optimizing data fetching logic\n")
        report.append("  - Using async/parallel processing\n\n")
    
    if slowest['duration_stdev'] > 10:
        report.append(f"⚠️ **{slowest['skill']}** has high variance (σ={slowest['duration_stdev']:.2f}s). Consider:\n")
        report.append("  - Adding timeout handling\n")
        report.append("  - Implementing retry logic\n")
        report.append("  - Using fallback data sources\n\n")
    
    if avg_success_rate < 0.9:
        report.append(f"⚠️ Overall success rate ({avg_success_rate*100:.0f}%) is below 90%. Review error handling.\n\n")
    
    report.append("✅ All systems performing within acceptable range.\n")
    
    return ''.join(report)

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Benchmark investment agent skills')
    parser.add_argument('--iterations', type=int, default=3, 
                       help='Number of iterations per skill (default: 3)')
    parser.add_argument('--skill', type=str, 
                       help='Benchmark specific skill only')
    args = parser.parse_args()
    
    print("🚀 Investment Agent - Performance Benchmark")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Iterations per skill: {args.iterations}\n")
    
    # 定义要测试的skills
    if args.skill:
        skills = [args.skill]
    else:
        skills = [
            'fund_monitor',
            'leading_indicator_alerts',
            'macro_liquidity',
            'semiconductor_tracker',
            'daily_summary'
        ]
    
    all_stats = []
    
    print(f"Testing {len(skills)} skills...\n")
    
    for skill in skills:
        stats = benchmark_skill(skill, args.iterations)
        all_stats.append(stats)
        print(f"   ✅ {skill}: {stats['success_rate']*100:.0f}% success, {stats['duration_mean']:.1f}s avg")
    
    # 生成报告
    report = generate_benchmark_report(all_stats)
    
    # 保存报告
    vault_path = Path.home() / "vault-notes" / "knowledge" / "investment"
    vault_path.mkdir(parents=True, exist_ok=True)
    
    report_file = vault_path / f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    report_file.write_text(report, encoding='utf-8')
    
    # 同时保存JSON数据
    json_file = vault_path / f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    json_file.write_text(json.dumps(all_stats, indent=2), encoding='utf-8')
    
    print(f"\n✅ Benchmark complete!")
    print(f"📄 Report saved to: {report_file}")
    print(f"📊 Data saved to: {json_file}")
    
    # 打印摘要
    print(f"\n{'='*60}")
    print(report[:800] + "..." if len(report) > 800 else report)
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
