#!/usr/bin/env python3
"""查询特定 case 的评测结果

Usage:
    python query_result.py <case_id> [report_json]
    
Example:
    python query_result.py skill-inv-fund-001
    python query_result.py skill-inv-vix-001 evals/results/benchmark_2026-03-22_171155.json
"""

import json
import sys
from pathlib import Path


def find_latest_report() -> Path:
    """找到最新的 benchmark 报告"""
    results_dir = Path("evals/results")
    json_files = list(results_dir.glob("benchmark_*.json"))
    if not json_files:
        print("Error: No benchmark report found in evals/results/")
        sys.exit(1)
    return max(json_files, key=lambda p: p.stat().st_mtime)


def query_case(case_id: str, report_path: Path):
    """查询特定 case 的结果"""
    data = json.loads(report_path.read_text())
    
    # 查找 case
    case = None
    for c in data.get("cases", []):
        if c.get("case_id") == case_id:
            case = c
            break
    
    if not case:
        print(f"Error: Case '{case_id}' not found in {report_path}")
        print(f"\nAvailable cases:")
        for c in data.get("cases", [])[:10]:
            print(f"  - {c.get('case_id')}")
        sys.exit(1)
    
    # 显示结果
    summary = case.get("summary", {})
    runs = case.get("runs", [{}])[0]
    
    print(f"\n{'='*60}")
    print(f"Case: {case_id}")
    print(f"Name: {case.get('case_name', 'N/A')}")
    print(f"{'='*60}")
    
    # 整体状态
    status = "✅ PASSED" if summary.get("pass_rate", 0) == 1.0 else "❌ FAILED"
    print(f"\nStatus: {status}")
    print(f"Pass Rate: {summary.get('pass_rate', 0)*100:.1f}%")
    print(f"Duration: {summary.get('duration_mean', 0):.0f}ms")
    print(f"Tokens: {runs.get('token_usage', {}).get('total_tokens', 0)}")
    
    # 断言详情
    print(f"\nAssertions:")
    for assertion in runs.get("assertions", []):
        status = "✓" if assertion.get("passed") else "✗"
        print(f"  {status} {assertion.get('id')}: {assertion.get('text', '')}")
        print(f"     → {assertion.get('evidence', 'N/A')}")
    
    # 输出预览
    output = runs.get("output", "")
    if output:
        print(f"\nOutput Preview:")
        print(f"  {output[:200]}...")
    
    print(f"\n{'='*60}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    case_id = sys.argv[1]
    report_path = Path(sys.argv[2]) if len(sys.argv) > 2 else find_latest_report()
    
    query_case(case_id, report_path)


if __name__ == "__main__":
    main()
