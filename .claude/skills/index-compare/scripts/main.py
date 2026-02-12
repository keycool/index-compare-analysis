#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
指数比价分析 - 主入口脚本
一键执行完整分析流程
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

# 添加父目录到 Python 路径以支持模块导入
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir))


def quick_query(index_code=None):
    """
    快速查询模式：读取已有数据并显示

    Args:
        index_code: 指数代码（'ZZ500', 'ZZ1000', 或 None 表示全部）
    """
    import json
    import pandas as pd

    # 切换到 skill 目录
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)

    # 检查数据文件是否存在
    conclusions_file = Path('data/conclusions.json')
    processed_file = Path('data/processed_data.csv')

    if not conclusions_file.exists():
        print("[错误] 数据文件不存在")
        print("\n请先运行完整分析生成数据:")
        print("  python scripts/main.py")
        sys.exit(1)

    # 读取分析结论
    with open(conclusions_file, 'r', encoding='utf-8') as f:
        conclusions = json.load(f)

    # 读取处理后的数据（获取更新时间）
    if processed_file.exists():
        df = pd.read_csv(processed_file, parse_dates=['trade_date'])
        latest_date = df.iloc[-1]['trade_date'].strftime('%Y-%m-%d')
    else:
        latest_date = "未知"

    # 验证指数代码
    valid_codes = ['ZZ500', 'ZZ1000', 'ZZA500']
    if index_code and index_code not in valid_codes:
        print(f"[错误] 指数代码 {index_code} 不存在")
        print(f"\n支持的代码: {', '.join(valid_codes)}")
        sys.exit(1)

    # 打印标题
    print("=" * 60)
    print("         指数比价快速查询")
    print("=" * 60)
    print(f"数据更新时间: {latest_date}")
    print()

    # 如果指定了特定指数，只显示该指数
    if index_code:
        display_codes = [index_code]
    else:
        display_codes = valid_codes

    # 显示数据摘要表格
    if len(display_codes) > 1:
        print("最新数据:")
        print("┌─────────────┬──────────┬──────────┬──────────┐")
        print("│ 指标        │ 中证500  │ 中证1000 │ 中证A500 │")
        print("├─────────────┼──────────┼──────────┼──────────┤")

        zz500 = conclusions.get('ZZ500', {})
        zz1000 = conclusions.get('ZZ1000', {})
        zza500 = conclusions.get('ZZA500', {})

        print(f"│ 当前比价    │ {zz500.get('current_ratio', 0):>8.4f} │ {zz1000.get('current_ratio', 0):>8.4f} │ {zza500.get('current_ratio', 0):>8.4f} │")
        print(f"│ 历史分位    │ {zz500.get('percentile', {}).get('value', 0):>7.1f}% │ {zz1000.get('percentile', {}).get('value', 0):>7.1f}% │ {zza500.get('percentile', {}).get('value', 0):>7.1f}% │")
        print(f"│ 30日偏离    │ {zz500.get('deviation', {}).get('value', 0):>+7.1f}% │ {zz1000.get('deviation', {}).get('value', 0):>+7.1f}% │ {zza500.get('deviation', {}).get('value', 0):>+7.1f}% │")

        zz500_rec = zz500.get('recommendation', {})
        zz1000_rec = zz1000.get('recommendation', {})
        zza500_rec = zza500.get('recommendation', {})
        zz500_text = f"{zz500_rec.get('icon', '')} {zz500_rec.get('action', '')}"
        zz1000_text = f"{zz1000_rec.get('icon', '')} {zz1000_rec.get('action', '')}"
        zza500_text = f"{zza500_rec.get('icon', '')} {zza500_rec.get('action', '')}"

        print(f"│ 配置建议    │ {zz500_text:^8} │ {zz1000_text:^8} │ {zza500_text:^8} │")
        print("└─────────────┴──────────┴──────────┴──────────┘")
        print()

    # 显示详细分析摘要
    for code in display_codes:
        if code in conclusions:
            data = conclusions[code]
            print(data.get('summary', ''))
            print()
            print("-" * 60)
            print()


