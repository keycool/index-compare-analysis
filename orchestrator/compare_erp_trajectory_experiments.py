#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Compare lightweight trajectory overlays for ERP execution.

Scheme A:
- Keep the current ERP/re-entry framework
- Use 30-day deviation and 5-day ratio change as a pacing multiplier

Scheme B:
- Keep the current ERP/re-entry framework
- Use staged recovery when a bucket is allowed to re-enter
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_PLAN_PATH = ROOT / "output" / "erp_execution_plan.json"
DEFAULT_CONCLUSIONS_PATH = (
    ROOT.parent / ".claude" / "skills" / "index-compare" / "data" / "conclusions.json"
)
DEFAULT_MARKDOWN_PATH = ROOT / "output" / "erp_trajectory_experiment_comparison.md"
DEFAULT_JSON_PATH = ROOT / "output" / "erp_trajectory_experiment_comparison.json"

BUCKET_ORDER = ["hs300", "sh50", "cyb", "zz500", "zz1000"]
CODE_MAP = {
    "zz500": "ZZ500",
    "zz1000": "ZZ1000",
    "cyb": "ZZA500",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare ERP trajectory overlays")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN_PATH))
    parser.add_argument("--conclusions", default=str(DEFAULT_CONCLUSIONS_PATH))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_PATH))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_PATH))
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def num(value: float) -> str:
    return f"{value:,.2f}"


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def ordered_positions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    positions = {item["bucket"]: item for item in plan["portfolio"]["positions"]}
    return [positions[bucket] for bucket in BUCKET_ORDER if bucket in positions]


def trajectory_metrics(conclusions: dict[str, Any], bucket: str) -> dict[str, Any]:
    code = CODE_MAP.get(bucket)
    if not code:
        return {"available": False}
    data = conclusions.get(code, {})
    return {
        "available": True,
        "deviation": float(data.get("deviation", {}).get("value", 0.0)),
        "change_5d": float(data.get("trend", {}).get("changes", {}).get("5d", 0.0)),
        "percentile": float(data.get("percentile", {}).get("value", 0.0)),
        "trend": data.get("trend", {}).get("status", ""),
    }


def scheme_a_multiplier(metrics: dict[str, Any]) -> tuple[float, str]:
    deviation = metrics["deviation"]
    change_5d = metrics["change_5d"]

    if deviation >= 4 or change_5d >= 3:
        return 0.60, "轨迹过热，恢复比例打 0.60"
    if deviation >= 2 or change_5d >= 1:
        return 0.80, "仍在高位或冲高，恢复比例打 0.80"
    if deviation <= -3 and change_5d > 0:
        return 1.15, "深度偏离后开始修复，恢复比例放大到 1.15"
    if deviation <= -1 and change_5d > 0:
        return 1.05, "低位修复确认，恢复比例放大到 1.05"
    if deviation < 0 and change_5d < 0:
        return 0.85, "仍在下滑途中，恢复比例打 0.85"
    return 1.00, "轨迹中性，不额外修正"


def scheme_b_restore_ratio(item: dict[str, Any]) -> tuple[float, str]:
    percentile = item.get("current_percentile")
    threshold = item.get("reentry_threshold")
    if percentile is None or threshold is None:
        return 1.00, "无重入阈值，维持原目标"
    if percentile > threshold:
        return 0.00, f"仍高于重入阈值 {threshold:.1f}%，不恢复"
    if percentile > threshold * 0.75:
        return 0.30, "刚进入可重入区，仅恢复 30%"
    if percentile > threshold * 0.50:
        return 0.60, "进入中段恢复区，恢复 60%"
    return 1.00, "已进入低位恢复区，恢复 100%"


