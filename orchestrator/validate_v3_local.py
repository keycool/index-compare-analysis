#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
本地回测验证：用已有的 conclusions.json 模拟完整 v3 执行层输出。
不需要飞书 API，不读写任何远程数据。
"""

import json
import math
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# ═══════════════════════════════════════════════
#  从 erp_execution_cloud.py 复制核心函数
# ═══════════════════════════════════════════════

def piecewise_linear_weight(percentile, low_threshold, high_threshold,
                            low_weight, neutral_weight, high_weight):
    midpoint = (low_threshold + high_threshold) / 2.0
    if percentile <= low_threshold:
        return low_weight
    if percentile >= high_threshold:
        return high_weight
    if percentile <= midpoint:
        span = max(1e-9, midpoint - low_threshold)
        return low_weight + (neutral_weight - low_weight) * (percentile - low_threshold) / span
    span = max(1e-9, high_threshold - midpoint)
    return neutral_weight + (high_weight - neutral_weight) * (percentile - midpoint) / span

def normalize_to_weights(scores):
    positive = {k: max(0.0, float(v)) for k, v in scores.items()}
    total = sum(positive.values())
    if total <= 0:
        equal = 1.0 / len(positive) if positive else 0.0
        return {k: equal for k in positive}
    return {k: v / total for k, v in positive.items()}

def recommendation_multiplier(text, mapping):
    if not text:
        return 1.0
    return float(mapping.get(str(text).strip(), 1.0))

_KC50_REVERSE = {
    "强烈超配": "强烈低配", "超配": "低配", "标配": "标配",
    "低配": "超配", "强烈低配": "强烈超配",
}

def kc50_bucket_rec(rec):
    return _KC50_REVERSE.get(rec, "标配")

def trajectory_multiplier(deviation, change_5d, config):
    if not config.get("enabled", True):
        return 1.0, "disabled"
    if deviation is None or change_5d is None:
        return 1.0, "metrics unavailable"

    hot = config.get("hot", {})
    if deviation >= float(hot.get("deviation_min", 4.0)) or change_5d >= float(hot.get("change_5d_min", 3.0)):
        return float(hot.get("multiplier", 0.6)), "hot"

    warm = config.get("warm", {})
    if deviation >= float(warm.get("deviation_min", 2.0)) or change_5d >= float(warm.get("change_5d_min", 1.0)):
        return float(warm.get("multiplier", 0.8)), "warm"

    repair_strong = config.get("repair_strong", {})
    if deviation <= float(repair_strong.get("deviation_max", -3.0)) and change_5d > float(repair_strong.get("change_5d_min", 0.0)):
        return float(repair_strong.get("multiplier", 1.15)), "repair_strong"

    repair_light = config.get("repair_light", {})
    if deviation <= float(repair_light.get("deviation_max", -1.0)) and change_5d > float(repair_light.get("change_5d_min", 0.0)):
        return float(repair_light.get("multiplier", 1.05)), "repair_light"

    falling = config.get("falling", {})
    if deviation < float(falling.get("deviation_max", 0.0)) and change_5d < float(falling.get("change_5d_max", 0.0)):
        return float(falling.get("multiplier", 0.85)), "falling"

    return 1.0, "neutral"


def style_pair_val300_fraction(val300_pct, style_config):
    thresholds = style_config.get("percentile_thresholds", {"low": 30, "high": 70})
    split = style_config.get("split", {})
    if val300_pct is None:
        return float(split.get("neutral_weight", 0.50))
    low = float(thresholds.get("low", 30))
    high = float(thresholds.get("high", 70))
    val_w = float(split.get("value_cheap_weight", 0.70))
    neu_w = float(split.get("neutral_weight", 0.50))
    gro_w = float(split.get("growth_cheap_weight", 0.70))
    if val300_pct <= low:
        return val_w
    if val300_pct >= high:
        return 1.0 - gro_w
    ratio = (val300_pct - low) / max(1e-9, high - low)
    return val_w + ((1.0 - gro_w) - val_w) * ratio


def cross_market_allocation(hsi_erp_pct, cross_config):
    hk_cap = float(cross_config.get("hk_pool_cap", 0.20))
    hk_min = float(cross_config.get("hk_min_erp_percentile", 30))
    hk_full = float(cross_config.get("hk_full_erp_percentile", 50))
    if hsi_erp_pct <= hk_min:
        return 1.0, 0.0
    if hsi_erp_pct >= hk_full:
        return 1.0 - hk_cap, hk_cap
    ratio = (hsi_erp_pct - hk_min) / max(1e-9, hk_full - hk_min)
    hk = hk_cap * ratio
    return 1.0 - hk, hk


# ═══════════════════════════════════════════════
#  加载数据
# ═══════════════════════════════════════════════

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / ".claude" / "skills" / "index-compare"

conclusions = json.loads((SKILL_DIR / "data" / "conclusions.json").read_text(encoding="utf-8"))
analysis = json.loads((SKILL_DIR / "data" / "analysis_results.json").read_text(encoding="utf-8"))
config = json.loads((ROOT / "orchestrator" / "erp_execution_config.json").read_text(encoding="utf-8"))

# ═══════════════════════════════════════════════
#  构建模拟信号
# ═══════════════════════════════════════════════

# ERP: 用中位数附近
erp_pct = 55.0
erp_agg = piecewise_linear_weight(erp_pct, 40, 60, 0.35, 0.50, 0.65)

# HSI ERP: fallback 中性
hsi_erp_pct = 50.0
hsi_agg = 0.45

# 比价建议从 conclusions 中提取
def rec(code):
    return conclusions.get(code, {}).get("recommendation", {}).get("action", "标配")

def dev(code):
    return conclusions.get(code, {}).get("deviation", {}).get("value", 0)

def chg(code):
    ch = conclusions.get(code, {}).get("trend", {}).get("changes", {})
    return ch.get("5d")

def pct_val(code):
    return conclusions.get(code, {}).get("percentile", {}).get("value")

signals = {
    "zz500":  {"rec": rec("ZZ500"),  "pct": pct_val("ZZ500"),  "dev": dev("ZZ500"),  "chg5": chg("ZZ500")},
    "zz1000": {"rec": rec("ZZ1000"), "pct": pct_val("ZZ1000"), "dev": dev("ZZ1000"), "chg5": chg("ZZ1000")},
    "cyb":    {"rec": rec("ZZA500"), "pct": pct_val("ZZA500"), "dev": dev("ZZA500"), "chg5": chg("ZZA500")},
    "sh50":   {"rec": rec("SH50"),   "pct": pct_val("SH50"),   "dev": dev("SH50"),   "chg5": chg("SH50")},
    "kc50":   {"rec": rec("KC50"),   "pct": pct_val("KC50"),   "dev": dev("KC50"),   "chg5": chg("KC50")},
    "val300": {"rec": rec("VAL300"), "pct": pct_val("VAL300"), "dev": dev("VAL300"), "chg5": chg("VAL300")},
    "hstech": {"rec": rec("HKTECH"), "pct": pct_val("HKTECH"), "dev": dev("HKTECH"), "chg5": chg("HKTECH")},
    "gro300": {"pct": 100 - (pct_val("VAL300") or 50), "dev": -(dev("VAL300") or 0)},
}


# ═══════════════════════════════════════════════
#  模拟总资产 100万，当前持仓为 0 (纯新仓)
# ═══════════════════════════════════════════════

TOTAL = 1_000_000
current = {}  # 空仓模拟

# ═══════════════════════════════════════════════
#  计算
# ═══════════════════════════════════════════════

thresholds = config["percentile_thresholds"]
alpha_bw = config["alpha_budget_weights"]
multipliers = config["recommendation_multipliers"]
base_weights = config["alpha_base_weights"]
caps = config["alpha_bucket_caps"]
forced_exit = config.get("forced_exit_percentiles", {})
reentry = config.get("aggressive_reentry_percentiles", {})
traj_cfg = config.get("trajectory_overlay", {})
style_cfg = config.get("style_pair", {})
cross_cfg = config.get("cross_market", {})
hk_cfg = config.get("hk_erp", {})
bucket_meta = config.get("bucket_metadata", {})

# ── Cross-market ──
ashare_pool, hk_pool = cross_market_allocation(hsi_erp_pct, cross_cfg)
print(f"跨市场: A股={ashare_pool:.1%} 港股={hk_pool:.1%}")

# ── A-share sleeve split ──
ashare_def = ashare_pool * (1 - erp_agg)
ashare_agg = ashare_pool * erp_agg
alpha_budget = piecewise_linear_weight(erp_pct, float(thresholds["low"]), float(thresholds["high"]),
                                        float(alpha_bw["low"]), float(alpha_bw["neutral"]), float(alpha_bw["high"]))
alpha_budget = min(alpha_budget, 0.45)

print(f"A股: 防守={ashare_def:.1%} 进攻={ashare_agg:.1%} AlphaBudget={alpha_budget:.1%}")

# ── A-share defensive ──
def_total = ashare_def
def_alpha = def_total * alpha_budget
style_budget_ratio = float(style_cfg.get("budget_ratio", 0.30))
style_pair_budget = def_alpha * style_budget_ratio

val300_pct = signals["val300"]["pct"]
val300_frac = style_pair_val300_fraction(val300_pct, style_cfg)
val300_tw = style_pair_budget * val300_frac
gro300_tw = style_pair_budget * (1 - val300_frac)

sh50_tw = def_alpha * (1 - style_budget_ratio)
sh50_tw *= recommendation_multiplier(signals["sh50"]["rec"], multipliers)
sh50_tw = min(sh50_tw, float(caps.get("sh50", 0.18)))
# sh50 forced exit
if signals["sh50"]["pct"] and float(signals["sh50"]["pct"]) >= float(forced_exit.get("sh50", 999)):
    sh50_tw = 0.0

hs300_tw = max(0, def_total - sh50_tw - val300_tw - gro300_tw)

def_weights = {
    "沪深300": hs300_tw,
    "上证50/红利": sh50_tw,
    "300价值": val300_tw,
    "300成长": gro300_tw,
}

hs300_tw = max(0, def_total - sh50_tw - val300_tw - gro300_tw)

# ── A-share aggressive ──
agg_total = ashare_agg
agg_alpha = agg_total * alpha_budget

scores = {}
for b in ["cyb", "zz500", "zz1000", "kc50"]:
    base = float(base_weights.get(b, 0.3))
    r = signals[b]["rec"]
    if b == "kc50":
        r = kc50_bucket_rec(r)
    scores[b] = base * recommendation_multiplier(r, multipliers)

local_w = normalize_to_weights(scores)

agg_weights = {}
agg_used = 0.0
for b in ["cyb", "zz500", "zz1000", "kc50"]:
    tw = agg_alpha * local_w[b]
    tw = min(tw, float(caps.get(b, 1.0)))
    # forced exit
    if signals[b]["pct"] and float(signals[b]["pct"]) >= float(forced_exit.get(b, 999)):
        tw = 0.0
    # trajectory
    tm, tr = trajectory_multiplier(signals[b]["dev"], signals[b]["chg5"], traj_cfg)
    tw *= tm
    agg_used += tw
    label = bucket_meta.get(b, {}).get("label", b)
    agg_weights[label] = (tw, tr, tm)

# HS300 gets: defensive residual + aggressive passive (not α-managed)
hs300_tw += max(0.0, agg_total - agg_used)

# ── HK pool ──
hk_agg_pct = hsi_agg
hk_def_total = hk_pool * (1 - hk_agg_pct)
hk_agg_total = hk_pool * hk_agg_pct

hstech_tw = hk_agg_total
if signals["hstech"]["pct"] and float(signals["hstech"]["pct"]) >= float(forced_exit.get("hstech", 999)):
    hstech_tw = 0.0
tm_ht, tr_ht = trajectory_multiplier(signals["hstech"]["dev"], signals["hstech"]["chg5"], traj_cfg)
hstech_tw *= tm_ht
hstech_tw = min(hstech_tw, float(caps.get("hstech", 0.08)))


# ═══════════════════════════════════════════════
#  输出
# ═══════════════════════════════════════════════

print()
print("=" * 72)
print("  ERP v3 回测验证 — 假设总资产 1,000,000，当前空仓")
print("=" * 72)
print(f"  生成时间: {datetime.now(SHANGHAI_TZ).isoformat(timespec='seconds')}")
print()
print(f"  HS300 ERP 分位: {erp_pct}%  →  进攻={erp_agg:.1%}  防守={1-erp_agg:.1%}")
print(f"  HSI   ERP 分位: {hsi_erp_pct}% (fallback)  →  进攻={hsi_agg:.1%}")
print(f"  Alpha Budget:   {alpha_budget:.1%}")
print()

# ── 信号表 ──
print("  ── 比价信号 ──")
print(f"  {'标的':12s} {'建议':8s} {'分位':>7s} {'偏离':>7s} {'5日变':>7s}  {'KC50反向':>10s}")
print(f"  {'-'*12} {'-'*8} {'-'*7} {'-'*7} {'-'*7}  {'-'*10}")
for k in ["zz500", "zz1000", "cyb", "sh50", "kc50", "val300", "hstech"]:
    s = signals[k]
    kc50_rev = f"→ {kc50_bucket_rec(s['rec'])}" if k == "kc50" else ""
    print(f"  {k:12s} {s['rec'] or '标配':8s} {s['pct'] or 0:>6.1f}% {s['dev'] or 0:>+6.1f}% {s['chg5'] or 0:>+6.1f}%  {kc50_rev:10s}")

print()
print("  ── 目标配置 ──")
print(f"  {'Pool':6s} {'Sleeve':10s} {'Bucket':18s} {'权重':>7s} {'金额':>12s}  {'备注'}")
print(f"  {'-'*6} {'-'*10} {'-'*18} {'-'*7} {'-'*12}  {'-'*20}")

total_check = 0.0
rows = [
    ("A股", "防守", "沪深300", hs300_tw, ""),
    ("A股", "防守", "上证50/红利", sh50_tw, f"rec={signals['sh50']['rec']}"),
    ("A股", "防守", "300价值", val300_tw, f"VAL300 pct={val300_pct:.1f}%→val占{val300_frac:.0%}"),
    ("A股", "防守", "300成长", gro300_tw, ""),
]
for b, tm_info in [("创业板", "cyb"), ("中证500", "zz500"), ("中证1000", "zz1000"), ("科创50", "kc50")]:
    tw, tr, tmult = agg_weights[b]
    note = f"rec={signals[tm_info]['rec']} traj={tr}×{tmult}"
    rows.append(("A股", "进攻", b, tw, note))

rows.append(("港股", "防守", "恒生指数", hk_def_total, ""))
note_ht = f"rec={signals['hstech']['rec']} traj={tr_ht}×{tm_ht}"
rows.append(("港股", "进攻", "恒生科技", hstech_tw, note_ht))

for pool, sleeve, label, tw, note in rows:
    amount = int(TOTAL * tw)
    total_check += tw
    print(f"  {pool:6s} {sleeve:10s} {label:18s} {tw:>6.1%} {amount:>12,}  {note}")

print(f"  {'─'*72}")
print(f"  合计: {total_check:.1%}  ({int(TOTAL * total_check):,})")
if abs(total_check - 1.0) > 0.001:
    print(f"  ⚠ 权重偏差: {total_check - 1.0:+.3%} (残差归入沪深300底仓)")

print()
print("  ── 风控状态 ──")
for b, key in [("sh50", "上证50"), ("cyb", "创业板"), ("zz500", "中证500"),
                ("zz1000", "中证1000"), ("kc50", "科创50"), ("hstech", "恒生科技")]:
    fe = forced_exit.get(b)
    p = signals[b]["pct"]
    if fe and p and float(p) >= float(fe):
        print(f"  ⚠ {key}: 强制退出 (分位 {p:.1f}% ≥ {fe}%)")
    re = reentry.get(b)
    # 模拟空仓 + 高分位 → 重入阻塞
    if re and p and float(p) > float(re):
        print(f"  🚫 {key}: 重入闸门关闭 (分位 {p:.1f}% > {re}%) — 空仓状态下被阻塞")

print()
print("=" * 72)
print("  验证完成。本输出为本地模拟，不影响线上 workflow。")
print("=" * 72)
