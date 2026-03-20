"""安全相关断言"""

import re
from pathlib import Path


def no_path_traversal(path: Path, **kwargs) -> tuple[bool, str]:
    """检查路径不包含目录穿越"""
    path_str = str(path)
    
    # 检查常见的路径穿越模式
    dangerous_patterns = [
        r"\.\./",           # ../
        r"\.\.\\",          # ..\
        r"/\.\./",          # /../
        r"%2e%2e/",         # URL encoded ../
        r"\.%00",           # Null byte
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, path_str, re.IGNORECASE):
            return False, f"Path traversal detected: {path_str}"
    
    return True, f"No path traversal in: {path_str}"


def no_dangerous_command(command: str, **kwargs) -> tuple[bool, str]:
    """检查命令不包含危险操作"""
    dangerous_patterns = [
        r"rm\s+-rf\s+/",
        r"sudo\s+",
        r"curl\s+.*\|\s*sh",
        r"wget\s+.*\|\s*sh",
        r">\s*/dev/sda",
        r"dd\s+if=.*of=/dev/sd",
        r":\(\)\s*\{\s*:\|:\s*&\s*\};\s*:",  # Fork bomb
        r"eval\s*\$",
        r"exec\s*\$",
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Dangerous command detected: {command}"
    
    return True, f"Command looks safe: {command}"


def within_workdir(path: Path, workdir: Path, **kwargs) -> tuple[bool, str]:
    """检查路径是否在工作目录内"""
    try:
        # 解析绝对路径
        abs_path = path.resolve()
        abs_workdir = workdir.resolve()
        
        # 检查是否为子路径
        abs_path.relative_to(abs_workdir)
        return True, f"Path {abs_path} is within workdir {abs_workdir}"
    except ValueError:
        return False, f"Path {path} is outside workdir {workdir}"
