#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cloud-friendly ERP execution workflow — v3 expanded.

Adds:
- Cross-market allocation (A-share + HK pools)
- KC50, VAL300, GRO300 as tradable buckets in A-share defensive/aggressive
- HSI (defensive) + HKTECH (aggressive) HK pool
- KC50 reverse logic (only holds when ratio percentile high)
- Style pair (VAL300/GRO300) replacing old style overlay
- HSI ERP via optional Feishu table (falls back to neutral)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


# ── Default Feishu table tokens ──────────────────────────────
DEFAULT_ERP_APP_TOKEN = "VnkcbzcsdabuDwslZhCc6WurnMd"
DEFAULT_ERP_TABLE_ID = "tblEo1BqoTp5z2UV"
DEFAULT_RELATIVE_APP_TOKEN = "POghbC154ablpxs20USc6veDnlh"
DEFAULT_RELATIVE_TABLE_ID = "tblnsUexqsEiLZs9"
DEFAULT_ASSET_APP_TOKEN = "TiVJb2a5GaRiZTsoeXFcO6BCn8e"
DEFAULT_ASSET_TABLE_ID = "tbl1qLL1iXMykQRd"
DEFAULT_HSI_ERP_APP_TOKEN = ""
DEFAULT_HSI_ERP_TABLE_ID = ""

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "erp_execution_plan.json"
DEFAULT_EXECUTION_CONFIG_PATH = Path(__file__).resolve().parent / "erp_execution_config.json"
DEFAULT_RENDER_SCRIPT = Path(__file__).resolve().parent / "render_erp_daily_summary_v4.py"

BASE_URL = "https://open.feishu.cn/open-apis"
AUTH_URL = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# ── Mojibake repair map ──────────────────────────────────────
MOJIBAKE_MAP = {
    "鏍囬厤": "标配", "瓒呴厤": "超配", "浣庨厤": "低配",
    "寮虹儓瓒呴厤": "强烈超配", "寮虹儓浣庨厤": "强烈低配",
    "娌繁300": "沪深300", "涓婅瘉50": "上证50",
    "鍒涗笟鏉": "创业板", "涓瘉500": "中证500", "涓瘉1000": "中证1000",
    "绉戝垱50": "科创50", "绾㈠埄ETF": "红利ETF",
    "鎭掔敓ETF": "恒生ETF", "鎭掔敓绉戞妧": "恒生科技",
    "鏃ユ湡": "日期", "鑲℃潈婧环鎸囨暟": "股权溢价指数",
    "500寤鸿": "500建议", "1000寤鸿": "1000建议",
    "鍒涗笟鏉垮缓璁": "创业板建议", "50寤鸿": "50建议",
    "绉戝垱50寤鸿": "科创50建议", "鎭掔敓绉戞妧寤鸿": "恒生科技建议",
    "300浠峰€煎缓璁": "300价值建议", "300鎴愰暱寤鸿": "300成长建议",
    "椤圭洰鍚嶇О": "项目名称", "閲戦": "金额",
}


def repair_text(text: str) -> str:
    fixed = unicodedata.normalize("NFKC", text).strip()
    for bad, good in MOJIBAKE_MAP.items():
        fixed = fixed.replace(bad, good)
    return fixed


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return repair_text(str(value))


def sanitize_structure(value: Any) -> Any:
    if isinstance(value, dict):
        return {normalize_text(key): sanitize_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_structure(item) for item in value]
    if isinstance(value, str):
        return normalize_text(value)
    return value


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {normalize_text(key): value for key, value in row.items()}


def get_first(row: dict[str, Any], *names: str) -> Any:
    normalized = {normalize_text(name) for name in names}
    for key, value in row.items():
        if normalize_text(key) in normalized:
            return value
    return None


def parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            number = int(value)
        except Exception:
            return None
        if abs(number) >= 10_000_000_000:
            number = number // 1000
        try:
            return datetime.fromtimestamp(number, SHANGHAI_TZ)
        except Exception:
            return None
    text = normalize_text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=SHANGHAI_TZ)
        except ValueError:
            continue
    return None


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    candidates = cell_texts(value)
    if len(candidates) > 1:
        candidates.append("".join(candidates))
    for candidate in candidates:
        text = candidate.replace(",", "").replace("￥", "").replace("¥", "").strip()
        if text.endswith("%"):
            text = text[:-1].strip()
        if not text:
            continue
        try:
            number = float(text)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def parse_multiselect(value: Any) -> list[str]:
    return cell_texts(value)


def cell_texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            texts.extend(cell_texts(item))
        return [t for t in texts if t]
    if isinstance(value, dict):
        for key in ("text", "name", "value", "display_value", "formatted_value", "title"):
            if key in value:
                return cell_texts(value[key])
        return []
    text = normalize_text(value)
    return [text] if text else []


# ── Feishu OpenAPI reader ────────────────────────────────────

