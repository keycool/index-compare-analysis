#!/usr/bin/env python
"""直接渲染 push_erp_daily_summary_to_feishu_v3.py 的输出预览。"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORCH = ROOT / "orchestrator"

# Mock an execution plan with the validation results
conclusions = json.loads(
    (ROOT / ".claude" / "skills" / "index-compare" / "data" / "conclusions.json").read_text("utf-8")
)

def rec(code):
    return conclusions.get(code, {}).get("recommendation", {}).get("action", "标配")

def dev(code):
    return conclusions.get(code, {}).get("deviation", {}).get("value", 0)

def chg(code):
    ch = conclusions.get(code, {}).get("trend", {}).get("changes", {})
    return ch.get("5d")

def pct_val(code):
    return conclusions.get(code, {}).get("percentile", {}).get("value")

# Build a mock plan matching the validation output
plan = {
    "version": "3.0",
    "signals": {
        "erp": {
            "date": "2026-07-02",
            "equity_premium": 3.42,
            "percentile": 55.0,
            "aggressive_weight": 0.575,
            "defensive_weight": 0.425,
        },
        "hsi_erp": {
            "available": False,
            "message": "HSI ERP table unavailable",
            "percentile": 50.0,
            "aggressive_weight": 0.45,
        },
        "relative": {
            "date": "2026-07-02",
        },
    },
    "portfolio": {
        "managed_amount": 1_000_000,
        "ashare_pool": 0.80,
        "hkshare_pool": 0.20,
        "positions": [
            {
                "bucket": "hs300", "label": "沪深300", "sleeve": "defensive", "pool": "ashare",
                "current_amount": 0, "target_amount": 594_555,
                "delta_amount": 594_555, "action": "buy",
            },
            {
                "bucket": "sh50", "label": "上证50/红利", "sleeve": "defensive", "pool": "ashare",
                "current_amount": 0, "target_amount": 86_215,
                "delta_amount": 86_215, "action": "buy",
                "current_percentile": pct_val("SH50"),
                "trajectory_multiplier": 1.05, "trajectory_reason": "trajectory repair light",
                "current_deviation": dev("SH50"), "change_5d": chg("SH50"),
            },
            {
                "bucket": "val300", "label": "300价值", "sleeve": "defensive", "pool": "ashare",
                "current_amount": 0, "target_amount": 22_491,
                "delta_amount": 22_491, "action": "buy",
                "current_percentile": pct_val("VAL300"),
                "trajectory_multiplier": 1.15, "trajectory_reason": "trajectory repair strong",
                "current_deviation": dev("VAL300"), "change_5d": chg("VAL300"),
            },
            {
                "bucket": "gro300", "label": "300成长", "sleeve": "defensive", "pool": "ashare",
                "current_amount": 0, "target_amount": 9_639,
                "delta_amount": 9_639, "action": "buy",
            },
            {
                "bucket": "cyb", "label": "创业板", "sleeve": "aggressive", "pool": "ashare",
                "current_amount": 0, "target_amount": 0,
                "delta_amount": 0, "action": "hold",
                "current_percentile": pct_val("ZZA500"),
                "forced_exit_threshold": 95.0, "forced_exit": True,
                "reentry_threshold": 30.0, "reentry_blocked": True,
            },
            {
                "bucket": "zz500", "label": "中证500", "sleeve": "aggressive", "pool": "ashare",
                "current_amount": 0, "target_amount": 26_677,
                "delta_amount": 26_677, "action": "buy",
                "current_percentile": pct_val("ZZ500"),
                "reentry_threshold": 40.0, "reentry_blocked": True,
                "trajectory_multiplier": 0.60, "trajectory_reason": "trajectory hot",
                "current_deviation": dev("ZZ500"), "change_5d": chg("ZZ500"),
            },
            {
                "bucket": "zz1000", "label": "中证1000", "sleeve": "aggressive", "pool": "ashare",
                "current_amount": 0, "target_amount": 26_677,
                "delta_amount": 26_677, "action": "buy",
                "current_percentile": pct_val("ZZ1000"),
                "reentry_threshold": 35.0, "reentry_blocked": True,
                "trajectory_multiplier": 0.80, "trajectory_reason": "trajectory warm",
                "current_deviation": dev("ZZ1000"), "change_5d": chg("ZZ1000"),
            },
            {
                "bucket": "kc50", "label": "科创50", "sleeve": "aggressive", "pool": "ashare",
                "current_amount": 0, "target_amount": 33_743,
                "delta_amount": 33_743, "action": "buy",
                "current_percentile": pct_val("KC50"),
            },
            {
                "bucket": "hsi", "label": "恒生指数", "sleeve": "defensive", "pool": "hkshare",
                "current_amount": 0, "target_amount": 110_000,
                "delta_amount": 110_000, "action": "buy",
            },
            {
                "bucket": "hstech", "label": "恒生科技", "sleeve": "aggressive", "pool": "hkshare",
                "current_amount": 0, "target_amount": 72_000,
                "delta_amount": 72_000, "action": "buy",
                "current_percentile": pct_val("HKTECH"),
                "trajectory_multiplier": 0.80, "trajectory_reason": "trajectory warm",
                "current_deviation": dev("HKTECH"), "change_5d": chg("HKTECH"),
            },
        ],
    },
}

# Import and use the actual push functions
sys_path = str(ORCH)
import sys
sys.path.insert(0, sys_path)

from push_erp_daily_summary_to_feishu_v3 import build_payload, forced_exit_text, reentry_text, trajectory_text

payload = build_payload(plan, "dummy summary")

# Format as readable text
print("=" * 64)
print("  📱 飞书 Webhook 卡片预览 (v4 — 执行向)")
print("=" * 64)
print()

content = payload["content"]["post"]["zh_cn"]["content"]
for row in content:
    text_parts = []
    for elem in row:
        text_parts.append(elem.get("text", ""))
    line = "".join(text_parts)
    # Add color hints
    if "加仓" in line:
        print(f"  {line}")
    elif "减仓" in line:
        print(f"  {line}")
    elif "⚠" in line or "🚫" in line:
        print(f"  {line}")
    elif "—" in line and "|" in line:
        print(f"  {line}")
    elif "🔥" in line or "🌤" in line or "🩹" in line or "📉" in line:
        print(f"  {line}")
    else:
        print(f"  {line}")

print()
print("=" * 64)
print("  对比旧版卡片（只有 5 bucket，无数值/无风控原因）")
print("=" * 64)
print()

# Simulate old format
old_positions = [
    ("沪深300", 340239, 350044, 9805, "buy", False, False),
    ("上证50", 74862, 79176, 4314, "buy", False, False),
    ("创业板", 24761, 10645, -14116, "sell", False, True),
    ("中证500", 1, 0, -1, "sell", True, True),
    ("中证1000", 1, 0, -1, "sell", True, False),
]
print("  📊 ERP执行日报 (2026-06-30)")
print("  调仓建议（2026-06-30）")
for label, cur, tgt, delta, action, reentry, traj in old_positions:
    dir_text = "加仓" if delta > 0 else ("减仓" if delta < 0 else "保持")
    extra = ""
    if reentry:
        extra += " | 暂不回补"
    if traj:
        extra += " | 轨迹过热（30日偏离 +4.91%，5日变化 +2.34%）"
    print(f"  {label} | 当前 {cur:,} | 目标 {tgt:,} | {dir_text} {abs(delta):,}{extra}")
print("  完整 Markdown 日报已生成。")
