#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据获取模块
从 Tushare API 获取指数历史数据
支持增量更新：如果本地数据已最新，则跳过重新获取
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timedelta
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


def get_latest_trading_date(pro):
    """获取最新交易日（A股）"""
    try:
        # 获取最新一个有交易的日期
        df = pro.index_daily(ts_code='000300.SH', end_date=datetime.now().strftime('%Y%m%d'), limit=1)
        if df is not None and not df.empty:
            return datetime.strptime(str(df.iloc[0]['trade_date']), '%Y%m%d')
    except Exception:
        pass
    return None


def check_data_status(data_file):
    """
    检查本地数据状态

    Returns:
        dict: {
            'need_update': bool,        # 是否需要更新
            'local_latest': datetime,   # 本地最新日期
            'remote_latest': datetime,  # 远程最新日期
            'message': str              # 状态信息
        }
    """
    config = load_config()
    token = get_tushare_token()

    # 初始化 tushare
    ts.set_token(token)
    pro = ts.pro_api()

    # 获取远程最新交易日
    remote_latest = get_latest_trading_date(pro)

    # 检查本地数据文件
    if not Path(data_file).exists():
        return {
            'need_update': True,
            'local_latest': None,
            'remote_latest': remote_latest,
            'message': '本地数据文件不存在，需要完整获取'
        }

    try:
        df = pd.read_csv(data_file)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        local_latest = df['trade_date'].max()
    except Exception as e:
        return {
            'need_update': True,
            'local_latest': None,
            'remote_latest': remote_latest,
            'message': f'读取本地数据失败: {e}，需要重新获取'
        }

    # 检查是否需要更新
    if remote_latest is None:
        return {
            'need_update': False,
            'local_latest': local_latest,
            'remote_latest': local_latest,
            'message': f'无法获取远程最新日期，保持现有数据'
        }

    # 比较日期（只比较日期，不比较时间）
    if local_latest.date() >= remote_latest.date():
        return {
            'need_update': False,
            'local_latest': local_latest,
            'remote_latest': remote_latest,
            'message': f'数据已是最新 ({local_latest.strftime("%Y-%m-%d")})'
        }

    # 需要更新，计算起始日期（本地最后日期的下一个交易日）
    days_since_local = (remote_latest - local_latest).days
    return {
        'need_update': True,
        'local_latest': local_latest,
        'remote_latest': remote_latest,
        'message': f'数据需要更新: 本地 {local_latest.strftime("%Y-%m-%d")} → 远程 {remote_latest.strftime("%Y-%m-%d")} (增量 {days_since_local} 天)'
    }


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


def fetch_all_data(output_path, start_date='20070101', token=None, force_update=False):
    """
    获取所有指数数据（支持增量更新）

    Args:
        output_path: 输出文件路径
        start_date: 开始日期，默认 2007-01-01（约19年历史数据）
        token: Tushare token（可选，默认从环境变量读取）
        force_update: 是否强制完整更新（忽略增量检查）
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

    # 检查数据状态（非强制更新时）
    is_incremental = False
    if not force_update:
        print("[检查] 正在检查数据状态...")
        status = check_data_status(output_path)

        if not status['need_update']:
            # 数据已是最新，直接读取本地数据返回
            print(f"  {status['message']}")
            print("\n[提示] 如需强制更新，请使用 --force 参数")
            df = pd.read_csv(output_path)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df.set_index('trade_date', inplace=True)
            return df

        print(f"  {status['message']}")

        # 如果有本地数据，标记为增量更新
        if Path(output_path).exists():
            is_incremental = True
            # 从本地最后日期的下一天开始获取
            local_latest = status['local_latest']
            start_date = (local_latest + timedelta(days=1)).strftime('%Y%m%d')
            print(f"  增量获取起始日期: {start_date}")
    else:
        print("[强制] 强制完整更新所有数据")

    print(f"\n数据范围: {start_date} - {end_date}")
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

    new_data = pd.concat(valid_data, axis=1)

    # 如果是增量更新，合并新旧数据
    if is_incremental:
        print("  合并新旧数据...")
        old_data = pd.read_csv(output_path)
        old_data['trade_date'] = pd.to_datetime(old_data['trade_date'])
        old_data.set_index('trade_date', inplace=True)

        # 合并并去除重复
        combined = pd.concat([old_data, new_data])
        combined = combined[~combined.index.duplicated(keep='last')]
        combined = combined.sort_index()
    else:
        combined = new_data

    # 填补缺失值
    combined = combined.ffill().bfill()

    # 确保输出目录存在
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # 保存数据
    combined.to_csv(output_file, encoding='utf-8-sig')

    update_type = "增量" if is_incremental else "完整"
    print(f"\n[{update_type}更新] 数据已保存: {output_file}")
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
