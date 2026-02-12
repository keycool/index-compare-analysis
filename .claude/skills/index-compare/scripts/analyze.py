#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
智能分析模块
基于计算结果生成智能分析结论
"""

import os
import json
import argparse
from pathlib import Path


def load_config():
    """加载配置文件"""
    config_path = Path(__file__).parent.parent / 'config.json'
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_percentile_status(percentile, config):
    """
    获取分位状态描述

    Args:
        percentile: 分位数
        config: 配置

    Returns:
        tuple: (状态, 描述, 建议方向)
    """
    levels = config['percentile_levels']

    if percentile <= levels['extreme_low']:
        return ("极度低估",
                "当前比价处于历史极低区域，中小盘相对大盘极具性价比",
                "强烈超配", 2)
    elif percentile <= levels['low']:
        return ("低估",
                "当前比价处于历史低位区域，中小盘相对大盘有较好性价比",
                "超配", 1)
    elif percentile < levels['high']:
        return ("中性",
                "当前比价处于历史中位水平，大小盘估值相对均衡",
                "标配", 0)
    elif percentile < levels['extreme_high']:
        return ("高估",
                "当前比价处于历史高位区域，中小盘相对大盘偏贵",
                "减仓", -1)
    else:
        return ("极度高估",
                "当前比价处于历史极高区域，中小盘相对大盘非常昂贵",
                "不配置", -2)


def get_trend_status(trend):
    """
    获取趋势状态描述

    Args:
        trend: 趋势判定

    Returns:
        tuple: (描述, 得分)
    """
    trend_map = {
        "强上升": ("比价呈现强劲上升趋势，中小盘相对大盘持续走强", 2),
        "弱上升": ("比价小幅上升，中小盘相对大盘略有走强", 1),
        "震荡": ("比价处于震荡状态，大小盘相对强弱不明显", 0),
        "弱下降": ("比价小幅下降，中小盘相对大盘略有走弱", -1),
        "强下降": ("比价呈现明显下降趋势，中小盘相对大盘持续走弱", -2),
    }
    return trend_map.get(trend, ("趋势不明", 0))


def get_deviation_status(deviation):
    """
    获取偏离度状态描述

    Args:
        deviation: 偏离度百分比

    Returns:
        tuple: (状态, 描述, 得分)
    """
    if deviation > 10:
        return ("严重超买", "大幅偏离均线上方，短期回调风险较高", -2)
    elif deviation > 5:
        return ("超买", "偏离均线上方，需警惕可能的短期回调", -1)
    elif deviation > -5:
        return ("正常", "在均线附近波动，属于正常状态", 0)
    elif deviation > -10:
        return ("超卖", "偏离均线下方，可能迎来短期反弹", 1)
    else:
        return ("严重超卖", "大幅偏离均线下方，反弹概率较高", 2)


def calculate_recommendation_score(percentile_score, trend_score, deviation_score, percentile_value):
    """
    计算综合建议得分

    Args:
        percentile_score: 分位得分
        trend_score: 趋势得分
        deviation_score: 偏离度得分
        percentile_value: 分位数值（用于调整趋势方向）

    Returns:
        float: 综合得分
    """
    # 根据分位情况调整趋势得分的方向
    # 高估区域（>60%）：趋势上升是追高风险，应取反
    # 低估区域（<40%）：趋势下降是继续下跌风险，保持原方向
    # 中性区域：趋势正常计算

    adjusted_trend_score = trend_score
    if percentile_value > 60:
        # 高估时，趋势上升是负面的（追高风险），趋势下降是正面的（回归均值）
        adjusted_trend_score = -trend_score
    elif percentile_value < 40:
        # 低估时，趋势正常：上升是正面的（开始反弹），下降是负面的
        adjusted_trend_score = trend_score
    # 中性区域保持原趋势得分

    # 权重调整：分位60%，趋势25%，偏离度15%
    return percentile_score * 0.6 + adjusted_trend_score * 0.25 + deviation_score * 0.15


def get_recommendation(score):
    """
    根据得分获取建议

    Args:
        score: 综合得分

    Returns:
        tuple: (建议, 图标)
    """
    if score > 1.0:
        return ("强烈超配", "[++]")
    elif score > 0.5:
        return ("超配", "[+]")
    elif score > -0.5:
        return ("标配", "[=]")
    elif score > -1.0:
        return ("低配", "[-]")
    else:
        return ("强烈低配", "[--]")


def generate_analysis(analysis_results):
    """
    生成智能分析结论

    Args:
        analysis_results: 计算结果字典

    Returns:
        dict: 分析结论
    """
    config = load_config()
    conclusions = {}

    index_names = {
        'ZZ500': '中证500',
        'ZZ1000': '中证1000',
        'ZZA500': '中证A500'
    }

    for index_code, data in analysis_results.items():
        index_name = index_names.get(index_code, index_code)

        # 获取各维度分析
        percentile = data['percentile']
        trend = data['trend']
        deviation = data['deviation']

        # 分位分析
        p_status, p_desc, p_suggest, p_score = get_percentile_status(percentile, config)

        # 趋势分析
        t_desc, t_score = get_trend_status(trend)

        # 偏离度分析
        d_status, d_desc, d_score = get_deviation_status(deviation)

        # 计算综合建议（传入分位值用于调整趋势方向）
        total_score = calculate_recommendation_score(p_score, t_score, d_score, percentile)
        recommendation, rec_icon = get_recommendation(total_score)

        # 构建结论
        conclusions[index_code] = {
            'name': index_name,
            'current_ratio': data['current_ratio'],
            'percentile': {
                'value': percentile,
                'status': p_status,
                'description': p_desc,
                'score': p_score
            },
            'trend': {
                'status': trend,
                'description': t_desc,
                'score': t_score,
                'changes': {
                    '5d': data.get('change_5d'),
                    '10d': data.get('change_10d'),
                    '20d': data.get('change_20d')
                }
            },
            'deviation': {
                'value': deviation,
                'status': d_status,
                'description': d_desc,
                'score': d_score
            },
            'recommendation': {
                'action': recommendation,
                'icon': rec_icon,
                'score': round(total_score, 2),
                'reasons': [
                    f"历史分位 {percentile:.1f}%，{p_status}",
                    f"近期趋势：{trend}",
                    f"均线偏离 {deviation:+.2f}%，{d_status}"
                ]
            },
            'summary': generate_summary(index_name, percentile, p_status, trend,
                                       deviation, d_status, recommendation, rec_icon)
        }

    return conclusions


def generate_summary(name, percentile, p_status, trend, deviation, d_status, recommendation, icon):
    """
    生成文字摘要

    Args:
        各分析参数

    Returns:
        str: 摘要文字
    """
    summary = f"""【{name}】分析结论：