def compare(plan: dict[str, Any], conclusions: dict[str, Any]) -> dict[str, Any]:
    managed_amount = float(plan["portfolio"]["managed_amount"])
    rows: list[dict[str, Any]] = []

    for item in ordered_positions(plan):
        row: dict[str, Any] = {
            "bucket": item["bucket"],
            "label": item["label"],
            "baseline_target_weight": float(item["target_weight"]),
            "baseline_target_amount": float(item["target_amount"]),
            "signal": item.get("signal"),
            "reentry_blocked": bool(item.get("reentry_blocked", False)),
            "current_percentile": item.get("current_percentile"),
            "reentry_threshold": item.get("reentry_threshold"),
        }

        if item["bucket"] not in CODE_MAP:
            row["scheme_a_weight"] = row["baseline_target_weight"]
            row["scheme_a_amount"] = row["baseline_target_amount"]
            row["scheme_a_reason"] = "非进攻重入桶，维持原目标"
            row["scheme_b_weight"] = row["baseline_target_weight"]
            row["scheme_b_amount"] = row["baseline_target_amount"]
            row["scheme_b_reason"] = "非进攻重入桶，维持原目标"
            rows.append(row)
            continue

        if row["reentry_blocked"]:
            row["scheme_a_weight"] = 0.0
            row["scheme_a_amount"] = 0.0
            row["scheme_a_reason"] = "仍被重入闸门拦截，维持 0%"
            row["scheme_b_weight"] = 0.0
            row["scheme_b_amount"] = 0.0
            row["scheme_b_reason"] = "仍被重入闸门拦截，维持 0%"
            row["trajectory"] = trajectory_metrics(conclusions, item["bucket"])
            rows.append(row)
            continue

        metrics = trajectory_metrics(conclusions, item["bucket"])
        mult_a, reason_a = scheme_a_multiplier(metrics)
        ratio_b, reason_b = scheme_b_restore_ratio(item)

        weight_a = float(item["target_weight"]) * mult_a
        weight_b = float(item["target_weight"]) * ratio_b
        row["trajectory"] = metrics
        row["scheme_a_weight"] = round(weight_a, 4)
        row["scheme_a_amount"] = round(weight_a * managed_amount, 2)
        row["scheme_a_reason"] = reason_a
        row["scheme_b_weight"] = round(weight_b, 4)
        row["scheme_b_amount"] = round(weight_b * managed_amount, 2)
        row["scheme_b_reason"] = reason_b
        rows.append(row)

    return {
        "generated_from": {
            "plan_date": plan["signals"]["relative"]["date"],
            "managed_amount": managed_amount,
        },
        "rows": rows,
    }


def render_markdown(comparison: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# ERP 轨迹实验对比")
    lines.append("")
    lines.append(f"- Relative 日期：`{comparison['generated_from']['plan_date']}`")
    lines.append(f"- 可管理资金：`{num(comparison['generated_from']['managed_amount'])}`")
    lines.append("")
    lines.append("## A 方案")
    lines.append("")
    lines.append("- 在现有 ERP + 分位 + 重入闸门基础上，再用 `30日偏离 + 5日变化` 做恢复速度修正。")
    lines.append("- 更像“先决定能不能进，再决定进多快”。")
    lines.append("")
    lines.append("## B 方案")
    lines.append("")
    lines.append("- 在现有 ERP + 分位 + 重入闸门基础上，用分位分段决定恢复比例。")
    lines.append("- 更像“重入后分层恢复”，解释性更强。")
    lines.append("")
    lines.append("## 对比结果")
    lines.append("")
    for row in comparison["rows"]:
        lines.append(f"### {row['label']}")
        lines.append("")
        lines.append(
            f"- 基线目标：`{pct(row['baseline_target_weight'])}` / `{num(row['baseline_target_amount'])}`"
        )
        lines.append(
            f"- A 方案：`{pct(row['scheme_a_weight'])}` / `{num(row['scheme_a_amount'])}`"
            f"；{row['scheme_a_reason']}"
        )
        lines.append(
            f"- B 方案：`{pct(row['scheme_b_weight'])}` / `{num(row['scheme_b_amount'])}`"
            f"；{row['scheme_b_reason']}"
        )
        if row.get("trajectory", {}).get("available"):
            metrics = row["trajectory"]
            lines.append(
                f"- 轨迹指标：`30日偏离 {metrics['deviation']:+.2f}%` / "
                f"`5日变化 {metrics['change_5d']:+.2f}%` / "
                f"`分位 {metrics['percentile']:.1f}%` / `{metrics['trend']}`"
            )
        if row.get("reentry_blocked"):
            lines.append(
                f"- 当前仍被重入闸门拦截：`分位 {row['current_percentile']:.1f}% > 阈值 {row['reentry_threshold']:.1f}%`"
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    args = parse_args()
    plan = load_json(Path(args.plan))
    conclusions = load_json(Path(args.conclusions))
    comparison = compare(plan, conclusions)

    markdown = render_markdown(comparison)
    markdown_path = Path(args.markdown_output)
    json_path = Path(args.json_output)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")

    print(markdown_path)
    print(json_path)


if __name__ == "__main__":
    main()
