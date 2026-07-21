#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Format relative index signals for ERP summary displays."""

from __future__ import annotations

import math
from typing import Any


RELATIVE_SIGNAL_ROWS = [
    ("中证500 / 沪深300", "zz500", "zz500_ratio", "zz500_percentile"),
    ("中证1000 / 沪深300", "zz1000", "zz1000_ratio", "zz1000_percentile"),
    ("创业板 / 沪深300", "cyb", "cyb_ratio", "cyb_percentile"),
    ("上证50 / 沪深300", "sh50_300", "sh50_300_ratio", "sh50_300_percentile"),
    ("科创50 / 沪深300", "kc50_300", "kc50_300_ratio", "kc50_300_percentile"),
    ("创业板 / 上证50", "cyb_sh50", "sh50_ratio", "sh50_percentile"),
    ("科创50 / 上证50", "kc50", "kc50_ratio", "kc50_percentile"),
    ("300价值 / 300成长", "val300", "val300_ratio", "val300_percentile"),
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
                "配置建议": str(recommendations.get(rec_key) or "-"),
            }
        )
    return rows


def markdown_relative_signal_table(relative: dict[str, Any]) -> list[str]:
    lines = [
        "| 指标名称 | 比价值 | 分位数 | 配置建议 |",
        "|---|---:|---:|---|",
    ]
    for row in relative_signal_rows(relative):
        lines.append(
            f"| {row['指标名称']} | `{row['比价值']}` | `{row['分位数']}` | `{row['配置建议']}` |"
        )
    return lines


def text_relative_signal_table(relative: dict[str, Any]) -> list[str]:
    lines = ["指标名称 | 比价值 | 分位数 | 配置建议"]
    for row in relative_signal_rows(relative):
        lines.append(
            f"{row['指标名称']} | {row['比价值']} | {row['分位数']} | {row['配置建议']}"
        )
    return lines
