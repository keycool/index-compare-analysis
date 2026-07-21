#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Push the latest ERP daily summary to Feishu webhook — v4 (10-bucket).
Produces a compact execution card: current → target amounts, buy/sell deltas,
plus forced-exit / reentry / trajectory warnings.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import requests

from relative_signal_table import text_asset_suggestion_table, text_relative_signal_table


ROOT = Path(__file__).resolve().parent
PLAN_PATH = ROOT / "output" / "erp_execution_plan.json"
SUMMARY_PATH = ROOT / "output" / "erp_daily_summary.md"

# v4: 10-bucket display order, grouped by pool
BUCKET_ORDER = {
    # A-share defensive
    "hs300": 0, "sh50": 1, "val300": 2, "gro300": 3,
    # A-share aggressive
    "cyb": 4, "zz500": 5, "zz1000": 6, "kc50": 7,
    # HK
    "hsi": 8, "hstech": 9,
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_webhook_url() -> str:
    return (os.environ.get("ERP_DAILY_FEISHU_WEBHOOK_URL") or "").strip()


def resolve_webhook_secret() -> str:
    return (os.environ.get("ERP_DAILY_FEISHU_WEBHOOK_SECRET") or "").strip()


def describe_webhook(url: str) -> str:
    if not url:
        return "webhook_source=ERP_DAILY_FEISHU_WEBHOOK_URL webhook_tail=<missing>"
    tail = url.rstrip("/").split("/")[-1]
    return f"webhook_source=ERP_DAILY_FEISHU_WEBHOOK_URL webhook_tail={tail[-8:]}"


def ordered_positions(plan: dict) -> list[dict]:
    return sorted(
        plan["portfolio"]["positions"],
        key=lambda item: BUCKET_ORDER.get(item.get("bucket", ""), 99),
    )


def forced_exit_text(item: dict) -> str:
    if not item.get("forced_exit"):
        return ""
    pct = item.get("current_percentile")
    threshold = item.get("forced_exit_threshold")
    operator = item.get("forced_exit_operator", ">=")
    if pct is None or threshold is None:
        return " | ⚠ 强制退出"
    return f" | ⚠ 强制退出（分位 {pct:.1f}% {operator} {threshold:.1f}%）"


def reentry_text(item: dict) -> str:
    if not item.get("reentry_blocked"):
        return ""
    pct = item.get("current_percentile")
    threshold = item.get("reentry_threshold")
    if pct is None or threshold is None:
        return " | 🚫 暂不回补"
    return f" | 🚫 暂不回补（分位 {pct:.1f}% > {threshold:.1f}%）"


def trajectory_text(item: dict) -> str:
    multiplier = item.get("trajectory_multiplier")
    reason = item.get("trajectory_reason")
    if multiplier is None or reason in (
        None, "", "trajectory neutral",
        "trajectory metrics unavailable", "trajectory overlay disabled",
    ):
        return ""
    deviation = item.get("current_deviation")
    change_5d = item.get("change_5d")
    reason_map = {
        "trajectory hot": "🔥 轨迹过热",
        "trajectory warm": "🌤 轨迹偏热",
        "trajectory repair strong": "🩹 低位强修复",
        "trajectory repair light": "🩹 低位轻修复",
        "trajectory falling": "📉 仍在下滑",
    }
    label = reason_map.get(reason, reason)
    if deviation is None or change_5d is None:
        return f" | {label}（乘数 ×{multiplier:.2f}）"
    return (
        f" | {label}（30日偏离 {deviation:+.2f}%，"
        f"5日变化 {change_5d:+.2f}%，乘数 ×{multiplier:.2f}）"
    )


def build_payload(plan: dict, summary_text: str) -> dict:
    relative = plan["signals"]["relative"]
    erp = plan["signals"]["erp"]
    hsi = plan["signals"].get("hsi_erp", {})
    portfolio = plan["portfolio"]
    positions = ordered_positions(plan)

    content: list[list[dict[str, str]]] = []

    # ── Header ──
    content.append([{"tag": "text", "text": f"📊 ERP执行日报 ({relative['date']})"}])

    # ── Signal summary (compact) ──
    erp_line = (
        f"A股 ERP {erp['percentile']:.0f}% → 进攻 {erp['aggressive_weight']:.0%}"
    )
    hk_line = ""
    if hsi.get("available"):
        hk_line = (
            f" | 港股 ERP {hsi['percentile']:.0f}% → 进攻 {hsi['aggressive_weight']:.0%}"
        )
    elif hsi.get("message"):
        hk_line = f" | 港股 {hsi['message'][:20]}"
    pool_line = (
        f" | A股 {portfolio.get('ashare_pool', 0):.0%}"
        f" / 港股 {portfolio.get('hkshare_pool', 0):.0%}"
    )
    content.append([{"tag": "text", "text": erp_line + hk_line + pool_line}])
    content.append([{"tag": "text", "text": f"ERP管理资金: {portfolio['managed_amount']:,.0f}"}])

    # ── Relative signal table ──
    content.append([{"tag": "text", "text": "━━━━ 比价信号 ━━━━"}])
    for line in text_relative_signal_table(relative):
        content.append([{"tag": "text", "text": line}])

    content.append([{"tag": "text", "text": "━━━━ 可配置标的建议 ━━━━"}])
    for line in text_asset_suggestion_table(portfolio):
        content.append([{"tag": "text", "text": line}])

    # ── Divider before positions ──
    content.append([{"tag": "text", "text": "━━━━ 调仓建议 ━━━━"}])

    # ── Positions ──
    current_pool = None
    for item in positions:
        pool = item.get("pool", "")
        sleeve = item.get("sleeve", "")
        bucket = item["bucket"]

        # Pool header
        if pool != current_pool:
            current_pool = pool
            pool_label = "🇭🇰 港股" if pool == "hkshare" else "🇨🇳 A股"
            content.append([{"tag": "text", "text": f"【{pool_label}】"}])

        if item["delta_amount"] > 0:
            direction = "加仓"
        elif item["delta_amount"] < 0:
            direction = "减仓"
        else:
            direction = "—"

        sleeve_icon = "🛡" if sleeve == "defensive" else "⚔"

        # Build the line piece by piece
        text = (
            f"{sleeve_icon} {item['label']}"
            f" | 当前 {item['current_amount']:,.0f}"
            f" | 目标 {item['target_amount']:,.0f}"
            f" | {direction} {abs(item['delta_amount']):,.0f}"
        )
        # Append warning tags in priority order
        text += forced_exit_text(item)
        text += reentry_text(item)
        text += trajectory_text(item)

        content.append([{"tag": "text", "text": text}])

    # ── Footer ──
    content.append([{"tag": "text", "text": "━━━━━━━━━━━━━━━━━━"}])
    content.append([{"tag": "text", "text": "⚠ 本内容为量化分析参考，不构成投资建议"}])

    if summary_text.strip():
        content.append([{"tag": "text", "text": "📄 完整 Markdown 日报已生成"}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"ERP执行日报 ({relative['date']})",
                    "content": content,
                }
            }
        },
    }