def run_pipeline():
    """运行完整分析流程"""
    # 切换到 skill 目录
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)

    # 自动清理临时文件
    try:
        from scripts.cleanup import cleanup_temp_files
        deleted_count, triggered = cleanup_temp_files(max_files=20)
        if triggered:
            print(f"[清理] 已清理 {deleted_count} 个临时文件")
    except Exception:
        pass  # 清理失败不影响主流程

    print("=" * 60)
    print("         指数比价分析 (Index Compare)")
    print("=" * 60)
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 检查环境变量
    print("\n[步骤 1/5] 检查环境配置...")
    token = os.environ.get('TUSHARE_TOKEN')

    # 如果环境变量未设置，尝试从 .env 文件读取
    if not token:
        env_file = Path('.env')
        if env_file.exists():
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('TUSHARE_TOKEN='):
                        token = line.split('=', 1)[1].strip()
                        os.environ['TUSHARE_TOKEN'] = token
                        break

    if not token:
        print("错误: 未设置 TUSHARE_TOKEN 环境变量")
        print("\n请按以下方式设置:")
        print("  Windows PowerShell: $env:TUSHARE_TOKEN = '你的Token'")
        print("  Windows CMD: set TUSHARE_TOKEN=你的Token")
        print("  Linux/Mac: export TUSHARE_TOKEN=你的Token")
        print("  或在 skill 目录下创建 .env 文件并添加: TUSHARE_TOKEN=你的Token")
        print("\n获取Token: https://tushare.pro/register")
        sys.exit(1)
    print("[OK] Token 已配置")

    # 导入模块
    try:
        from scripts.fetch_data import fetch_all_data
        from scripts.calculate import process_data
        from scripts.analyze import analyze
        from scripts.generate_report import generate_report
    except ImportError as e:
        print(f"[ERROR] 导入模块失败: {e}")
        print("请确保已安装所有依赖: pip install tushare pandas numpy plotly scipy")
        sys.exit(1)

    # 加载配置获取报告目录
    import json
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    report_dir = config['output']['report_dir']

    # 步骤 2: 获取数据
    print("\n[步骤 2/5] 获取指数数据...")
    try:
        fetch_all_data('data/raw_data.csv')
    except Exception as e:
        print(f"[ERROR] 数据获取失败: {e}")
        sys.exit(1)

    # 步骤 3: 计算比价
    print("\n[步骤 3/5] 计算比价指标...")
    try:
        process_data('data/raw_data.csv', 'data/processed_data.csv')
    except Exception as e:
        print(f"[ERROR] 比价计算失败: {e}")
        sys.exit(1)

    # 步骤 4: 智能分析
    print("\n[步骤 4/5] 生成智能分析...")
    try:
        analyze('data/analysis_results.json', 'data/conclusions.json')
    except Exception as e:
        print(f"[ERROR] 智能分析失败: {e}")
        sys.exit(1)

    # 步骤 5: 生成报告
    print("\n[步骤 5/5] 生成 HTML 报告...")
    try:
        report_file = generate_report('data/processed_data.csv', 'data/conclusions.json', report_dir)
    except Exception as e:
        print(f"[ERROR] 报告生成失败: {e}")
        sys.exit(1)

    # 读取并显示数据摘要
    print("\n" + "=" * 60)
    print("         [OK] 分析完成!")
    print("=" * 60)

    try:
        import pandas as pd
        import json

        # 读取处理后的数据
        df = pd.read_csv('data/processed_data.csv', parse_dates=['trade_date'])
        latest = df.iloc[-1]

        # 读取分析结论
        with open('data/conclusions.json', 'r', encoding='utf-8') as f:
            conclusions = json.load(f)

        # 显示数据摘要
        print(f"\n[DATA] 最新数据 ({latest['trade_date'].strftime('%Y-%m-%d')}):")
        print("+-------------+----------+----------+----------+")
        print("| 指标        | 中证500  | 中证1000 | 沪深300  |")
        print("+-------------+----------+----------+----------+")
        print(f"| 收盘价      | {latest['ZZ500']:>8.2f} | {latest['ZZ1000']:>8.2f} | {latest['HS300']:>8.2f} |")
        print(f"| 比价        | {latest['ZZ500_ratio']:>8.4f} | {latest['ZZ1000_ratio']:>8.4f} | (基准)   |")
        print(f"| 历史分位    | {latest['ZZ500_percentile']:>7.1f}% | {latest['ZZ1000_percentile']:>7.1f}% |    -     |")
        print(f"| 30日偏离    | {latest['ZZ500_deviation']:>7.1f}% | {latest['ZZ1000_deviation']:>7.1f}% |    -     |")
        print("+-------------+----------+----------+----------+")

        # 显示配置建议
        print("\n[RECOMMEND] 配置建议:")
        for idx_name, conclusion in conclusions.items():
            if idx_name in ['ZZ500', 'ZZ1000', 'ZZA500']:
                name_map = {'ZZ500': '中证500', 'ZZ1000': '中证1000', 'ZZA500': '中证A500'}
                name = name_map.get(idx_name, idx_name)
                rec = conclusion.get('recommendation', {})
                suggestion = rec.get('action', '标配')
                icon = rec.get('icon', '')
                print(f"\n【{name}】{icon} {suggestion}")
                if 'reasons' in rec:
                    for reason in rec['reasons']:
                        print(f"  - {reason}")

    except Exception as e:
        print(f"\n[WARN] 无法显示数据摘要: {e}")

    print(f"\n[REPORT] 报告文件: {report_file}")
    print("\n提示: 用浏览器打开上述 HTML 文件查看交互式报告")

    return report_file


def main():
    parser = argparse.ArgumentParser(
        description='指数比价分析工具 - 一键分析中证500/1000相对沪深300的比价关系',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py              # 运行完整分析流程
  python main.py --query      # 快速查询已有数据（所有指数）
  python main.py --query ZZ500   # 快速查询中证500
  python main.py --help       # 显示帮助信息

环境变量:
  TUSHARE_TOKEN              # Tushare API Token (必需)
        """
    )

    parser.add_argument('--query', nargs='?', const='all',
                        help='快速查询模式：查看已有数据（可选指定 ZZ500 或 ZZ1000）')

    args = parser.parse_args()

    # 如果是查询模式，执行查询后直接返回
    if args.query is not None:
        query_target = None if args.query == 'all' else args.query
        quick_query(query_target)
        return

    # 否则执行完整分析流程
    run_pipeline()


if __name__ == '__main__':
    main()
