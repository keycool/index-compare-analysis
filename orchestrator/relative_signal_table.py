#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Format relative index signals for ERP summary displays."""

from __future__ import annotations

import math
from typing import Any


ASSET_ORDER = {
    "hs300": 0,
    "sh50": 1,
    "val300": 2,
    "gro300": 3,
    "cyb": 4,
    "zz500": 5,
    "zz1000": 6,
    "kc50": 7,
    "hsi": 8,
    "hstech": 9,
}

ASSET_SOURCE_LABELS = {
    "hs300": ("A股 ERP + 核心锚", "分母资产不从比价表直接给建议，承接 A 股核心与剩余仓位"),
    "hsi": ("港股 ERP + 核心锚", "分母资产不从比价表直接给建议，承接港股核心仓位"),
    "gro300": ("300成长 / 300价值 分子", "分子标的，直接使用对分子建议"),
    "val300": ("300成长 / 300价值 反向", "300价值是该比价的分母，建议由成长/价值信号反向派生"),
    "sh50": ("上证50相关比价", "上证50有直接核心比价，也可能受特色比价分母侧影响；最终以执行层目标仓位为准"),
    "cyb": ("创业板相关比价", "创业板同时出现在沪深300锚和上证50锚中；最终以执行层目标仓位为准"),
    "zz500": ("中证500 / 沪深300 分子", "分子标的，直接使用对分子建议"),
    "zz1000": ("中证1000 / 沪深300 分子", "分子标的，直接使用对分子建议"),
    "kc50": ("科创50相关比价", "科创50同时出现在沪深300锚和上证50锚中；最终以执行层目标仓位为准"),
    "hstech": ("恒生科技 / 恒生指数 分子", "分子标的，直接使用对分子建议"),
}

RELATIVE_SIGNAL_ROWS = [
    ("中证500 / 沪深300", "zz500", "zz500_ratio", "zz500_percentile"),
    ("中证1000 / 沪深300", "zz1000", "zz1000_ratio", "zz1000_percentile"),
    ("创业板 / 沪深300", "cyb", "cyb_ratio", "cyb_percentile"),
    ("上证50 / 沪深300", "sh50_300", "sh50_300_ratio", "sh50_300_percentile"),
    ("科创50 / 沪深300", "kc50_300", "kc50_300_ratio", "kc50_300_percentile"),
    ("创业板 / 上证50", "cyb_sh50", "sh50_ratio", "sh50_percentile"),
    ("科创50 / 上证50", "kc50", "kc50_ratio", "kc50_percentile"),
    ("300成长 / 300价值", "gro300", "val300_ratio", "gro300_percentile"),
    ("恒生科技 / 恒生指数", "hstech", "hstech_ratio", "hstech_percentile"),
]


def is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def fmt_ratio(value: Any) -> str:
    return f"{float(value):.4f}" if is_finite_number(value) else "-"


def fmt_percentile(value: Any) -> str:
    return f"{float(value):.1f}%" if is_finite_number(value) else "-"


def fmt_weight(value: Any) -> str:
    return f"{float(value) * 100:.2f}%" if is_finite_number(value) else "-"


def fmt_amount(value: Any) -> str:
    return f"{float(value):,.0f}" if is_finite_number(value) else "-"


def action_text(action: str, delta_amount: Any, execution_mode: str = "rebalance") -> str:
    amount = fmt_amount(abs(float(delta_amount))) if is_finite_number(delta_amount) else "-"
    if execution_mode == "research":
        if action == "buy":
            return f"目标高于当前 {amount}"
        if action == "sell":
            return f"目标低于当前 {amount}"
        return "持平观察"
    if action == "buy":
        return f"加仓 {amount}"
    if action == "sell":
        return f"减仓 {amount}"
    return "保持"


def relative_signal_rows(relative: dict[str, Any]) -> list[dict[str, str]]:
    ratios = relative.get("ratios", {})
    percentiles = relative.get("percentiles", {})
    recommendations = relative.get("recommendations", {})
    rows: list[dict[str, str]] = []
    for label, rec_key, ratio_key, percentile_key in RELATIVE_SIGNAL_ROWS:
        rows.append(
            {
                "指标名称": label,
                "比价值": fmt_ratio(ratios.get(ratio_key)),
                "分位数": fmt_percentile(percentiles.get(percentile_key)),
                "对分子建议": str(recommendations.get(rec_key) or "-"),
            }
        )
    return rows


def markdown_relative_signal_table(relative: dict[str, Any]) -> list[str]:
    lines = [
        "| 指标名称 | 比价值 | 分位数 | 对分子建议 |",
        "|---|---:|---:|---|",
    ]
    for row in relative_signal_rows(relative):
        lines.append(
            f"| {row['指标名称']} | `{row['比价值']}` | `{row['分位数']}` | `{row['对分子建议']}` |"
        )
    return lines


def text_relative_signal_table(relative: dict[str, Any]) -> list[str]:
    lines = ["指标名称 | 比价值 | 分位数 | 对分子建议"]
    for row in relative_signal_rows(relative):
        lines.append(
            f"{row['指标名称']} | {row['比价值']} | {row['分位数']} | {row['对分子建议']}"
        )
    return lines


def asset_suggestion_rows(portfolio: dict[str, Any], execution_mode: str = "rebalance") -> list[dict[str, str]]:
    positions = sorted(
        portfolio.get("positions", []),
        key=lambda item: ASSET_ORDER.get(item.get("bucket", ""), 99),
    )
    rows: list[dict[str, str]] = []
    for item in positions:
        bucket = str(item.get("bucket", ""))
        source, note = ASSET_SOURCE_LABELS.get(bucket, ("执行计划", "以执行层目标仓位为准"))
        signal = str(item.get("signal") or "-")
        if signal == "core":
            signal = "核心"
        suggestion = (
            f"{signal}；目标 {fmt_weight(item.get('target_weight'))}，"
            f"{action_text(str(item.get('action', 'hold')), item.get('delta_amount', 0), execution_mode)}"
        )
        rows.append(
            {
                "标的": str(item.get("label") or bucket),
                "来源信号": source,
                "配置建议": suggestion,
                "说明": note,
            }
        )
    return rows


def markdown_asset_suggestion_table(portfolio: dict[str, Any], execution_mode: str = "rebalance") -> list[str]:
    lines = [
        "| 标的 | 来源信号 | 配置建议 | 说明 |",
        "|---|---|---|---|",
    ]
    for row in asset_suggestion_rows(portfolio, execution_mode):
        lines.append(
            f"| {row['标的']} | {row['来源信号']} | `{row['配置建议']}` | {row['说明']} |"
        )
    return lines


def text_asset_suggestion_table(portfolio: dict[str, Any], execution_mode: str = "rebalance") -> list[str]:
    lines = ["标的 | 来源信号 | 配置建议 | 说明"]
    for row in asset_suggestion_rows(portfolio, execution_mode):
        lines.append(
            f"{row['标的']} | {row['来源信号']} | {row['配置建议']} | {row['说明']}"
        )
    return lines
