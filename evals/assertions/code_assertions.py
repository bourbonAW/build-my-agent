"""代码相关断言"""

import ast
import subprocess
import sys
from pathlib import Path


def code_compiles(path: Path, **kwargs) -> tuple[bool, str]:
    """检查 Python 代码可编译"""
    if not path.exists():
        return False, f"File not found: {path}"
    
    try:
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        return True, f"Python code compiles: {path}"
    except SyntaxError as e:
        return False, f"Syntax error in {path}: {e}"


def test_passes(test_path: Path, **kwargs) -> tuple[bool, str]:
    """运行 pytest 检查测试通过"""
    if not test_path.exists():
        return False, f"Test file not found: {test_path}"
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return True, f"Tests pass: {test_path}"
        return False, f"Tests failed: {result.stdout}\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return False, f"Test timeout: {test_path}"
    except Exception as e:
        return False, f"Error running tests: {e}"


def function_exists(path: Path, function_name: str, **kwargs) -> tuple[bool, str]:
    """检查 Python 文件中存在指定函数"""
    if not path.exists():
        return False, f"File not found: {path}"
    
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                return True, f"Function '{function_name}' found in {path}"
        
        return False, f"Function '{function_name}' not found in {path}"
    except Exception as e:
        return False, f"Error parsing {path}: {e}"


def class_exists(path: Path, class_name: str, **kwargs) -> tuple[bool, str]:
    """检查 Python 文件中存在指定类"""
    if not path.exists():
        return False, f"File not found: {path}"
    
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return True, f"Class '{class_name}' found in {path}"
        
        return False, f"Class '{class_name}' not found in {path}"
    except Exception as e:
        return False, f"Error parsing {path}: {e}"
