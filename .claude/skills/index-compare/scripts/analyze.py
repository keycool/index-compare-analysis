#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Analyze ratio signals and generate conclusions.
"""

import argparse
import json
import os
from pathlib import Path


def load_config():
    config_path = Path(__file__).parent.parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_percentile_status(percentile, config):
    levels = config["percentile_levels"]
    if percentile <= levels["extreme_low"]:
        return (
            "极度低估",
            "当前比价处于历史极低区间，相对配置价值突出。",
            "强烈超配",
            2,
        )
    if percentile <= levels["low"]:
        return (
            "低估",
            "当前比价处于历史低位区间，具备较好的相对性价比。",
            "超配",
            1,
        )
    if percentile < levels["high"]:
        return (
            "中性",
            "当前比价处于历史中位附近，估值相对均衡。",
            "标配",
            0,
        )
    if percentile < levels["extreme_high"]:
        return (
            "高估",
            "当前比价处于历史高位区间，短期继续追高的性价比偏弱。",
            "低配",
            -1,
        )
    return (
        "极度高估",
        "当前比价处于历史极高区间，需要警惕估值回归风险。",
        "不配置",
        -2,
    )


def get_trend_status(trend):
    trend_map = {
        "强上升": ("比价呈现强劲上升趋势，相对强势仍在延续。", 2),
        "弱上升": ("比价温和上升，边际上略有走强。", 1),
        "震荡": ("比价处于震荡区间，方向性不强。", 0),
        "弱下降": ("比价温和回落，边际上略有走弱。", -1),
        "强下降": ("比价明显回落，短线仍在走弱。", -2),
    }
    return trend_map.get(trend, ("趋势不明", 0))


def get_deviation_status(deviation, zscore):
    if zscore >= 2.0:
        return ("严重超买", "短期明显偏离均值，回调风险较高。", -2)
    if zscore >= 1.0:
        return ("超买", "估值有一定透支迹象，注意波动风险。", -1)
    if zscore <= -2.0:
        return ("严重超卖", "估值压缩较充分，存在修复机会。", 2)
    if zscore <= -1.0:
        return ("超卖", "已进入偏低区间，具备阶段性修复空间。", 1)
    return ("正常", "仍处于常态波动区间，均值回归信号不强。", 0)


def calculate_recommendation_score(
    percentile_score, trend_score, deviation_score, percentile_value
):
    adjusted_trend_score = trend_score
    if percentile_value > 60:
        adjusted_trend_score = -trend_score
    elif percentile_value < 40:
        adjusted_trend_score = trend_score
    return percentile_score * 0.6 + adjusted_trend_score * 0.25 + deviation_score * 0.15


def get_recommendation(score):
    if score > 1.0:
        return ("强烈超配", "[++]")
    if score > 0.5:
        return ("超配", "[+]")
    if score > -0.5:
        return ("标配", "[=]")
    if score > -1.0:
        return ("低配", "[-]")
    return ("强烈低配", "[--]")


def get_index_names():
    return {
        "ZZ500": "中证500",
        "ZZ1000": "中证1000",
        "ZZA500": "创业板指数",
        "SH50_300": "上证50指数",
        "KC50_300": "科创50指数",
        "SH50": "创业板/上证50",
        "KC50": "科创50/上证50",
        "VAL300": "300成长/价值",
        "HKTECH": "恒生科技指数",
    }


def get_benchmark_name(index_code):
    benchmark_map = {
        "SH50": "上证50指数",
        "KC50": "科创50指数",
        "VAL300": "300价值指数",
        "HKTECH": "恒生指数",
    }
    return benchmark_map.get(index_code, "沪深300")


def generate_analysis(analysis_results):
    config = load_config()
    conclusions = {}
    index_names = get_index_names()

    for index_code, data in analysis_results.items():
        index_name = index_names.get(index_code, index_code)
        percentile = data["percentile"]
        trend = data["trend"]
        deviation = data["deviation"]
        zscore = data.get("zscore", 0)

        p_status, p_desc, _, p_score = get_percentile_status(percentile, config)
        t_desc, t_score = get_trend_status(trend)
        d_status, d_desc, d_score = get_deviation_status(deviation, zscore)
        total_score = calculate_recommendation_score(
            p_score, t_score, d_score, percentile
        )
        recommendation, rec_icon = get_recommendation(total_score)

        conclusions[index_code] = {
            "name": index_name,
            "current_ratio": data["current_ratio"],
            "percentile": {
                "value": percentile,
                "status": p_status,
                "description": p_desc,
                "score": p_score,
            },
            "trend": {
                "status": trend,
                "description": t_desc,
                "score": t_score,
                "changes": {
                    "5d": data.get("change_5d"),
                    "10d": data.get("change_10d"),
                    "20d": data.get("change_20d"),
                },
            },
            "deviation": {
                "value": deviation,
                "zscore": zscore,
                "status": d_status,
                "description": d_desc,
                "score": d_score,
            },
            "recommendation": {
                "action": recommendation,
                "icon": rec_icon,
                "score": round(total_score, 2),
                "reasons": [
                    f"历史分位 {percentile:.1f}%：{p_status}",
                    f"近期趋势：{trend}",
                    f"均线偏离 {deviation:+.2f}% / {zscore:+.2f}σ：{d_status}",
                ],
            },
            "summary": generate_summary(
                index_code,
                index_name,
                percentile,
                p_status,
                trend,
                deviation,
                zscore,
                d_status,
                recommendation,
                rec_icon,
            ),
        }

    return conclusions


def generate_summary(
    index_code,
    name,
    percentile,
    p_status,
    trend,
    deviation,
    zscore,
    d_status,
    recommendation,
    icon,
):
    benchmark_name = get_benchmark_name(index_code)
    relative_position = "高于" if deviation > 0 else "低于"

    return f"""《{name}》分析结论：

1. 历史分位：{percentile:.1f}%（{p_status}）
   当前{name}相对{benchmark_name}的比价处于历史{p_status}区间。

2. 趋势判断：{trend}
   近期比价走势呈现{trend}状态。

3. 均值回归：偏离度 {deviation:+.2f}% / {zscore:+.2f}σ（{d_status}）
   当前比价{relative_position}30日均线 {abs(deviation):.2f}%，相对波动位置为 {zscore:+.2f}σ。

4. 配置建议：{icon} {recommendation}
   综合以上分析，建议对{name}采取《{recommendation}》策略。"""


def analyze(input_path, output_path):
    print("=" * 50)
    print("智能分析".center(50))
    print("=" * 50)
    print(f"\n读取分析结果: {input_path}")

    with open(input_path, "r", encoding="utf-8-sig") as f:
        analysis_results = json.load(f)

    print("\n生成智能分析结论...")
    conclusions = generate_analysis(analysis_results)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(conclusions, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 分析结论已保存: {output_file}")
    print("\n" + "=" * 50)
    print("分析摘要".center(50))
    print("=" * 50)
    for _, data in conclusions.items():
        print(f"\n{data['summary']}")
        print("-" * 40)

    return conclusions


def main():
    parser = argparse.ArgumentParser(description="generate conclusions")
    parser.add_argument("--input", "-i", default="data/analysis_results.json")
    parser.add_argument("--output", "-o", default="data/conclusions.json")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)
    analyze(args.input, args.output)


if __name__ == "__main__":
    main()
