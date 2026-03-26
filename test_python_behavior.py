#!/usr/bin/env python3
# 测试 Python 行为

print("=== 测试 a+1 的行为 ===")

try:
    result = a + 1
    print(f"a + 1 = {result}")
except NameError as e:
    print(f"NameError: {e}")

print("\n=== 测试完成 ===")
