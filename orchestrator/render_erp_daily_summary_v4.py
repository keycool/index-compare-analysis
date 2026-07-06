#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Render a human-readable ERP daily summary from the latest execution plan — v3 expanded.
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
    "hs300": 0, "sh50": 1, "val300": 2, "gro300": 3,
    "cyb": 4, "zz500": 5, "zz1000": 6, "kc50": 7,
    "hsi": 8, "hstech": 9,
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


def forced_exit_text(item: dict) -> str | None:
    if not item.get("forced_exit"):
        return None
    percentile = item.get("current_percentile")
    threshold = item.get("forced_exit_threshold")
    if percentile is None or threshold is None:
        return "已达到强制退出条件，目标仓位归零"
    return f"当前分位 {percentile:.2f}% 已达强制退出阈值 {threshold:.2f}%，目标仓位归零"


def reentry_text(item: dict) -> str | None:
    if not item.get("reentry_blocked"):
        return None
    percentile = item.get("current_percentile")
    threshold = item.get("reentry_threshold")
    if percentile is None or threshold is None:
        return "重入闸门未开启，暂不回补"
    return f"当前分位 {percentile:.2f}% 高于重入阈值 {threshold:.2f}%，暂不回补"


def trajectory_text(item: dict) -> str | None:
    multiplier = item.get("trajectory_multiplier")
    reason = item.get("trajectory_reason")
    if multiplier is None or reason in (None, "", "trajectory neutral", "trajectory metrics unavailable", "trajectory overlay disabled"):
        return None
    deviation = item.get("current_deviation")
    change_5d = item.get("change_5d")
    reason_map = {
        "trajectory hot": "轨迹过热",
        "trajectory warm": "轨迹偏热",
        "trajectory repair strong": "低位强修复",
        "trajectory repair light": "低位轻修复",
        "trajectory falling": "仍在下滑途中",
    }
    label = reason_map.get(reason, reason)
    if deviation is None or change_5d is None:
        return f"{label}，仓位乘数 {multiplier:.2f}"
    return f"{label}，30日偏离 {deviation:+.2f}%，5日变化 {change_5d:+.2f}%，仓位乘数 {multiplier:.2f}"


def ordered_positions(positions: list[dict]) -> list[dict]:
    return sorted(positions, key=lambda item: BUCKET_ORDER.get(item.get("bucket", ""), 99))


