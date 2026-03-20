#!/usr/bin/env python3
"""验证 Eval 框架是否正确配置"""

import json
import sys
from pathlib import Path


def check_structure():
    """检查目录结构"""
    print("Checking directory structure...")
    
    required_dirs = [
        "evals/fixtures",
        "evals/cases",
        "evals/assertions",
    ]
    
    for dir_path in required_dirs:
        path = Path(dir_path)
        if path.exists():
            print(f"  ✓ {dir_path}")
        else:
            print(f"  ✗ {dir_path} - MISSING")
            return False
    
    return True


def check_config():
    """检查配置文件"""
    print("\nChecking config file...")
    
    config_path = Path("evals/config.toml")
    if not config_path.exists():
        print("  ✗ config.toml - MISSING")
        return False
    
    try:
        import toml
        with open(config_path) as f:
            config = toml.load(f)
        
        required_keys = ["metadata", "runner", "dimensions"]
        for key in required_keys:
            if key in config:
                print(f"  ✓ config.{key}")
            else:
                print(f"  ✗ config.{key} - MISSING")
                return False
        
        return True
    except Exception as e:
        print(f"  ✗ Error reading config: {e}")
        return False


def check_cases():
    """检查评测用例"""
    print("\nChecking eval cases...")
    
    cases_dir = Path("evals/cases")
    case_files = list(cases_dir.rglob("*.json"))
    
    if not case_files:
        print("  ✗ No eval cases found")
        return False
    
    print(f"  Found {len(case_files)} case files")
    
    valid_cases = 0
    for case_file in case_files:
        try:
            with open(case_file) as f:
                case = json.load(f)
            
            required = ["id", "name", "prompt", "assertions"]
            missing = [f for f in required if f not in case]
            
            if missing:
                print(f"  ✗ {case_file.name} - missing: {missing}")
            else:
                print(f"  ✓ {case['id']}: {case['name']}")
                valid_cases += 1
        except Exception as e:
            print(f"  ✗ {case_file.name} - {e}")
    
    return valid_cases > 0


def check_assertions():
    """检查断言库"""
    print("\nChecking assertions library...")
    
    try:
        sys.path.insert(0, "evals")
        from assertions import (
            file_exists,
            file_contains,
            no_path_traversal,
        )
        print("  ✓ assertions module imports successfully")
        return True
    except Exception as e:
        print(f"  ✗ Error importing assertions: {e}")
        return False


def check_runner():
    """检查 runner"""
    print("\nChecking runner...")
    
    runner_path = Path("evals/runner.py")
    if not runner_path.exists():
        print("  ✗ runner.py - MISSING")
        return False
    
    print("  ✓ runner.py exists")
    
    try:
        # 尝试导入（不实际运行）
        sys.path.insert(0, "evals")
        import runner
        print("  ✓ runner module imports successfully")
        return True
    except Exception as e:
        print(f"  ✗ Error importing runner: {e}")
        return False


def main():
    print("="*60)
    print("Bourbon Eval Framework Validation")
    print("="*60)
    
    checks = [
        ("Structure", check_structure),
        ("Config", check_config),
        ("Cases", check_cases),
        ("Assertions", check_assertions),
        ("Runner", check_runner),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} check failed with exception: {e}")
            results.append((name, False))
    
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
    
    all_passed = all(r for _, r in results)
    
    if all_passed:
        print("\n✓ All checks passed! Eval framework is ready.")
        return 0
    else:
        print("\n✗ Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
