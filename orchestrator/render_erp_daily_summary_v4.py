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

from relative_signal_table import markdown_asset_suggestion_table, markdown_relative_signal_table


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


def is_research_mode(plan: dict) -> bool:
    return plan.get("inputs", {}).get("execution_mode") == "research"


def mode_label(plan: dict) -> str:
    return "research（研究草案，不可作为调仓指令）" if is_research_mode(plan) else "rebalance（正式调仓模式）"


def action_text(action: str, delta: float, research_mode: bool = False) -> str:
    if research_mode:
        if action == "buy":
            return f"目标高于当前 {num(abs(delta))}"
        if action == "sell":
            return f"目标低于当前 {num(abs(delta))}"
        return "持平观察"
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
    operator = item.get("forced_exit_operator", ">=")
    if percentile is None or threshold is None:
        return "已达到强制退出条件，目标仓位归零"
    return f"当前分位 {percentile:.2f}% {operator} 强制退出阈值 {threshold:.2f}%，目标仓位归零"


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


def hsi_unavailable_text(message: str) -> str:
    return (
        f"数据不可用（{message}），禁止新增港股敞口；"
        "按当前港股比例保留，并受港股总上限约束。"
    )


def append_data_health(lines: list[str], plan: dict) -> None:
    health = plan.get("signals", {}).get("data_health", {})
    lines.append("## 数据健康")
    lines.append("")
    lines.append(f"- 执行模式：`{mode_label(plan)}`")
    if health.get("as_of"):
        lines.append(f"- 统一截止日：`{health['as_of']}`")
    if health.get("portfolio_snapshot_as_of"):
        source = health.get("asset_date_source")
        suffix = "（人工声明，未由记录更新时间证明）" if source == "operator_asserted_portfolio_snapshot_as_of" else ""
        lines.append(f"- 持仓快照日：`{health['portfolio_snapshot_as_of']}`{suffix}")
    if health.get("dates"):
        dates = health["dates"]
        lines.append(
            f"- 数据日期：ERP `{dates.get('erp')}` / Relative `{dates.get('relative')}` / "
            f"港股 ERP `{dates.get('hsi_erp')}` / 持仓 `{dates.get('asset')}`"
        )
    if health.get("errors"):
        lines.append("- 阻断错误：")
        lines.extend(f"  - {item}" for item in health["errors"])
    if health.get("warnings"):
        lines.append("- 健康警告：")
        lines.extend(f"  - {item}" for item in health["warnings"])
    if not health.get("errors") and not health.get("warnings"):
        lines.append("- 通过：没有阻断错误或健康警告。")
    lines.append("")


def main() -> None:
    plan = load_json(PLAN_PATH)
    config = load_json(CONFIG_PATH)

    erp = plan["signals"]["erp"]
    hsi = plan["signals"].get("hsi_erp", {})
    relative = plan["signals"]["relative"]
    portfolio = plan["portfolio"]
    positions = ordered_positions(portfolio["positions"])
    research_mode = is_research_mode(plan)

    lines: list[str] = []
    lines.append("# ERP 研究草案 v3" if research_mode else "# ERP 调仓日报 v3")
    lines.append("")
    lines.append(f"生成时间: {datetime.now(SHANGHAI_TZ).isoformat(timespec='seconds')}")
    lines.append("")
    append_data_health(lines, plan)

    # ── 今日信号 ──
    lines.append("## 今日信号")
    lines.append("")
    lines.append(f"- **A股 ERP** (`{erp['date']}`)：股权溢价 `{erp['equity_premium']:.2f}`，历史分位 `{erp['percentile']:.2f}%`。")
    lines.append(f"  → 进攻 `{pct(erp['aggressive_weight'])}` / 防守 `{pct(erp['defensive_weight'])}`。")

    if hsi.get("available"):
        lines.append(f"- **港股 ERP** (`{hsi['date']}`)：股权溢价 `{hsi['equity_premium']:.2f}`，历史分位 `{hsi['percentile']:.2f}%`。")
        lines.append(f"  → 进攻 `{pct(hsi['aggressive_weight'])}` / 防守 `{pct(hsi['defensive_weight'])}`。")
    else:
        lines.append(f"- **港股 ERP**：{hsi_unavailable_text(hsi.get('message', 'fallback neutral'))}")

    pool_ashare = portfolio.get("ashare_pool", 0)
    pool_hk = portfolio.get("hkshare_pool", 0)
    lines.append(f"- **资金分配**：A股 `{pct(pool_ashare)}` / 港股 `{pct(pool_hk)}`。")
    lines.append("")

    # ── 比价建议 ──
    lines.append("## 比价建议")
    lines.append("")
    lines.append(f"- `{relative['date']}`")
    lines.extend(markdown_relative_signal_table(relative))
    lines.append("")

    # ── 可配置标的建议 ──
    lines.append("## 可配置标的建议")
    lines.append("")
    lines.extend(markdown_asset_suggestion_table(portfolio, plan.get("inputs", {}).get("execution_mode", "rebalance")))
    lines.append("")

    # ── 调仓建议 ──
    lines.append("## 研究草案（不可作为调仓指令）" if research_mode else "## 调仓建议")
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
                f"{'草案' if research_mode else '建议'} `{action_text(item['action'], item['delta_amount'], research_mode)}`。"
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
        sh50_exit = 100 - float(forced_exit_thresholds["sh50"]) if "sh50" in forced_exit_thresholds else "-"
        lines.append(f"- 强制退出阈值：`50<={sh50_exit}` / `500>={forced_exit_thresholds.get('zz500','-')}` / `1000>={forced_exit_thresholds.get('zz1000','-')}` / `创业板>={forced_exit_thresholds.get('cyb','-')}` / `科创50>={forced_exit_thresholds.get('kc50','-')}`")
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
