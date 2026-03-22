#!/usr/bin/env python3
"""
Run Tests - 运行测试用例

Usage:
    python scripts/run_tests.py
    python scripts/run_tests.py --eval-id 1
    python scripts/run_tests.py --category crisis_response
"""

import json
import sys
from pathlib import Path
from datetime import datetime

def load_evals():
    """加载测试用例"""
    evals_path = Path(__file__).parent.parent / "evals" / "evals.json"
    
    if not evals_path.exists():
        print(f"❌ Evals file not found: {evals_path}")
        return None
    
    with open(evals_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def run_test(eval_case):
    """运行单个测试用例"""
    print(f"\n{'='*60}")
    print(f"🧪 Test #{eval_case['id']}: {eval_case['eval_name']}")
    print(f"{'='*60}")
    print(f"Prompt: {eval_case['prompt'][:100]}...")
    print(f"Expected: {eval_case['expected_output'][:100]}...")
    
    # 这里应该实际运行skill并检查结果
    # 简化版：只打印信息，实际检查需要集成到Claude Code测试框架
    
    print(f"\n✅ Test case loaded successfully")
    print(f"   Category: {eval_case.get('metadata', {}).get('category', 'unknown')}")
    print(f"   Difficulty: {eval_case.get('metadata', {}).get('difficulty', 'unknown')}")
    print(f"   Assertions: {len(eval_case.get('assertions', []))}")
    
    return {
        'id': eval_case['id'],
        'name': eval_case['eval_name'],
        'status': 'loaded',
        'prompt': eval_case['prompt']
    }

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run investment agent tests')
    parser.add_argument('--eval-id', type=int, help='Run specific test by ID')
    parser.add_argument('--category', type=str, help='Run tests by category')
    parser.add_argument('--list', action='store_true', help='List all test cases')
    args = parser.parse_args()
    
    print("🧪 Investment Agent - Test Runner")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 加载测试用例
    evals_data = load_evals()
    if not evals_data:
        sys.exit(1)
    
    print(f"✅ Loaded {len(evals_data['evals'])} test cases")
    print(f"   Skill: {evals_data['skill_name']}")
    print(f"   Version: {evals_data.get('version', 'unknown')}")
    
    # 列出所有测试
    if args.list:
        print(f"\n{'='*60}")
        print("📋 Available Test Cases:")
        print(f"{'='*60}\n")
        
        for eval_case in evals_data['evals']:
            should_trigger = eval_case.get('metadata', {}).get('should_trigger', True)
            trigger_status = "🟢" if should_trigger else "🔴"
            
            print(f"{trigger_status} #{eval_case['id']}: {eval_case['eval_name']}")
            print(f"   Category: {eval_case.get('metadata', {}).get('category', 'unknown')}")
            print(f"   Difficulty: {eval_case.get('metadata', {}).get('difficulty', 'unknown')}")
            print(f"   Prompt: {eval_case['prompt'][:80]}...")
            print()
        
        return 0
    
    # 筛选测试用例
    tests_to_run = evals_data['evals']
    
    if args.eval_id:
        tests_to_run = [e for e in tests_to_run if e['id'] == args.eval_id]
        if not tests_to_run:
            print(f"❌ Test #{args.eval_id} not found")
            sys.exit(1)
    
    if args.category:
        tests_to_run = [e for e in tests_to_run 
                       if e.get('metadata', {}).get('category') == args.category]
        if not tests_to_run:
            print(f"❌ No tests found in category: {args.category}")
            sys.exit(1)
    
    print(f"\n🎯 Running {len(tests_to_run)} test(s)...\n")
    
    # 运行测试
    results = []
    for eval_case in tests_to_run:
        result = run_test(eval_case)
        results.append(result)
    
    # 汇总
    print(f"\n{'='*60}")
    print("📊 Test Summary")
    print(f"{'='*60}\n")
    print(f"Total tests: {len(results)}")
    print(f"Loaded successfully: {len(results)} ✅")
    
    print(f"\n📝 Next Steps:")
    print("1. Use Claude Code's skill testing framework to run actual tests")
    print("2. Check assertions against real outputs")
    print("3. Generate evaluation report with pass/fail status")
    print("4. Iterate and improve skill based on results")
    
    print(f"\n💡 To run actual tests in Claude Code:")
    print("   - Use /skill-test command (if available)")
    print("   - Or manually invoke skill with test prompts")
    print("   - Compare outputs to expected results")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
