#!/usr/bin/env python3
# 测试os模块功能的脚本

import os
import sys

print("=== os模块功能测试 ===")
print(f"当前工作目录: {os.getcwd()}")
print(f"Python版本: {sys.version}")

# 测试文件路径操作
current_dir = os.path.dirname(os.path.abspath(__file__))
print(f"脚本所在目录: {current_dir}")

# 测试路径拼接
test_file = os.path.join(current_dir, 'test_output.txt')
print(f"测试文件路径: {test_file}")

print("os模块功能正常！")
