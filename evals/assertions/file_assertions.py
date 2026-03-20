"""文件相关断言"""

import json
import re
from pathlib import Path
from typing import Any


def file_exists(path: Path, **kwargs) -> tuple[bool, str]:
    """检查文件是否存在"""
    if path.exists() and path.is_file():
        return True, f"File exists: {path}"
    return False, f"File not found: {path}"


def file_contains(path: Path, content: str, **kwargs) -> tuple[bool, str]:
    """检查文件内容包含指定字符串"""
    if not path.exists():
        return False, f"File not found: {path}"
    
    text = path.read_text(encoding="utf-8")
    if content in text:
        return True, f"Found '{content}' in {path}"
    return False, f"'{content}' not found in {path}"


def file_not_contains(path: Path, content: str, **kwargs) -> tuple[bool, str]:
    """检查文件内容不包含指定字符串"""
    if not path.exists():
        return True, f"File not found (so doesn't contain): {path}"
    
    text = path.read_text(encoding="utf-8")
    if content not in text:
        return True, f"'{content}' correctly not in {path}"
    return False, f"'{content}' unexpectedly found in {path}"


def file_matches_regex(path: Path, pattern: str, **kwargs) -> tuple[bool, str]:
    """检查文件内容匹配正则表达式"""
    if not path.exists():
        return False, f"File not found: {path}"
    
    text = path.read_text(encoding="utf-8")
    if re.search(pattern, text):
        return True, f"Pattern '{pattern}' matches in {path}"
    return False, f"Pattern '{pattern}' not found in {path}"


def json_path_equals(path: Path, json_path: str, expected: Any, **kwargs) -> tuple[bool, str]:
    """检查 JSON 文件的指定路径等于期望值
    
    Args:
        path: JSON 文件路径
        json_path: 点分隔的路径，如 "mcp.servers.0.name"
        expected: 期望值
    """
    if not path.exists():
        return False, f"File not found: {path}"
    
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    
    # 遍历路径
    current = data
    for key in json_path.split("."):
        if isinstance(current, dict):
            if key not in current:
                return False, f"Key '{key}' not found in path"
            current = current[key]
        elif isinstance(current, list):
            try:
                idx = int(key)
                current = current[idx]
            except (ValueError, IndexError):
                return False, f"Invalid index '{key}' in list"
        else:
            return False, f"Cannot navigate into {type(current)}"
    
    if current == expected:
        return True, f"Value at '{json_path}' equals '{expected}'"
    return False, f"Value at '{json_path}' is '{current}', expected '{expected}'"