def main() -> None:
    plan = load_json(PLAN_PATH)
    config = load_json(CONFIG_PATH)

    erp = plan["signals"]["erp"]
    hsi = plan["signals"].get("hsi_erp", {})
    relative = plan["signals"]["relative"]
    portfolio = plan["portfolio"]
    positions = ordered_positions(portfolio["positions"])

    lines: list[str] = []
    lines.append("# ERP 日报摘要 v3")
    lines.append("")
    lines.append(f"生成时间: {datetime.now(SHANGHAI_TZ).isoformat(timespec='seconds')}")
    lines.append("")

    # ── 今日信号 ──
    lines.append("## 今日信号")
    lines.append("")
    lines.append(f"- **A股 ERP** (`{erp['date']}`)：股权溢价 `{erp['equity_premium']:.2f}`，历史分位 `{erp['percentile']:.2f}%`。")
    lines.append(f"  → 进攻 `{pct(erp['aggressive_weight'])}` / 防守 `{pct(erp['defensive_weight'])}`。")

    if hsi.get("available"):
        lines.append(f"- **港股 ERP** (`{hsi['date']}`)：股权溢价 `{hsi['equity_premium']:.2f}`，历史分位 `{hsi['percentile']:.2f}%`。")
        lines.append(f"  → 进攻 `{pct(hsi['aggressive_weight'])}` / 防守 `{pct(hsi['defensive_weight'])}`。")
    else:
        lines.append(f"- **港股 ERP**：数据不可用（{hsi.get('message', 'fallback neutral')}），使用中性配置。")

    pool_ashare = portfolio.get("ashare_pool", 0)
    pool_hk = portfolio.get("hkshare_pool", 0)
    lines.append(f"- **资金分配**：A股 `{pct(pool_ashare)}` / 港股 `{pct(pool_hk)}`。")
    lines.append("")

    # ── 比价建议 ──
    lines.append("## 比价建议")
    lines.append("")
    recs = relative["recommendations"]
    lines.append(f"- `{relative['date']}`")
    lines.append(f"  - 中证500：`{recs.get('zz500','标配')}` | 中证1000：`{recs.get('zz1000','标配')}`")
    lines.append(f"  - 创业板：`{recs.get('cyb','标配')}` | 上证50：`{recs.get('sh50','标配')}` | 科创50：`{recs.get('kc50','标配')}`")
    lines.append(f"  - 300价值：`{recs.get('val300','标配')}` | 300成长：`{recs.get('gro300','标配')}`")
    lines.append(f"  - 恒生科技：`{recs.get('hstech','标配')}`")
    lines.append("")

    # ── 调仓建议 ──
    lines.append("## 调仓建议")
    lines.append("")

    # Group by pool
    for pool_name, pool_label in [("ashare", "A股"), ("hkshare", "港股")]:
        pool_positions = [p for p in positions if p.get("pool") == pool_name]
        if not pool_positions:
            continue
        lines.append(f"### {pool_label}")
        lines.append("")
        for item in pool_positions:
            sleeve_tag = "🛡" if item.get("sleeve") == "defensive" else "⚔"
            line = (
                f"- {sleeve_tag} `{item['label']}`：当前 `{num(item['current_amount'])}`，"
                f"目标 `{num(item['target_amount'])}`，"
                f"建议 `{action_text(item['action'], item['delta_amount'])}`。"
            )
            fe = forced_exit_text(item)
            re = reentry_text(item)
            tr = trajectory_text(item)
            tags = []
            if fe:
                tags.append(f"⚠ {fe}")
            if re:
                tags.append(f"🚫 {re}")
            if tr:
                tags.append(f"📊 {tr}")
            if tags:
                line += " " + " | ".join(tags)
            lines.append(line)
            if item.get("holding_breakdown"):
                details = " / ".join(f"{d['name']} {num(d['amount'])}" for d in item["holding_breakdown"])
                lines.append(f"  - 持仓明细：{details}")
        lines.append("")

    # ── 组合结构 ──
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
    forced_exit_thresholds = config.get("forced_exit_percentiles", {})
    reentry_thresholds = config.get("aggressive_reentry_percentiles", {})
    lines.append(f"- ERP 分位阈值：`low={thresholds['low']}` / `high={thresholds['high']}`")
    lines.append(f"- 进攻权重：`low={pct(aggressive_weights['low'])}` / `neutral={pct(aggressive_weights['neutral'])}` / `high={pct(aggressive_weights['high'])}`")
    lines.append(f"- 港股上限：`{pct(config.get('cross_market', {}).get('hk_pool_cap', 0.20))}`")
    if forced_exit_thresholds:
        lines.append(f"- 强制退出阈值：`50>={forced_exit_thresholds.get('sh50','-')}` / `500>={forced_exit_thresholds.get('zz500','-')}` / `1000>={forced_exit_thresholds.get('zz1000','-')}` / `创业板>={forced_exit_thresholds.get('cyb','-')}` / `科创50>={forced_exit_thresholds.get('kc50','-')}`")
    if reentry_thresholds:
        lines.append(f"- 重入闸门：`500<{reentry_thresholds.get('zz500','-')}` / `1000<{reentry_thresholds.get('zz1000','-')}` / `创业板<{reentry_thresholds.get('cyb','-')}` / `科创50<{reentry_thresholds.get('kc50','-')}`")

    lines.append("")
    lines.append("## 参考文件")
    lines.append("")
    lines.append(f"- 执行计划：`{PLAN_PATH}`")
    lines.append(f"- 执行配置：`{CONFIG_PATH}`")
    lines.append(f"- 扩展方案：`docs/strategy-expansion-v3.md`")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
