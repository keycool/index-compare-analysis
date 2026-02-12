#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据获取模块
从 Tushare API 获取指数历史数据
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
import tushare as ts


def load_config():
    """加载配置文件"""
    config_path = Path(__file__).parent.parent / 'config.json'
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_tushare_token(token_arg=None):
    """获取 Tushare Token"""
    token = token_arg or os.environ.get('TUSHARE_TOKEN')
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN 环境变量")
        print("\n请按以下方式设置:")
        print("  Windows PowerShell: $env:TUSHARE_TOKEN = '你的Token'")
        print("  Windows CMD: set TUSHARE_TOKEN=你的Token")
        print("  Linux/Mac: export TUSHARE_TOKEN=你的Token")
        print("  或使用参数: python fetch_data.py --token 你的Token")
        print("\n获取Token: https://tushare.pro/register")
        sys.exit(1)
    return token


def get_index_data(pro, ts_code, start_date, end_date, config):
    """
    获取单个指数的历史数据

    Args:
        pro: tushare pro api
        ts_code: 指数代码
        start_date: 开始日期
        end_date: 结束日期
        config: 配置信息

    Returns:
        DataFrame with close price
    """
    retry_times = config['api']['retry_times']
    retry_interval = config['api']['retry_interval']

    for attempt in range(retry_times):
        try:
            df = pro.index_daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df is None or df.empty:
                raise ValueError(f"未获取到 {ts_code} 的数据")

            df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
            df.set_index('trade_date', inplace=True)
            df.sort_index(inplace=True)

            return df[['close']]

        except Exception as e:
            print(f"  第 {attempt + 1} 次尝试失败: {e}")
            if attempt < retry_times - 1:
                print(f"  {retry_interval} 秒后重试...")
                time.sleep(retry_interval)
            else:
                raise Exception(f"获取 {ts_code} 数据失败，已重试 {retry_times} 次")


def fetch_all_data(output_path, start_date='20150101', token=None):
    """
    获取所有指数数据

    Args:
        output_path: 输出文件路径
        start_date: 开始日期，默认 2015-01-01
        token: Tushare token（可选，默认从环境变量读取）
    """
    config = load_config()
    token = get_tushare_token(token)

    # 初始化 tushare
    ts.set_token(token)
    pro = ts.pro_api()

    # 时间范围
    end_date = datetime.now().strftime('%Y%m%d')

    print("=" * 50)
    print("       指数数据获取")
    print("=" * 50)
    print(f"数据范围: {start_date} - {end_date}")
    print()

    # 获取各指数数据
    data_dict = {}
    indices = config['indices']

    for key, info in indices.items():
        code = info['code']
        name = info['name']
        print(f"正在获取 {name} ({code})...")

        try:
            data_dict[key] = get_index_data(pro, code, start_date, end_date, config)
            print(f"  [OK] 成功获取 {len(data_dict[key])} 条记录")
        except Exception as e:
            print(f"  [X] 失败: {e}")
            data_dict[key] = None

    # 合并数据
    print("\n正在合并数据...")
    valid_data = {k: v['close'] for k, v in data_dict.items() if v is not None}

    if not valid_data:
        print("错误: 未能获取任何有效数据")
        sys.exit(1)

    combined = pd.concat(valid_data, axis=1)

    # 填补缺失值
    combined = combined.ffill().bfill()

    # 确保输出目录存在
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # 保存数据
    combined.to_csv(output_file, encoding='utf-8-sig')

    print(f"\n[OK] 数据已保存: {output_file}")
    print(f"  共 {len(combined)} 个交易日")
    print(f"  列: {list(combined.columns)}")
    print(f"  时间范围: {combined.index.min()} ~ {combined.index.max()}")

    return combined


def main():
    parser = argparse.ArgumentParser(description='获取指数历史数据')
    parser.add_argument('--output', '-o',
                        default='data/raw_data.csv',
                        help='输出文件路径 (默认: data/raw_data.csv)')
    parser.add_argument('--start', '-s',
                        default='20150101',
                        help='开始日期 (默认: 20150101)')
    parser.add_argument('--token', '-t',
                        default=None,
                        help='Tushare Token (可选，默认从环境变量读取)')

    args = parser.parse_args()

    # 切换到 skill 目录
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)

    fetch_all_data(args.output, args.start, args.token)


if __name__ == '__main__':
    main()
