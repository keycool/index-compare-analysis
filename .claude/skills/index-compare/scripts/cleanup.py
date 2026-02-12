#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
临时文件清理模块
自动清理 tmpclaude-* 临时文件
"""

import os
from pathlib import Path


def cleanup_temp_files(base_dir=None, max_files=10, pattern="tmpclaude-*"):
    """
    清理临时文件

    Args:
        base_dir: 基础目录，默认为 skill 根目录的上3级
        max_files: 触发清理的文件数量阈值
        pattern: 文件匹配模式

    Returns:
        tuple: (清理的文件数, 是否触发清理)
    """
    if base_dir is None:
        # 默认为 skill 根目录的上3级（项目根目录）
        base_dir = Path(__file__).parent.parent.parent.parent.parent
    else:
        base_dir = Path(base_dir)

    # 查找所有匹配的临时文件
    temp_files = list(base_dir.rglob(pattern))

    file_count = len(temp_files)

    # 如果文件数量超过阈值，执行清理
    if file_count >= max_files:
        deleted_count = 0
        for temp_file in temp_files:
            try:
                if temp_file.is_file():
                    temp_file.unlink()
                    deleted_count += 1
            except Exception as e:
                # 忽略删除失败的文件
                pass

        return deleted_count, True

    return 0, False


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description='清理临时文件')
    parser.add_argument('--max', '-m', type=int, default=10,
                        help='触发清理的文件数量阈值 (默认: 10)')
    parser.add_argument('--pattern', '-p', default='tmpclaude-*',
                        help='文件匹配模式 (默认: tmpclaude-*)')
    parser.add_argument('--force', '-f', action='store_true',
                        help='强制清理所有匹配文件')

    args = parser.parse_args()

    if args.force:
        # 强制清理模式
        base_dir = Path(__file__).parent.parent.parent.parent.parent
        temp_files = list(base_dir.rglob(args.pattern))
        deleted_count = 0

        for temp_file in temp_files:
            try:
                if temp_file.is_file():
                    temp_file.unlink()
                    deleted_count += 1
            except Exception:
                pass

        print(f"[清理] 强制清理完成，删除了 {deleted_count} 个临时文件")
    else:
        # 自动清理模式
        deleted_count, triggered = cleanup_temp_files(max_files=args.max, pattern=args.pattern)

        if triggered:
            print(f"[清理] 临时文件数量超过阈值 ({args.max})，已清理 {deleted_count} 个文件")
        else:
            print(f"[清理] 临时文件数量未超过阈值，无需清理")


if __name__ == '__main__':
    main()