def build_fallback_text_payload(plan: dict) -> dict:
    """Plain-text fallback when Feishu bot keyword filter blocks post payload."""
    relative = plan["signals"]["relative"]
    erp = plan["signals"]["erp"]
    portfolio = plan["portfolio"]
    positions = ordered_positions(plan)

    lines = [
        f"ERP执行日报 ({relative['date']})",
        f"A股 ERP {erp['percentile']:.0f}% 进攻{erp['aggressive_weight']:.0%}",
        f"资金: {portfolio['managed_amount']:,.0f}",
        "比价信号:",
        *text_relative_signal_table(relative),
        "可配置标的建议:",
        *text_asset_suggestion_table(portfolio),
        "调仓建议:",
    ]
    for item in positions:
        if item["delta_amount"] > 0:
            direction = "加仓"
        elif item["delta_amount"] < 0:
            direction = "减仓"
        else:
            direction = "保持"
        line = (
            f"{item['label']}: 当前 {item['current_amount']:,.0f}, "
            f"目标 {item['target_amount']:,.0f}, {direction} {abs(item['delta_amount']):,.0f}"
        )
        fe = forced_exit_text(item).replace(" | ", ", ")
        re = reentry_text(item).replace(" | ", ", ")
        tr = trajectory_text(item).replace(" | ", ", ")
        if fe:
            line += fe
        if re:
            line += re
        if tr:
            line += tr
        lines.append(line)

    return {
        "msg_type": "text",
        "content": {"text": "\n".join(lines)},
    }


def attach_signature(payload: dict, secret: str) -> dict:
    if not secret:
        return payload

    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    sign = base64.b64encode(
        hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    signed = dict(payload)
    signed["timestamp"] = timestamp
    signed["sign"] = sign
    return signed


def main() -> None:
    webhook_url = resolve_webhook_url()
    if not webhook_url:
        raise RuntimeError("Missing Feishu webhook URL. Set ERP_DAILY_FEISHU_WEBHOOK_URL.")

    if not PLAN_PATH.exists():
        raise FileNotFoundError(f"Missing execution plan: {PLAN_PATH}")
    if not SUMMARY_PATH.exists():
        raise FileNotFoundError(f"Missing daily summary: {SUMMARY_PATH}")

    plan = load_json(PLAN_PATH)
    summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
    secret = resolve_webhook_secret()

    print(f"[PUSH] {describe_webhook(webhook_url)}")
    payload = build_payload(plan, summary_text)
    response = requests.post(
        webhook_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(attach_signature(payload, secret), ensure_ascii=False),
        timeout=15,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code") == 19024:
        print("[PUSH] keyword check blocked post payload, retrying with plain text fallback")
        fallback = build_fallback_text_payload(plan)
        retry = requests.post(
            webhook_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(attach_signature(fallback, secret), ensure_ascii=False),
            timeout=15,
        )
        retry.raise_for_status()
        result = retry.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu push failed: {result}")

    print(
        json.dumps(
            {"success": True, "message": "pushed", "date": plan["signals"]["relative"]["date"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
