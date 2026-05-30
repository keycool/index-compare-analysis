#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Render a human-readable ERP daily summary from the latest execution plan.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
PLAN_PATH = ROOT / "output" / "erp_execution_plan.json"
CONFIG_PATH = ROOT / "erp_execution_config.json"
OUTPUT_PATH = ROOT / "output" / "erp_daily_summary.md"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
BUCKET_ORDER = {
    "hs300": 0,
    "sh50": 1,
    "cyb": 2,
    "zz500": 3,
    "zz1000": 4,
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float, digits: int = 2) -> str:
    return f"{value * 100:.{digits}f}%"


def num(value: float) -> str:
    return f"{value:,.2f}"


def action_text(action: str, delta: float) -> str:
    if action == "buy":
        return f"加仓 {num(abs(delta))}"
    if action == "sell":
        return f"减仓 {num(abs(delta))}"
    return "保持不动"


def reentry_text(item: dict) -> str | None:
    if not item.get("reentry_blocked"):
        return None
    percentile = item.get("current_percentile")
    threshold = item.get("reentry_threshold")
    if percentile is None or threshold is None:
        return "标配，但重入闸门未开启，暂不回补"
    return f"标配，但当前分位 {percentile:.2f}% 高于重入阈值 {threshold:.2f}%，暂不回补"


def ordered_positions(positions: list[dict]) -> list[dict]:
    return sorted(positions, key=lambda item: BUCKET_ORDER.get(item.get("bucket", ""), 99))


def main() -> None:
    plan = load_json(PLAN_PATH)
    config = load_json(CONFIG_PATH)

    erp = plan["signals"]["erp"]
    relative = plan["signals"]["relative"]
    val300 = plan["signals"].get("val300_style", {})
    portfolio = plan["portfolio"]
    positions = ordered_positions(portfolio["positions"])

    lines: list[str] = []
    lines.append("# ERP 日报摘要")
    lines.append("")
    lines.append(f"生成时间: {datetime.now(SHANGHAI_TZ).isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## 今日结论")
    lines.append("")
    lines.append(
        f"- ERP 最新日期 `{erp['date']}`，股权溢价 `{erp['equity_premium']:.2f}`，历史分位 `{erp['percentile']:.2f}%`。"
    )
    lines.append(
        f"- 当前总体倾向 `进攻 {pct(erp['aggressive_weight'])} / 防守 {pct(erp['defensive_weight'])}`。"
    )
    lines.append(
        f"- Relative 最新日期 `{relative['date']}`，`500={relative['recommendations']['zz500'] or '标配'}`，"
        f"`1000={relative['recommendations']['zz1000'] or '标配'}`，"
        f"`创业板={relative['recommendations']['cyb'] or '标配'}`，"
        f"`50={relative['recommendations']['sh50'] or '标配'}`。"
    )
    if val300.get("available"):
        lines.append(
            f"- `300价值/成长` 最新日期 `{val300['date']}`，比价 `{val300['ratio']:.4f}`，"
            f"分位 `{val300['percentile']:.2f}%`，建议 `{val300['recommendation']}`。"
        )
    lines.append("")
    lines.append("## 调仓建议")
    lines.append("")
    for item in positions:
        line = (
            f"- `{item['label']}`：当前 `{num(item['current_amount'])}`，目标 `{num(item['target_amount'])}`，"
            f"建议 `{action_text(item['action'], item['delta_amount'])}`。"
        )
        extra = reentry_text(item)
        if extra:
            line += f" `{extra}`。"
        lines.append(line)
    lines.append("")
    lines.append("## 组合结构")
    lines.append("")
    lines.append(f"- 可管理 ERP 资金：`{num(portfolio['managed_amount'])}`")
    lines.append(f"- 未映射资金：`{num(portfolio['unmapped_amount'])}`")
    lines.append(f"- 可管理持仓数：`{portfolio['managed_position_count']}`")
    if portfolio["unmapped_holdings"]:
        lines.append("- 未映射标的：")
        for item in portfolio["unmapped_holdings"]:
            lines.append(f"  - `{item['name']}` `{num(item['amount'])}`")
    lines.append("")
    lines.append("## 当前参数")
    lines.append("")
    thresholds = config["percentile_thresholds"]
    aggressive_weights = config["aggressive_weights"]
    reentry_thresholds = config.get("aggressive_reentry_percentiles", {})
    lines.append(f"- ERP 分位阈值：`low={thresholds['low']}` / `high={thresholds['high']}`")
    lines.append(
        f"- 进攻权重锚点：`low={pct(aggressive_weights['low'])}` / "
        f"`neutral={pct(aggressive_weights['neutral'])}` / `high={pct(aggressive_weights['high'])}`"
    )
    if reentry_thresholds:
        lines.append(
            f"- 高分位重入闸门：`500<{reentry_thresholds.get('zz500', '-')}%` / "
            f"`1000<{reentry_thresholds.get('zz1000', '-')}%` / "
            f"`创业板<{reentry_thresholds.get('cyb', '-')}%`"
        )
    lines.append("- 建议乘数与风格微调详见配置文件和说明文档。")
    lines.append("")
    lines.append("## 参考文件")
    lines.append("")
    lines.append(f"- 执行计划：`{PLAN_PATH}`")
    lines.append(f"- 执行配置：`{CONFIG_PATH}`")
    lines.append(f"- 配置说明：`{ROOT / 'erp_execution_config.md'}`")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