1. 历史分位：{percentile:.1f}%（{p_status}）
   当前{name}相对沪深300的比价处于历史{p_status}区域。

2. 趋势判断：{trend}
   近期比价走势呈现{trend}态势。

3. 均值回归：偏离度 {deviation:+.2f}%（{d_status}）
   当前比价{"高于" if deviation > 0 else "低于"}30日均线{abs(deviation):.2f}%。

4. 配置建议：{icon} {recommendation}
   综合以上分析，建议对{name}采取【{recommendation}】策略。"""

    return summary


def analyze(input_path, output_path):
    """
    执行智能分析

    Args:
        input_path: 分析结果JSON文件路径
        output_path: 输出文件路径
    """
    print("=" * 50)
    print("       智能分析")
    print("=" * 50)

    # 读取分析结果
    print(f"\n读取分析结果: {input_path}")
    with open(input_path, 'r', encoding='utf-8-sig') as f:
        analysis_results = json.load(f)

    # 生成分析结论
    print("\n生成智能分析结论...")
    conclusions = generate_analysis(analysis_results)

    # 输出结论
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(conclusions, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 分析结论已保存: {output_file}")

    # 打印摘要
    print("\n" + "=" * 50)
    print("       分析摘要")
    print("=" * 50)

    for index_code, data in conclusions.items():
        print(f"\n{data['summary']}")
        print("-" * 40)

    return conclusions


def main():
    parser = argparse.ArgumentParser(description='生成智能分析结论')
    parser.add_argument('--input', '-i',
                        default='data/analysis_results.json',
                        help='输入文件路径 (默认: data/analysis_results.json)')
    parser.add_argument('--output', '-o',
                        default='data/conclusions.json',
                        help='输出文件路径 (默认: data/conclusions.json)')

    args = parser.parse_args()

    # 切换到 skill 目录
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)

    analyze(args.input, args.output)


if __name__ == '__main__':
    main()
