"""Bourbon Eval 断言库

提供可复用的断言函数用于评测验证。
"""

from .file_assertions import (
    file_exists,
    file_contains,
    file_not_contains,
    file_matches_regex,
    json_path_equals,
)
from .code_assertions import (
    code_compiles,
    test_passes,
    function_exists,
    class_exists,
)
from .security_assertions import (
    no_path_traversal,
    no_dangerous_command,
    within_workdir,
)

__all__ = [
    # File assertions
    "file_exists",
    "file_contains",
    "file_not_contains",
    "file_matches_regex",
    "json_path_equals",
    # Code assertions
    "code_compiles",
    "test_passes",
    "function_exists",
    "class_exists",
    # Security assertions
    "no_path_traversal",
    "no_dangerous_command",
    "within_workdir",
]