class FeishuBitableReader:
    def __init__(self, app_id: str, app_secret: str):
        if not app_id or not app_secret:
            raise ValueError("Missing FEISHU_APP_ID / FEISHU_APP_SECRET")
        self.app_id = app_id
        self.app_secret = app_secret
        self._tenant_token: str | None = None
        self._tenant_expiry = 0.0

    def _refresh_token(self) -> None:
        response = requests.post(AUTH_URL, json={"app_id": self.app_id, "app_secret": self.app_secret}, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {payload}")
        self._tenant_token = payload["tenant_access_token"]
        self._tenant_expiry = time.time() + float(payload.get("expire", 7200)) - 300

    def _headers(self) -> dict[str, str]:
        if not self._tenant_token or time.time() >= self._tenant_expiry:
            self._refresh_token()
        return {"Authorization": f"Bearer {self._tenant_token}", "Content-Type": "application/json"}

    def list_all_records(self, app_token: str, table_id: str, page_size: int = 500) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {"page_size": min(page_size, 500), "automatic_fields": "true"}
            if page_token:
                params["page_token"] = page_token
            url = f"{BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
            response = requests.get(url, params=params, headers=self._headers(), timeout=30)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise RuntimeError(f"Feishu record list failed: {payload}")
            data = payload.get("data", {})
            for item in data.get("items", []):
                fields = normalize_row(item.get("fields", {}))
                fields["record_id"] = item.get("record_id")
                fields["_created_time"] = item.get("created_time") or get_first(
                    fields, "created_time", "创建时间", "创建日期"
                )
                fields["_last_modified_time"] = item.get("last_modified_time") or get_first(
                    fields, "last_modified_time", "更新时间", "最后更新时间", "修改时间"
                )
                records.append(fields)
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        return records


# ── Math helpers ─────────────────────────────────────────────

def recommendation_multiplier(text: str | None, mapping: dict[str, float]) -> float:
    if not text:
        return 1.0
    return float(mapping.get(normalize_text(text), 1.0))


def piecewise_linear_weight(percentile: float, low_threshold: float, high_threshold: float,
                            low_weight: float, neutral_weight: float, high_weight: float) -> float:
    midpoint = (low_threshold + high_threshold) / 2.0
    if percentile <= low_threshold:
        return low_weight
    if percentile >= high_threshold:
        return high_weight
    if percentile <= midpoint:
        span = max(1e-9, midpoint - low_threshold)
        ratio = (percentile - low_threshold) / span
        return low_weight + (neutral_weight - low_weight) * ratio
    span = max(1e-9, high_threshold - midpoint)
    ratio = (percentile - midpoint) / span
    return neutral_weight + (high_weight - neutral_weight) * ratio


def normalize_to_weights(scores: dict[str, float]) -> dict[str, float]:
    positive = {key: max(0.0, float(value)) for key, value in scores.items()}
    total = sum(positive.values())
    if total <= 0:
        equal = 1.0 / len(positive) if positive else 0.0
        return {key: equal for key in positive}
    return {key: value / total for key, value in positive.items()}


# ── Reverse recommendation map ───────────────────────────────
_REVERSE_REC = {
    "强烈超配": "强烈低配", "超配": "低配", "标配": "标配",
    "低配": "超配", "强烈低配": "强烈超配",
}


def _kc50_rec_to_bucket_rec(rec: str) -> str:
    """Convert KC50 ratio recommendation to KC50 bucket recommendation."""
    return _REVERSE_REC.get(normalize_text(rec), "标配")


# ── Holding resolution ───────────────────────────────────────

def resolve_holding_bucket(name: str, alias_lookup: dict[str, str], ignored_lookup: set[str]) -> str | None:
    fixed_name = normalize_text(name)
    if fixed_name in ignored_lookup:
        return "__IGNORE__"
    if fixed_name in alias_lookup:
        return alias_lookup[fixed_name]
    if "国债" in fixed_name:
        return "__IGNORE__"
    if "恒生消费" in fixed_name:
        return "__IGNORE__"
    # v3: 科创50 no longer ignored
    if "科创50" in fixed_name:
        return "kc50"
    if "恒生科技" in fixed_name:
        return "hstech"
    if "恒生" in fixed_name and "ETF" in fixed_name:
        return "hsi"
    if "恒生指数" in fixed_name:
        return "hsi"
    if "300价值" in fixed_name:
        return "val300"
    if "300成长" in fixed_name:
        return "gro300"
    if "红利" in fixed_name:
        return "__IGNORE__"
    if "创业板" in fixed_name:
        return "cyb"
    if "1000" in fixed_name:
        return "zz1000"
    if "500" in fixed_name:
        return "zz500"
    if "50" in fixed_name:
        return "sh50"
    if "300" in fixed_name:
        return "hs300"
    return None


def aggregate_current_holdings(
    rows: list[dict[str, Any]], alias_map: dict[str, str], ignored_holdings: set[str],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    aggregated: dict[str, float] = {}
    unmapped: list[dict[str, Any]] = []
    for row in rows:
        third_level = parse_multiselect(get_first(row, "Ⅲ级分类", "III级分类", "三级分类"))
        if "ERP" not in third_level:
            continue
        name = normalize_text(get_first(row, "项目名称", "标的", "名称"))
        amount = safe_float(get_first(row, "金额", "市值", "资产金额")) or 0.0
        bucket = resolve_holding_bucket(name, alias_map, ignored_holdings)
        if bucket == "__IGNORE__":
            continue
        if bucket:
            aggregated[bucket] = aggregated.get(bucket, 0.0) + amount
        else:
            unmapped.append({
                "name": name, "amount": round(amount, 2),
                "source": parse_multiselect(get_first(row, "来源")),
                "level_2": parse_multiselect(get_first(row, "Ⅱ级分类", "II级分类", "二级分类")),
            })
    return aggregated, unmapped


def build_holding_breakdown(
    rows: list[dict[str, Any]], alias_map: dict[str, str], ignored_holdings: set[str],
) -> dict[str, list[dict[str, Any]]]:
    breakdown: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        third_level = parse_multiselect(get_first(row, "Ⅲ级分类", "III级分类", "三级分类"))
        if "ERP" not in third_level:
            continue
        name = normalize_text(get_first(row, "项目名称", "标的", "名称"))
        amount = safe_float(get_first(row, "金额", "市值", "资产金额")) or 0.0
        bucket = resolve_holding_bucket(name, alias_map, ignored_holdings)
        if not bucket or bucket == "__IGNORE__":
            continue
        breakdown.setdefault(bucket, []).append({"name": name, "amount": round(amount, 2)})
    for items in breakdown.values():
        items.sort(key=lambda item: item["amount"], reverse=True)
    return breakdown


# ── Signal computation ───────────────────────────────────────

def latest_valid_row(rows: list[dict[str, Any]], required_aliases: list[str]) -> dict[str, Any]:
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        dt = parse_date(get_first(row, "日期"))
        if not dt:
            continue
        if not any(get_first(row, alias) not in (None, "", []) for alias in required_aliases):
            continue
        candidates.append((dt, row))
    if not candidates:
        raise ValueError("No valid dated rows found")
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def compute_erp_snapshot(rows: list[dict[str, Any]], thresholds: dict[str, float],
                         weights: dict[str, float]) -> dict[str, Any]:
    valid: list[tuple[datetime, float]] = []
    for row in rows:
        dt = parse_date(get_first(row, "日期"))
        premium = safe_float(get_first(row, "股权溢价指数"))
        if dt and premium is not None:
            valid.append((dt, premium))
    if not valid:
        raise ValueError("ERP table has no valid premium history")
    valid.sort(key=lambda item: item[0])
    latest_date, latest_value = valid[-1]
    history = [value for _, value in valid]
    percentile = round(sum(1 for v in history if v <= latest_value) / len(history) * 100, 2)
    aggressive_weight = piecewise_linear_weight(
        percentile,
        float(thresholds["low"]), float(thresholds["high"]),
        float(weights["low"]), float(weights["neutral"]), float(weights["high"]),
    )
    return {
        "date": latest_date.strftime("%Y-%m-%d"),
        "equity_premium": round(latest_value, 4),
        "percentile": percentile,
        "aggressive_weight": round(aggressive_weight, 4),
        "defensive_weight": round(1.0 - aggressive_weight, 4),
        "history_points": len(history),
    }


def compute_relative_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Read relative table including v3 expanded fields (KC50, HKTECH, GRO300)."""
    latest = latest_valid_row(rows, [
        "500建议", "1000建议", "创业板建议", "50建议",
        "科创50建议", "300价值建议", "300成长建议", "恒生科技建议",
    ])
    dt = parse_date(get_first(latest, "日期"))
    if not dt:
        raise ValueError("Relative row missing valid date")

    dated_rows: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        row_dt = parse_date(get_first(row, "日期"))
        if row_dt:
            dated_rows.append((row_dt, row))
    dated_rows.sort(key=lambda item: item[0])

    def compute_ratio_change(field_name: str, periods: int = 5) -> float | None:
        history: list[tuple[datetime, float]] = []
        for row_dt, r in dated_rows:
            value = safe_float(get_first(r, field_name))
            if value is not None:
                history.append((row_dt, value))
        if len(history) <= periods:
            return None
        latest_val = history[-1][1]
        base_val = history[-1 - periods][1]
        if base_val == 0:
            return None
        return round((latest_val / base_val - 1.0) * 100.0, 2)

    return {
        "date": dt.strftime("%Y-%m-%d"),
        "recommendations": {
            "zz500": normalize_text(get_first(latest, "500建议")),
            "zz1000": normalize_text(get_first(latest, "1000建议")),
            "cyb": normalize_text(get_first(latest, "创业板建议")),
            "sh50": normalize_text(get_first(latest, "50建议")),
            "kc50": normalize_text(get_first(latest, "科创50建议")),
            "val300": normalize_text(get_first(latest, "300价值建议")),
            "gro300": normalize_text(get_first(latest, "300成长建议")),
            "hstech": normalize_text(get_first(latest, "恒生科技建议")),
        },
        "ratios": {
            "zz500_ratio": safe_float(get_first(latest, "500/300比价")),
            "zz1000_ratio": safe_float(get_first(latest, "1000/300比价")),
            "cyb_ratio": safe_float(get_first(latest, "创业板/300比价")),
            "sh50_ratio": safe_float(get_first(latest, "50/创业板比价", "50/300比价")),
            "kc50_ratio": safe_float(get_first(latest, "科创50/上证50比价")),
            "val300_ratio": safe_float(get_first(latest, "300价值/成长比价")),
            "hstech_ratio": safe_float(get_first(latest, "恒生科技/恒生比价")),
        },
        "percentiles": {
            "zz500_percentile": safe_float(get_first(latest, "500分位")),
            "zz1000_percentile": safe_float(get_first(latest, "1000分位")),
            "cyb_percentile": safe_float(get_first(latest, "创业板分位")),
            "sh50_percentile": safe_float(get_first(latest, "50分位")),
            "kc50_percentile": safe_float(get_first(latest, "科创50分位")),
            "val300_percentile": safe_float(get_first(latest, "300价值分位")),
            "gro300_percentile": safe_float(get_first(latest, "300成长分位")),
            "hstech_percentile": safe_float(get_first(latest, "恒生科技分位")),
        },
        "deviations": {
            "zz500_deviation": safe_float(get_first(latest, "500偏离(%)")),
            "zz1000_deviation": safe_float(get_first(latest, "1000偏离(%)")),
            "cyb_deviation": safe_float(get_first(latest, "创业板偏离(%)")),
            "sh50_deviation": safe_float(get_first(latest, "50偏离(%)")),
            "kc50_deviation": safe_float(get_first(latest, "科创50偏离(%)")),
            "val300_deviation": safe_float(get_first(latest, "300价值偏离(%)")),
            "gro300_deviation": safe_float(get_first(latest, "300成长偏离(%)")),
            "hstech_deviation": safe_float(get_first(latest, "恒生科技偏离(%)")),
        },
        "changes": {
            "zz500_change_5d": compute_ratio_change("500/300比价", 5),
            "zz1000_change_5d": compute_ratio_change("1000/300比价", 5),
            "cyb_change_5d": compute_ratio_change("创业板/300比价", 5),
            "sh50_change_5d": compute_ratio_change("50/创业板比价", 5) or compute_ratio_change("50/300比价", 5),
            "kc50_change_5d": compute_ratio_change("科创50/上证50比价", 5),
            "val300_change_5d": compute_ratio_change("300价值/成长比价", 5),
            "hstech_change_5d": compute_ratio_change("恒生科技/恒生比价", 5),
        },
    }


# ── HSI ERP (optional, falls back to neutral) ────────────────

def compute_hsi_erp_snapshot(
    hsi_rows: list[dict[str, Any]] | None,
    hk_config: dict[str, Any],
) -> dict[str, Any]:
    """Compute HSI ERP snapshot from Feishu table. Falls back to neutral if unavailable."""
    if not hsi_rows:
        return _hsi_erp_neutral(hk_config)

    valid: list[tuple[datetime, float]] = []
    for row in hsi_rows:
        dt = parse_date(get_first(row, "日期"))
        premium = safe_float(get_first(row, "恒生ERP", "股权溢价指数", "ERP"))
        if dt and premium is not None:
            valid.append((dt, premium))

    if not valid:
        return _hsi_erp_neutral(hk_config)

    valid.sort(key=lambda item: item[0])
    latest_date, latest_value = valid[-1]
    history = [value for _, value in valid]
    percentile = round(sum(1 for v in history if v <= latest_value) / len(history) * 100, 2)

    thresholds = hk_config.get("percentile_thresholds", {"low": 40.0, "high": 60.0})
    weights = hk_config.get("aggressive_weights", {"low": 0.30, "neutral": 0.45, "high": 0.60})
    aggressive_weight = piecewise_linear_weight(
        percentile,
        float(thresholds["low"]), float(thresholds["high"]),
        float(weights["low"]), float(weights["neutral"]), float(weights["high"]),
    )
    return {
        "date": latest_date.strftime("%Y-%m-%d"),
        "equity_premium": round(latest_value, 4),
        "percentile": percentile,
        "aggressive_weight": round(aggressive_weight, 4),
        "defensive_weight": round(1.0 - aggressive_weight, 4),
        "history_points": len(history),
        "available": True,
    }


def _hsi_erp_neutral(hk_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": None,
        "equity_premium": None,
        "percentile": None,
        "aggressive_weight": 0.0,
        "defensive_weight": 1.0,
        "history_points": 0,
        "available": False,
        "message": "HSI ERP table unavailable; HK targets are capped at current HK exposure",
    }


# ── Trajectory overlay ───────────────────────────────────────

def trajectory_multiplier(deviation: float | None, change_5d: float | None,
                          trajectory_config: dict[str, Any]) -> tuple[float, str]:
    if not trajectory_config.get("enabled", True):
        return 1.0, "trajectory overlay disabled"
    if deviation is None or change_5d is None:
        return 1.0, "trajectory metrics unavailable"

    hot = trajectory_config.get("hot", {})
    if deviation >= float(hot.get("deviation_min", 4.0)) or change_5d >= float(hot.get("change_5d_min", 3.0)):
        return float(hot.get("multiplier", 0.6)), "trajectory hot"

    warm = trajectory_config.get("warm", {})
    if deviation >= float(warm.get("deviation_min", 2.0)) or change_5d >= float(warm.get("change_5d_min", 1.0)):
        return float(warm.get("multiplier", 0.8)), "trajectory warm"

    repair_strong = trajectory_config.get("repair_strong", {})
    if deviation <= float(repair_strong.get("deviation_max", -3.0)) and change_5d > float(repair_strong.get("change_5d_min", 0.0)):
        return float(repair_strong.get("multiplier", 1.15)), "trajectory repair strong"

    repair_light = trajectory_config.get("repair_light", {})
    if deviation <= float(repair_light.get("deviation_max", -1.0)) and change_5d > float(repair_light.get("change_5d_min", 0.0)):
        return float(repair_light.get("multiplier", 1.05)), "trajectory repair light"

    falling = trajectory_config.get("falling", {})
    if deviation < float(falling.get("deviation_max", 0.0)) and change_5d < float(falling.get("change_5d_max", 0.0)):
        return float(falling.get("multiplier", 0.85)), "trajectory falling"

    return 1.0, "trajectory neutral"


# ── Cross-market allocation ──────────────────────────────────

def compute_cross_market_allocation(
    hsi_erp: dict[str, Any],
    cross_config: dict[str, Any],
    current_hk_weight: float = 0.0,
) -> tuple[float, float]:
    """Returns (ashare_pool_pct, hkshare_pool_pct)."""
    hk_cap = float(cross_config.get("hk_pool_cap", 0.20))
    if not hsi_erp.get("available"):
        hk_pool = min(max(current_hk_weight, 0.0), hk_cap)
        return 1.0 - hk_pool, hk_pool

    hk_min = float(cross_config.get("hk_min_erp_percentile", 30))
    hk_full = float(cross_config.get("hk_full_erp_percentile", 50))
    hsi_pct = float(hsi_erp["percentile"])

    if hsi_pct <= hk_min:
        hk_pool = 0.0
    elif hsi_pct >= hk_full:
        hk_pool = hk_cap
    else:
        ratio = (hsi_pct - hk_min) / max(1e-9, hk_full - hk_min)
        hk_pool = hk_cap * ratio

    hk_pool = max(0.0, min(hk_pool, hk_cap))
    ashare_pool = 1.0 - hk_pool
    return ashare_pool, hk_pool


# ═══════════════════════════════════════════════════════════════
#  TARGET WEIGHT BUILDER (v3 — dual-pool)
# ═══════════════════════════════════════════════════════════════

def _build_pool_aggressive_buckets(
    bucket_keys: list[str],
    relative_snapshot: dict[str, Any],
    execution_config: dict[str, Any],
    current_holdings: dict[str, float],
    aggressive_alpha_total: float,
    bucket_metadata: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build aggressive bucket targets for a pool."""
    recs = relative_snapshot["recommendations"]
    base_weights = execution_config["alpha_base_weights"]
    caps = execution_config["alpha_bucket_caps"]
    multipliers = execution_config["recommendation_multipliers"]
    forced_exit_thresholds = execution_config.get("forced_exit_percentiles", {})
    reentry_thresholds = execution_config.get("aggressive_reentry_percentiles", {})
    reentry_min = float(execution_config.get("reentry_min_current_amount", 1000.0))
    trajectory_config = execution_config.get("trajectory_overlay", {})

    scores: dict[str, float] = {}
    for bucket in bucket_keys:
        base = float(base_weights.get(bucket, 0.3))
        rec = recs.get(bucket, "标配")
        # KC50 reverse logic
        if bucket == "kc50":
            rec = _kc50_rec_to_bucket_rec(rec)
        scores[bucket] = base * recommendation_multiplier(rec, multipliers)

    local_weights = normalize_to_weights(scores)

    targets: dict[str, dict[str, Any]] = {}
    for bucket, local_w in local_weights.items():
        percentile = relative_snapshot["percentiles"].get(f"{bucket}_percentile")
        deviation = relative_snapshot.get("deviations", {}).get(f"{bucket}_deviation")
        change_5d = relative_snapshot.get("changes", {}).get(f"{bucket}_change_5d")
        cur_amount = float(current_holdings.get(bucket, 0.0))

        force_threshold = forced_exit_thresholds.get(bucket)
        forced_exit = (
            force_threshold is not None and percentile is not None
            and float(percentile) >= float(force_threshold)
        )
        reentry_threshold = reentry_thresholds.get(bucket)
        reentry_blocked = (
            reentry_threshold is not None and percentile is not None
            and cur_amount <= reentry_min
            and float(percentile) > float(reentry_threshold)
        )
        traj_mult, traj_reason = trajectory_multiplier(deviation, change_5d, trajectory_config)

        tw = aggressive_alpha_total * local_w
        tw = min(tw, float(caps.get(bucket, 1.0)))
        if forced_exit:
            tw = 0.0
        elif reentry_blocked:
            tw = 0.0
        else:
            tw *= traj_mult

        meta = bucket_metadata.get(bucket, {})
        targets[bucket] = {
            "bucket": bucket,
            "label": meta.get("label", bucket),
            "sleeve": meta.get("sleeve", "aggressive"),
            "pool": meta.get("pool", "ashare"),
            "signal": _rec_for_bucket(bucket, recs),
            "current_percentile": round(float(percentile), 2) if percentile is not None else None,
            "current_deviation": round(float(deviation), 2) if deviation is not None else None,
            "change_5d": round(float(change_5d), 2) if change_5d is not None else None,
            "forced_exit_threshold": float(force_threshold) if force_threshold is not None else None,
            "forced_exit": forced_exit,
            "reentry_threshold": float(reentry_threshold) if reentry_threshold is not None else None,
            "reentry_blocked": reentry_blocked,
            "trajectory_multiplier": round(float(traj_mult), 2),
            "trajectory_reason": traj_reason,
            "target_weight": round(tw, 4),
        }
    return targets


def _rec_for_bucket(bucket: str, recs: dict[str, str]) -> str:
    if bucket == "kc50":
        return _kc50_rec_to_bucket_rec(recs.get(bucket, "标配"))
    return recs.get(bucket, "标配")


def _style_pair_budget_ratio(val300_pct: float | None, style_config: dict[str, Any]) -> float:
    """Returns fraction of style pair budget allocated to VAL300 (rest goes to GRO300)."""
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
        return val_w  # value cheap → most to VAL300
    if val300_pct >= high:
        return 1.0 - gro_w  # growth cheap → most to GRO300
    # linear interpolation
    ratio = (val300_pct - low) / max(1e-9, high - low)
    return val_w + ((1.0 - gro_w) - val_w) * ratio


def _balance_target_weights(targets: dict[str, dict[str, Any]], core_bucket: str = "hs300") -> None:
    total = sum(float(item.get("target_weight", 0.0)) for item in targets.values())
    diff = 1.0 - total
    core = targets.get(core_bucket)
    if core is None or abs(diff) < 0.00005:
        return
    core["target_weight"] = round(max(0.0, float(core.get("target_weight", 0.0)) + diff), 4)


def build_target_weights(
    erp_snapshot: dict[str, Any],
    hsi_erp_snapshot: dict[str, Any],
    relative_snapshot: dict[str, Any],
    execution_config: dict[str, Any],
    current_holdings: dict[str, float],
) -> dict[str, dict[str, Any]]:
    """Build all target weights for both pools (v3 expanded)."""
    thresholds = execution_config["percentile_thresholds"]
    recs = relative_snapshot["recommendations"]
    caps = execution_config["alpha_bucket_caps"]
    multipliers = execution_config["recommendation_multipliers"]
    base_weights = execution_config["alpha_base_weights"]
    alpha_budget_w = execution_config["alpha_budget_weights"]
    style_config = execution_config.get("style_pair", {})
    forced_exit_thresholds = execution_config.get("forced_exit_percentiles", {})
    reentry_thresholds = execution_config.get("aggressive_reentry_percentiles", {})
    reentry_min = float(execution_config.get("reentry_min_current_amount", 1000.0))
    trajectory_config = execution_config.get("trajectory_overlay", {})
    bucket_meta = execution_config.get("bucket_metadata", {})

    # ── Cross-market ──
    cross_config = execution_config.get("cross_market", {})
    managed_total = sum(float(value) for value in current_holdings.values())
    current_hk_weight = 0.0
    if managed_total > 0:
        current_hk_weight = (
            float(current_holdings.get("hsi", 0.0)) + float(current_holdings.get("hstech", 0.0))
        ) / managed_total
    ashare_pool, hk_pool = compute_cross_market_allocation(hsi_erp_snapshot, cross_config, current_hk_weight)

    # ── A-share: ERP-driven sleeve split ──
    ashare_aggressive = float(erp_snapshot["aggressive_weight"])
    ashare_defensive = 1.0 - ashare_aggressive

    ashare_alpha_budget = piecewise_linear_weight(
        float(erp_snapshot["percentile"]),
        float(thresholds["low"]), float(thresholds["high"]),
        float(alpha_budget_w["low"]), float(alpha_budget_w["neutral"]), float(alpha_budget_w["high"]),
    )
    ashare_alpha_budget = max(0.0, min(ashare_alpha_budget, 0.45))

    # ── HK: ERP-driven sleeve split ──
    hk_config = execution_config.get("hk_erp", {})
    hk_thresholds = hk_config.get("percentile_thresholds", {"low": 40.0, "high": 60.0})
    hk_weights = hk_config.get("aggressive_weights", {"low": 0.30, "neutral": 0.45, "high": 0.60})
    hk_aggressive = float(hsi_erp_snapshot["aggressive_weight"])

    targets: dict[str, dict[str, Any]] = {}

    # ═══ A-share defensive ═══
    ashare_def_total = ashare_pool * ashare_defensive
    def_alpha_total = ashare_def_total * ashare_alpha_budget

    # -- Style pair (VAL300 / GRO300) --
    style_budget_ratio = float(style_config.get("budget_ratio", 0.30))
    style_pair_budget = def_alpha_total * style_budget_ratio
    val300_pct = relative_snapshot["percentiles"].get("val300_percentile")
    val300_frac = _style_pair_budget_ratio(val300_pct, style_config)

    def _style_bucket(bucket: str, tw: float, rec_key: str) -> dict[str, Any]:
        pct = relative_snapshot["percentiles"].get(f"{bucket}_percentile")
        dev = relative_snapshot.get("deviations", {}).get(f"{bucket}_deviation")
        chg = relative_snapshot.get("changes", {}).get(f"{bucket}_change_5d")
        cur_amt = float(current_holdings.get(bucket, 0.0))
        ft = forced_exit_thresholds.get(bucket)
        fe = ft is not None and pct is not None and float(pct) >= float(ft)
        rt = reentry_thresholds.get(bucket)
        rb = rt is not None and pct is not None and cur_amt <= reentry_min and float(pct) > float(rt)
        tm, tr = trajectory_multiplier(dev, chg, trajectory_config)
        tw = min(tw, float(caps.get(bucket, 1.0)))
        if fe:
            tw = 0.0
        elif rb:
            tw = 0.0
        else:
            tw *= tm
        meta = bucket_meta.get(bucket, {})
        return {
            "bucket": bucket, "label": meta.get("label", bucket),
            "sleeve": meta.get("sleeve", "defensive"), "pool": meta.get("pool", "ashare"),
            "signal": recs.get(rec_key, "标配"),
            "current_percentile": round(float(pct), 2) if pct is not None else None,
            "current_deviation": round(float(dev), 2) if dev is not None else None,
            "change_5d": round(float(chg), 2) if chg is not None else None,
            "forced_exit_threshold": float(ft) if ft is not None else None,
            "forced_exit": fe,
            "reentry_threshold": float(rt) if rt is not None else None,
            "reentry_blocked": rb,
            "trajectory_multiplier": round(float(tm), 2),
            "trajectory_reason": tr,
            "target_weight": round(tw, 4),
        }

    val300_tw = style_pair_budget * val300_frac
    gro300_tw = style_pair_budget * (1.0 - val300_frac)
    targets["val300"] = _style_bucket("val300", val300_tw, "val300")
    targets["gro300"] = _style_bucket("gro300", gro300_tw, "gro300")

    # -- SH50 (defensive alpha) --
    sh50_percentile = relative_snapshot["percentiles"].get("sh50_percentile")
    sh50_ft = forced_exit_thresholds.get("sh50")
    sh50_exit_threshold = 100.0 - float(sh50_ft) if sh50_ft is not None else None
    sh50_fe = (
        sh50_exit_threshold is not None and sh50_percentile is not None
        and float(sh50_percentile) <= sh50_exit_threshold
    )

    sh50_tw = def_alpha_total * (1.0 - style_budget_ratio)
    sh50_signal = recs.get("sh50") or "标配"
    sh50_tw *= recommendation_multiplier(sh50_signal, multipliers)
    sh50_tw = min(sh50_tw, float(caps.get("sh50", 0.18)))
    if sh50_fe:
        sh50_tw = 0.0

    meta_sh50 = bucket_meta.get("sh50", {})
    targets["sh50"] = {
        "bucket": "sh50", "label": meta_sh50.get("label", "防守价值"),
        "sleeve": "defensive", "pool": "ashare",
        "signal": sh50_signal,
        "current_percentile": round(float(sh50_percentile), 2) if sh50_percentile is not None else None,
        "forced_exit_threshold": sh50_exit_threshold,
        "forced_exit_operator": "<=",
        "forced_exit": sh50_fe,
        "target_weight": round(sh50_tw, 4),
    }

    # ═══ A-share aggressive ═══
    ashare_agg_total = ashare_pool * ashare_aggressive
    agg_alpha_total = ashare_agg_total * ashare_alpha_budget
    agg_buckets = _build_pool_aggressive_buckets(
        ["cyb", "zz500", "zz1000", "kc50"],
        relative_snapshot, execution_config, current_holdings,
        agg_alpha_total, bucket_meta,
    )
    targets.update(agg_buckets)

    # -- HS300 core (defensive residual + aggressive passive) --
    used_def = sum(
        float(targets[key]["target_weight"])
        for key in ("sh50", "val300", "gro300")
        if key in targets
    )
    agg_used = sum(
        float(item["target_weight"])
        for item in targets.values()
        if item.get("pool") == "ashare" and item.get("sleeve") == "aggressive"
    )
    hs300_tw = max(0.0, ashare_def_total - used_def) + max(0.0, ashare_agg_total - agg_used)
    meta_hs = bucket_meta.get("hs300", {})
    targets["hs300"] = {
        "bucket": "hs300", "label": meta_hs.get("label", "沪深300"),
        "sleeve": "defensive", "pool": "ashare",
        "signal": "core",
        "target_weight": round(hs300_tw, 4),
    }

    # ═══ HK pool ═══
    meta_hsi = bucket_meta.get("hsi", {})
    meta_ht = bucket_meta.get("hstech", {})
    if not hsi_erp_snapshot.get("available"):
        hsi_tw = 0.0
        hstech_tw = 0.0
        if managed_total > 0 and current_hk_weight > 0:
            scale = hk_pool / current_hk_weight
            hsi_tw = float(current_holdings.get("hsi", 0.0)) / managed_total * scale
            hstech_tw = float(current_holdings.get("hstech", 0.0)) / managed_total * scale
        targets["hsi"] = {
            "bucket": "hsi", "label": meta_hsi.get("label", "恒生指数"),
            "sleeve": "defensive", "pool": "hkshare",
            "signal": "hold-no-hsi-erp",
            "target_weight": round(hsi_tw, 4),
        }
        targets["hstech"] = {
            "bucket": "hstech", "label": meta_ht.get("label", "恒生科技"),
            "sleeve": "aggressive", "pool": "hkshare",
            "signal": "hold-no-hsi-erp",
            "target_weight": round(hstech_tw, 4),
            "trajectory_multiplier": 1.0,
            "trajectory_reason": "HSI ERP unavailable; no new HK exposure",
        }
        _balance_target_weights(targets)
        return targets

    hk_def_total = hk_pool * (1.0 - hk_aggressive)
    targets["hsi"] = {
        "bucket": "hsi", "label": meta_hsi.get("label", "恒生指数"),
        "sleeve": "defensive", "pool": "hkshare",
        "signal": "core",
        "target_weight": round(hk_def_total, 4),
    }

    hk_agg_total = hk_pool * hk_aggressive
    # HKTECH: with forced exit / reentry / trajectory
    hstech_pct = relative_snapshot["percentiles"].get("hstech_percentile")
    hstech_dev = relative_snapshot.get("deviations", {}).get("hstech_deviation")
    hstech_chg = relative_snapshot.get("changes", {}).get("hstech_change_5d")
    hstech_cur = float(current_holdings.get("hstech", 0.0))
    hstech_ft = forced_exit_thresholds.get("hstech")
    hstech_fe = hstech_ft is not None and hstech_pct is not None and float(hstech_pct) >= float(hstech_ft)
    hstech_rt = reentry_thresholds.get("hstech")
    hstech_rb = hstech_rt is not None and hstech_pct is not None and hstech_cur <= reentry_min and float(hstech_pct) > float(hstech_rt)
    hstech_tm, hstech_tr = trajectory_multiplier(hstech_dev, hstech_chg, trajectory_config)

    hstech_tw = hk_agg_total
    hstech_tw = min(hstech_tw, float(caps.get("hstech", 0.08)))
    if hstech_fe:
        hstech_tw = 0.0
    elif hstech_rb:
        hstech_tw = 0.0
    else:
        hstech_tw *= hstech_tm

    targets["hstech"] = {
        "bucket": "hstech", "label": meta_ht.get("label", "恒生科技"),
        "sleeve": "aggressive", "pool": "hkshare",
        "signal": recs.get("hstech", "标配"),
        "current_percentile": round(float(hstech_pct), 2) if hstech_pct is not None else None,
        "current_deviation": round(float(hstech_dev), 2) if hstech_dev is not None else None,
        "change_5d": round(float(hstech_chg), 2) if hstech_chg is not None else None,
        "forced_exit_threshold": float(hstech_ft) if hstech_ft is not None else None,
        "forced_exit": hstech_fe,
        "reentry_threshold": float(hstech_rt) if hstech_rt is not None else None,
        "reentry_blocked": hstech_rb,
        "trajectory_multiplier": round(float(hstech_tm), 2),
        "trajectory_reason": hstech_tr,
        "target_weight": round(hstech_tw, 4),
    }

    _balance_target_weights(targets)
    return targets


# ── Rebalance plan ───────────────────────────────────────────

def build_rebalance_plan(
    current_holdings: dict[str, float],
    unmapped_holdings: list[dict[str, Any]],
    targets: dict[str, dict[str, Any]],
    holding_breakdown: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    managed_total = round(sum(current_holdings.values()), 2)
    unmapped_total = round(sum(item["amount"] for item in unmapped_holdings), 2)
    total_erp_amount = round(managed_total + unmapped_total, 2)

    positions: list[dict[str, Any]] = []
    for bucket, target in targets.items():
        current_amount = round(current_holdings.get(bucket, 0.0), 2)
        current_weight = round(current_amount / managed_total, 4) if managed_total > 0 else 0.0
        target_amount = round(managed_total * float(target["target_weight"]), 2)
        delta_amount = round(target_amount - current_amount, 2)
        if delta_amount > 0:
            action = "buy"
        elif delta_amount < 0:
            action = "sell"
        else:
            action = "hold"
        positions.append({
            **target,
            "current_amount": current_amount,
            "current_weight": current_weight,
            "target_amount": target_amount,
            "delta_amount": delta_amount,
            "action": action,
            "holding_breakdown": (holding_breakdown or {}).get(bucket, []),
        })

    positions.sort(key=lambda item: (
        {"ashare": 0, "hkshare": 1}.get(item.get("pool", ""), 2),
        {"defensive": 0, "aggressive": 1}.get(item.get("sleeve", ""), 2),
        item.get("bucket", ""),
    ))
    target_weight_sum = sum(float(item.get("target_weight", 0.0)) for item in positions)

    return {
        "total_erp_amount": total_erp_amount,
        "managed_amount": managed_total,
        "unmapped_amount": unmapped_total,
        "managed_position_count": len(current_holdings),
        "unmapped_position_count": len(unmapped_holdings),
        "target_weight_sum": round(target_weight_sum, 6),
        "ashare_pool": round(targets.get("hs300", {}).get("target_weight", 0) + sum(
            float(t.get("target_weight", 0)) for k, t in targets.items()
            if t.get("pool") == "ashare" and k != "hs300"
        ), 4),
        "hkshare_pool": round(sum(
            float(t.get("target_weight", 0)) for k, t in targets.items()
            if t.get("pool") == "hkshare"
        ), 4),
        "positions": positions,
        "unmapped_holdings": unmapped_holdings,
    }


# ── Output ───────────────────────────────────────────────────

def latest_asset_update(rows: list[dict[str, Any]]) -> datetime | None:
    dates: list[datetime] = []
    for row in rows:
        third_level = parse_multiselect(get_first(row, "Ⅲ级分类", "III级分类", "三级分类"))
        if "ERP" not in third_level:
            continue
        dt = parse_date(row.get("_last_modified_time") or row.get("_created_time"))
        if dt:
            dates.append(dt)
    return max(dates) if dates else None


def _snapshot_date(snapshot: dict[str, Any]) -> datetime | None:
    return parse_date(snapshot.get("date"))


def build_data_health(
    erp_snapshot: dict[str, Any],
    hsi_erp_snapshot: dict[str, Any],
    relative_snapshot: dict[str, Any],
    asset_rows: list[dict[str, Any]],
    execution_config: dict[str, Any],
    as_of: datetime,
    *,
    require_asset_timestamp: bool,
) -> dict[str, Any]:
    config = execution_config.get("data_quality", {})
    max_staleness = config.get("max_staleness_days", {})
    max_gap_days = int(config.get("max_signal_date_gap_days", 10))
    dates = {
        "erp": _snapshot_date(erp_snapshot),
        "relative": _snapshot_date(relative_snapshot),
        "hsi_erp": _snapshot_date(hsi_erp_snapshot),
        "asset": latest_asset_update(asset_rows),
    }
    limits = {
        "erp": int(max_staleness.get("erp", 14)),
        "relative": int(max_staleness.get("relative", 3)),
        "hsi_erp": int(max_staleness.get("hsi_erp", 14)),
        "asset": int(max_staleness.get("asset", 14)),
    }
    errors: list[str] = []
    warnings: list[str] = []
    ages: dict[str, int | None] = {}

    for name in ("erp", "relative"):
        dt = dates[name]
        if dt is None:
            errors.append(f"{name} date is missing")
            ages[name] = None
            continue
        age = (as_of.date() - dt.date()).days
        ages[name] = age
        if age < 0:
            errors.append(f"{name} date {dt.date()} is after as_of {as_of.date()}")
        elif age > limits[name]:
            errors.append(f"{name} data is stale: {age} days > {limits[name]}")

    if dates["erp"] is not None and dates["relative"] is not None:
        gap = abs((dates["relative"].date() - dates["erp"].date()).days)
        if gap > max_gap_days:
            errors.append(f"ERP/relative date gap is too large: {gap} days > {max_gap_days}")

    hsi_dt = dates["hsi_erp"]
    if hsi_erp_snapshot.get("available"):
        if hsi_dt is None:
            errors.append("hsi_erp date is missing")
            ages["hsi_erp"] = None
        else:
            age = (as_of.date() - hsi_dt.date()).days
            ages["hsi_erp"] = age
            if age < 0:
                errors.append(f"hsi_erp date {hsi_dt.date()} is after as_of {as_of.date()}")
            elif age > limits["hsi_erp"]:
                errors.append(f"hsi_erp data is stale: {age} days > {limits['hsi_erp']}")
    else:
        ages["hsi_erp"] = None
        warnings.append("HSI ERP unavailable; HK targets are capped at current HK exposure")

    asset_dt = dates["asset"]
    if asset_dt is None:
        ages["asset"] = None
        message = "asset record update timestamp is missing"
        if require_asset_timestamp:
            errors.append(message)
        else:
            warnings.append(message)
    else:
        age = (as_of.date() - asset_dt.date()).days
        ages["asset"] = age
        if age < 0:
            errors.append(f"asset update date {asset_dt.date()} is after as_of {as_of.date()}")
        elif age > limits["asset"]:
            errors.append(f"asset data is stale: {age} days > {limits['asset']}")

    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "dates": {key: value.strftime("%Y-%m-%d") if value else None for key, value in dates.items()},
        "ages_days": ages,
        "max_signal_date_gap_days": max_gap_days,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def validate_execution_payload(payload: dict[str, Any]) -> None:
    portfolio = payload.get("portfolio", {})
    positions = portfolio.get("positions", [])
    total_weight = sum(float(item.get("target_weight", 0.0)) for item in positions)
    tolerance = float(
        payload.get("inputs", {})
        .get("execution_config", {})
        .get("data_quality", {})
        .get("target_weight_tolerance", 0.0015)
    )
    errors: list[str] = []
    if abs(total_weight - 1.0) > tolerance:
        errors.append(f"target weights must sum to 1.0, got {total_weight:.6f}")
    errors.extend(payload.get("signals", {}).get("data_health", {}).get("errors", []))
    if errors:
        raise RuntimeError("ERP execution validation failed: " + "; ".join(errors))


def save_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_daily_summary() -> Path | None:
    if not DEFAULT_RENDER_SCRIPT.exists():
        return None
    completed = subprocess.run(
        [sys.executable, str(DEFAULT_RENDER_SCRIPT)],
        cwd=DEFAULT_RENDER_SCRIPT.parent.parent,
        text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Failed to render daily summary: {completed.stderr.strip() or completed.stdout.strip()}")
    output_text = (completed.stdout or "").strip()
    if not output_text:
        return None
    return Path(output_text.splitlines()[-1].strip())


def print_summary(payload: dict[str, Any]) -> None:
    erp = payload["signals"]["erp"]
    hsi = payload["signals"].get("hsi_erp", {})
    relative = payload["signals"]["relative"]
    portfolio = payload["portfolio"]

    print("=" * 60)
    print("ERP Execution Cloud Plan v3")
    print("=" * 60)
    print(f"A-share ERP: {erp['date']}  premium={erp['equity_premium']:.2f}  pct={erp['percentile']:.2f}%  agg={erp['aggressive_weight']:.2%}")
    if hsi.get("available"):
        print(f"HK     ERP: {hsi['date']}  premium={hsi['equity_premium']:.2f}  pct={hsi['percentile']:.2f}%  agg={hsi['aggressive_weight']:.2%}")
    else:
        print(f"HK     ERP: {hsi.get('message', 'unavailable')}")

    pool_ashare = portfolio.get("ashare_pool", 0)
    pool_hk = portfolio.get("hkshare_pool", 0)
    print(f"Pool split: A-share={pool_ashare:.2%}  HK={pool_hk:.2%}")
    print(f"Managed ERP capital: {portfolio['managed_amount']:,.2f}")
    print()

    for item in portfolio["positions"]:
        pool_tag = f"[{item.get('pool', '?')}]"
        sleeve_tag = item.get("sleeve", "")
        extra = []
        if item.get("forced_exit"):
            extra.append(f"FORCED EXIT (pct={item.get('current_percentile')})")
        if item.get("reentry_blocked"):
            extra.append(f"REENTRY BLOCKED (pct={item.get('current_percentile')}>{item.get('reentry_threshold')})")
        if item.get("trajectory_reason", "").startswith("trajectory") and item["trajectory_reason"] != "trajectory neutral":
            extra.append(f"traj={item['trajectory_reason']} ×{item['trajectory_multiplier']}")
        extras = " | ".join(extra) if extra else ""
        print(
            f"  {pool_tag} {item['sleeve']:10s} {item['label']:16s} "
            f"cur={item['current_amount']:>10,.2f}  →  tgt={item['target_amount']:>10,.2f}  "
            f"({item['action']:4s} {item['delta_amount']:>+10,.2f})"
            + (f"  [{extras}]" if extras else "")
        )


# ── Argument parsing ─────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ERP execution plan via Feishu OpenAPI (v3)")
    parser.add_argument("--erp-app-token", default=os.environ.get("ERP_EXEC_ERP_APP_TOKEN", DEFAULT_ERP_APP_TOKEN))
    parser.add_argument("--erp-table-id", default=os.environ.get("ERP_EXEC_ERP_TABLE_ID", DEFAULT_ERP_TABLE_ID))
    parser.add_argument("--relative-app-token", default=os.environ.get("ERP_EXEC_RELATIVE_APP_TOKEN", DEFAULT_RELATIVE_APP_TOKEN))
    parser.add_argument("--relative-table-id", default=os.environ.get("ERP_EXEC_RELATIVE_TABLE_ID", DEFAULT_RELATIVE_TABLE_ID))
    parser.add_argument("--asset-app-token", default=os.environ.get("ERP_EXEC_ASSET_APP_TOKEN", DEFAULT_ASSET_APP_TOKEN))
    parser.add_argument("--asset-table-id", default=os.environ.get("ERP_EXEC_ASSET_TABLE_ID", DEFAULT_ASSET_TABLE_ID))
    parser.add_argument("--hsi-erp-app-token", default=os.environ.get("ERP_EXEC_HSI_ERP_APP_TOKEN", DEFAULT_HSI_ERP_APP_TOKEN))
    parser.add_argument("--hsi-erp-table-id", default=os.environ.get("ERP_EXEC_HSI_ERP_TABLE_ID", DEFAULT_HSI_ERP_TABLE_ID))
    parser.add_argument("--execution-config-path", default=os.environ.get("ERP_EXECUTION_CONFIG_PATH", str(DEFAULT_EXECUTION_CONFIG_PATH)))
    parser.add_argument("--output", default=os.environ.get("ERP_EXECUTION_OUTPUT_PATH", str(DEFAULT_OUTPUT)))
    parser.add_argument("--as-of", default=os.environ.get("ERP_EXECUTION_AS_OF", ""))
    parser.add_argument("--page-size", type=int, default=500)
    return parser.parse_args()


# ── Main ─────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    as_of = parse_date(args.as_of) if args.as_of else datetime.now(SHANGHAI_TZ)
    if as_of is None:
        raise ValueError(f"Invalid --as-of date: {args.as_of}")

    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    reader = FeishuBitableReader(app_id, app_secret)

    execution_config = sanitize_structure(json.loads(Path(args.execution_config_path).read_text(encoding="utf-8")))

    erp_rows = reader.list_all_records(args.erp_app_token, args.erp_table_id, args.page_size)
    relative_rows = reader.list_all_records(args.relative_app_token, args.relative_table_id, args.page_size)
    asset_rows = reader.list_all_records(args.asset_app_token, args.asset_table_id, args.page_size)

    # HSI ERP (optional)
    hsi_rows: list[dict[str, Any]] | None = None
    if args.hsi_erp_app_token and args.hsi_erp_table_id:
        try:
            hsi_rows = reader.list_all_records(args.hsi_erp_app_token, args.hsi_erp_table_id, args.page_size)
        except Exception:
            hsi_rows = None

    erp_snapshot = compute_erp_snapshot(erp_rows, execution_config["percentile_thresholds"], execution_config["aggressive_weights"])
    hsi_erp_snapshot = compute_hsi_erp_snapshot(hsi_rows, execution_config.get("hk_erp", {}))
    relative_snapshot = compute_relative_snapshot(relative_rows)

    alias_map = {normalize_text(k): normalize_text(v) for k, v in execution_config.get("holding_alias_map", {}).items()}
    ignored_holdings = {normalize_text(item) for item in execution_config.get("ignored_erp_holdings", [])}
    current_holdings, unmapped_holdings = aggregate_current_holdings(asset_rows, alias_map, ignored_holdings)
    holding_breakdown = build_holding_breakdown(asset_rows, alias_map, ignored_holdings)

    targets = build_target_weights(erp_snapshot, hsi_erp_snapshot, relative_snapshot, execution_config, current_holdings)
    portfolio = build_rebalance_plan(current_holdings, unmapped_holdings, targets, holding_breakdown)
    data_health = build_data_health(
        erp_snapshot,
        hsi_erp_snapshot,
        relative_snapshot,
        asset_rows,
        execution_config,
        as_of,
        require_asset_timestamp=True,
    )

    payload = {
        "version": "3.0",
        "signal_type": "erp_execution_plan",
        "generated_at": datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds"),
        "inputs": {
            "mode": "cloud_openapi",
            "erp_table": {"app_token": args.erp_app_token, "table_id": args.erp_table_id},
            "relative_table": {"app_token": args.relative_app_token, "table_id": args.relative_table_id},
            "asset_table": {"app_token": args.asset_app_token, "table_id": args.asset_table_id},
            "hsi_erp_table": {"app_token": args.hsi_erp_app_token, "table_id": args.hsi_erp_table_id} if args.hsi_erp_app_token else None,
            "as_of": as_of.strftime("%Y-%m-%d"),
            "execution_config_path": str(Path(args.execution_config_path).resolve()),
            "execution_config": execution_config,
        },
        "signals": {
            "erp": erp_snapshot,
            "hsi_erp": hsi_erp_snapshot,
            "relative": relative_snapshot,
            "data_health": data_health,
        },
        "portfolio": portfolio,
    }

    validate_execution_payload(payload)
    output_path = Path(args.output).resolve()
    save_output(output_path, payload)
    summary_path = render_daily_summary()
    print_summary(payload)
    print(f"\nSaved to: {output_path}")
    if summary_path is not None:
        print(f"Daily summary: {summary_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
