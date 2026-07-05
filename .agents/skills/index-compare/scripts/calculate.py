#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
比价计算模块
计算指数间比价关系、移动平均、历史分位等指标
"""

import os
import json
import argparse
from pathlib import Path

import pandas as pd
import numpy as np
from scipy.stats import percentileofscore


def load_config():
    """加载配置文件"""
    config_path = Path(__file__).parent.parent / 'config.json'
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def calculate_ratio(df, target_col, base_col):
    """
    计算比价

    Args:
        df: DataFrame
        target_col: 目标指数列名
        base_col: 基准指数列名

    Returns:
        Series: 比价序列
    """
    return df[target_col] / df[base_col]


def calculate_ma(series, window=30):
    """
    计算移动平均

    Args:
        series: 数据序列
        window: 窗口大小

    Returns:
        Series: 移动平均序列
    """
    return series.rolling(window=window).mean()


def calculate_deviation(current_value, ma_value):
    """
    计算偏离度

    Args:
        current_value: 当前值
        ma_value: 均线值

    Returns:
        float: 偏离度百分比
    """
    if ma_value == 0 or pd.isna(ma_value):
        return 0
    return (current_value - ma_value) / ma_value * 100


def calculate_percentile(series, current_value, use_all_history=True):
    """
    计算历史分位

    Args:
        series: 历史数据序列
        current_value: 当前值
        use_all_history: 是否使用全部历史数据

    Returns:
        float: 分位数 (0-100)
    """
    if use_all_history:
        data = series.dropna()
    else:
        data = series.tail(250).dropna()

    return percentileofscore(data, current_value)


def calculate_trend(series, windows=[5, 10, 20]):
    """
    计算趋势变化

    Args:
        series: 数据序列
        windows: 对比窗口列表

    Returns:
        dict: 各窗口的变化率
    """
    current = series.iloc[-1]
    changes = {}

    for w in windows:
        if len(series) > w:
            past = series.iloc[-w-1]
            change = (current - past) / past * 100 if past != 0 else 0
            changes[f'change_{w}d'] = round(change, 2)
        else:
            changes[f'change_{w}d'] = None

    return changes


def determine_trend(changes):
    """
    判定趋势

    Args:
        changes: 各窗口变化率字典

    Returns:
        str: 趋势判定
    """
    values = [v for v in changes.values() if v is not None]

    if not values:
        return "数据不足"

    # 计算上涨和下跌的数量
    up_count = sum(1 for v in values if v > 0.5)
    down_count = sum(1 for v in values if v < -0.5)
    strong_up = all(v > 1 for v in values)
    strong_down = all(v < -1 for v in values)

    if strong_up:
        return "强上升"
    elif strong_down:
        return "强下降"
    elif up_count >= 2:
        return "弱上升"
    elif down_count >= 2:
        return "弱下降"
    else:
        return "震荡"


def process_data(input_path, output_path):
    """
    处理原始数据，计算所有指标

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
    """
    config = load_config()
    ma_window = config['analysis']['ma_window']
    trend_windows = config['analysis']['trend_windows']
    use_all_history = config['analysis']['percentile_base'] == 'all_history'

    print("=" * 50)
    print("       比价指标计算")
    print("=" * 50)

    # 读取数据
    print(f"\n读取数据: {input_path}")
    df = pd.read_csv(input_path, index_col=0, parse_dates=True)
    print(f"  数据行数: {len(df)}")
    print(f"  数据列: {list(df.columns)}")

    # 获取基准指数
    base_col = 'HS300'  # 沪深300作为基准

    # 获取目标指数
    target_indices = ['ZZ500', 'ZZ1000', 'ZZA500']

    # 计算比价和相关指标
    analysis_results = {}

    for target in target_indices:
        if target not in df.columns:
            print(f"  警告: 缺少 {target} 数据，跳过")
            continue

        print(f"\n计算 {target} vs {base_col}...")

        # 计算比价
        ratio_col = f'{target}_ratio'
        df[ratio_col] = calculate_ratio(df, target, base_col)

        # 计算移动平均
        ma_col = f'{target}_MA{ma_window}'
        df[ma_col] = calculate_ma(df[ratio_col], ma_window)

        # 当前值
        current_ratio = df[ratio_col].iloc[-1]
        current_ma = df[ma_col].iloc[-1]

        # 计算偏离度
        deviation = calculate_deviation(current_ratio, current_ma)

        # 计算历史分位
        percentile = calculate_percentile(df[ratio_col], current_ratio, use_all_history)

        # 计算趋势
        changes = calculate_trend(df[ratio_col], trend_windows)
        trend = determine_trend(changes)

        # 存储结果
        analysis_results[target] = {
            'current_ratio': round(current_ratio, 4),
            'current_ma': round(current_ma, 4),
            'deviation': round(deviation, 2),
            'percentile': round(percentile, 1),
            'trend': trend,
            **changes
        }

        print(f"  当前比价: {current_ratio:.4f}")
        print(f"  {ma_window}日均线: {current_ma:.4f}")
        print(f"  偏离度: {deviation:+.2f}%")
        print(f"  历史分位: {percentile:.1f}%")
        print(f"  趋势: {trend}")

    # 保存处理后的数据
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, encoding='utf-8-sig')

    # 保存分析结果
    analysis_file = output_file.parent / 'analysis_results.json'
    with open(analysis_file, 'w', encoding='utf-8') as f:
        json.dump(analysis_results, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 处理后数据已保存: {output_file}")
    print(f"[OK] 分析结果已保存: {analysis_file}")

    return df, analysis_results


def main():
    parser = argparse.ArgumentParser(description='计算比价指标')
    parser.add_argument('--input', '-i',
                        default='data/raw_data.csv',
                        help='输入文件路径 (默认: data/raw_data.csv)')
    parser.add_argument('--output', '-o',
                        default='data/processed_data.csv',
                        help='输出文件路径 (默认: data/processed_data.csv)')

    args = parser.parse_args()

    # 切换到 skill 目录
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)

    process_data(args.input, args.output)


if __name__ == '__main__':
    main()
