#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cloud-friendly ERP execution workflow.

Reads the required Feishu Bitable tables directly through OpenAPI instead of the
local lark-cli login state, then generates the same execution plan artifact used
by the local ERP execution workflow.
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


DEFAULT_ERP_APP_TOKEN = "KfaSbpRdiaYFdWsCTRfcWpocnbd"
DEFAULT_ERP_TABLE_ID = "tblRAs2p4woXE1ig"
DEFAULT_RELATIVE_APP_TOKEN = "POghbC154ablpxs20USc6veDnlh"
DEFAULT_RELATIVE_TABLE_ID = "tblnsUexqsEiLZs9"
DEFAULT_ASSET_APP_TOKEN = "TiVJb2a5GaRiZTsoeXFcO6BCn8e"
DEFAULT_ASSET_TABLE_ID = "tbl1qLL1iXMykQRd"

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "erp_execution_plan.json"
DEFAULT_EXECUTION_CONFIG_PATH = Path(__file__).resolve().parent / "erp_execution_config.json"
DEFAULT_RENDER_SCRIPT = Path(__file__).resolve().parent / "render_erp_daily_summary_v4.py"

BASE_URL = "https://open.feishu.cn/open-apis"
AUTH_URL = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

MOJIBAKE_MAP = {
    "鏍囬厤": "标配",
    "瓒呴厤": "超配",
    "浣庨厤": "低配",
    "寮虹儓瓒呴厤": "强烈超配",
    "寮虹儓浣庨厤": "强烈低配",
    "娌繁300": "沪深300",
    "涓婅瘉50": "上证50",
    "鍒涗笟鏉": "创业板",
    "涓瘉500": "中证500",
    "涓瘉1000": "中证1000",
    "绾㈠埄ETF": "红利ETF",
    "鍒涗笟鏉垮寮": "创业板增强",
    "鍒涗笟鏉挎寚": "创业板指",
    "涓婅瘉50ETF": "上证50ETF",
    "涓瘉500ETF": "中证500ETF",
    "涓瘉1000ETF": "中证1000ETF",
    "鍗佸勾鏈熷浗鍊篍TF": "十年期国债ETF",
    "鎭掔敓娑堣垂ETF": "恒生消费ETF",
    "绉戝垱50ETF": "科创50ETF",
    "鏃ユ湡": "日期",
    "鑲℃潈婧环鎸囨暟": "股权溢价指数",
    "500寤鸿": "500建议",
    "1000寤鸿": "1000建议",
    "鍒涗笟鏉垮缓璁": "创业板建议",
    "50寤鸿": "50建议",
    "500/300姣斾环": "500/300比价",
    "1000/300姣斾环": "1000/300比价",
    "鍒涗笟鏉?300姣斾环": "创业板/300比价",
    "鍒涗笟鏉300姣斾环": "创业板/300比价",
    "50/鍒涗笟鏉挎瘮浠": "50/创业板比价",
    "50/300姣斾环": "50/300比价",
    "300浠峰€?鎴愰暱姣斾环": "300价值/成长比价",
    "300浠峰€煎垎浣": "300价值分位",
    "300浠峰€煎缓璁": "300价值建议",
    "椤圭洰鍚嶇О": "项目名称",
    "閲戦": "金额",
    "鏉ユ簮": "来源",
    "鈪＄骇鍒嗙被": "Ⅱ级分类",
    "II绾у垎绫": "Ⅱ级分类",
    "浜岀骇鍒嗙被": "二级分类",
    "鈪㈢骇鍒嗙被": "Ⅲ级分类",
    "III绾у垎绫": "Ⅲ级分类",
    "涓夌骇鍒嗙被": "三级分类",
}

BUCKET_METADATA = {
    "hs300": {"label": "沪深300", "sleeve": "defensive"},
    "sh50": {"label": "防守价值（上证50/红利）", "sleeve": "defensive"},
    "cyb": {"label": "创业板", "sleeve": "aggressive"},
    "zz500": {"label": "中证500", "sleeve": "aggressive"},
    "zz1000": {"label": "中证1000", "sleeve": "aggressive"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ERP execution plan via Feishu OpenAPI")
    parser.add_argument("--erp-app-token", default=os.environ.get("ERP_EXEC_ERP_APP_TOKEN", DEFAULT_ERP_APP_TOKEN))
    parser.add_argument("--erp-table-id", default=os.environ.get("ERP_EXEC_ERP_TABLE_ID", DEFAULT_ERP_TABLE_ID))
    parser.add_argument(
        "--relative-app-token",
        default=os.environ.get("ERP_EXEC_RELATIVE_APP_TOKEN", DEFAULT_RELATIVE_APP_TOKEN),
    )
    parser.add_argument(
        "--relative-table-id",
        default=os.environ.get("ERP_EXEC_RELATIVE_TABLE_ID", DEFAULT_RELATIVE_TABLE_ID),
    )
    parser.add_argument("--asset-app-token", default=os.environ.get("ERP_EXEC_ASSET_APP_TOKEN", DEFAULT_ASSET_APP_TOKEN))
    parser.add_argument("--asset-table-id", default=os.environ.get("ERP_EXEC_ASSET_TABLE_ID", DEFAULT_ASSET_TABLE_ID))
    parser.add_argument(
        "--execution-config-path",
        default=os.environ.get("ERP_EXECUTION_CONFIG_PATH", str(DEFAULT_EXECUTION_CONFIG_PATH)),
    )
    parser.add_argument("--output", default=os.environ.get("ERP_EXECUTION_OUTPUT_PATH", str(DEFAULT_OUTPUT)))
    parser.add_argument("--page-size", type=int, default=500)
    return parser.parse_args()


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
        return [text for text in texts if text]
    if isinstance(value, dict):
        for key in ("text", "name", "value", "display_value", "formatted_value", "title"):
            if key in value:
                return cell_texts(value[key])
        return []
    text = normalize_text(value)
    return [text] if text else []


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
        return {
            "Authorization": f"Bearer {self._tenant_token}",
            "Content-Type": "application/json",
        }

    def list_all_records(self, app_token: str, table_id: str, page_size: int = 500) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {"page_size": min(page_size, 500)}
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
                records.append(fields)

            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break

        return records


def recommendation_multiplier(text: str | None, mapping: dict[str, float]) -> float:
    if not text:
        return 1.0
    return float(mapping.get(normalize_text(text), 1.0))


def piecewise_linear_weight(percentile: float, low_threshold: float, high_threshold: float, low_weight: float, neutral_weight: float, high_weight: float) -> float:
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


def resolve_holding_bucket(name: str, alias_lookup: dict[str, str], ignored_lookup: set[str]) -> str | None:
    fixed_name = normalize_text(name)
    if fixed_name in ignored_lookup:
        return "__IGNORE__"
    if fixed_name in alias_lookup:
        return alias_lookup[fixed_name]
    if "国债" in fixed_name or "科创50" in fixed_name or "恒生消费" in fixed_name:
        return "__IGNORE__"
    if "红利" in fixed_name:
        return "sh50"
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


def aggregate_current_holdings(rows: list[dict[str, Any]], alias_map: dict[str, str], ignored_holdings: set[str]) -> tuple[dict[str, float], list[dict[str, Any]]]:
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
            unmapped.append(
                {
                    "name": name,
                    "amount": round(amount, 2),
                    "source": parse_multiselect(get_first(row, "来源")),
                    "level_2": parse_multiselect(get_first(row, "Ⅱ级分类", "II级分类", "二级分类")),
                }
            )

    return aggregated, unmapped


def build_holding_breakdown(rows: list[dict[str, Any]], alias_map: dict[str, str], ignored_holdings: set[str]) -> dict[str, list[dict[str, Any]]]:
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


def compute_erp_snapshot(rows: list[dict[str, Any]], thresholds: dict[str, float], weights: dict[str, float]) -> dict[str, Any]:
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
    percentile = round(sum(1 for value in history if value <= latest_value) / len(history) * 100, 2)
    aggressive_weight = piecewise_linear_weight(
        percentile,
        float(thresholds["low"]),
        float(thresholds["high"]),
        float(weights["low"]),
        float(weights["neutral"]),
        float(weights["high"]),
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
    latest = latest_valid_row(rows, ["500建议", "1000建议", "创业板建议", "50建议", "300价值建议"])
    dt = parse_date(get_first(latest, "日期"))
    if not dt:
        raise ValueError("Relative row missing valid date")

    dated_rows = []
    for row in rows:
        row_dt = parse_date(get_first(row, "日期"))
        if row_dt:
            dated_rows.append((row_dt, row))
    dated_rows.sort(key=lambda item: item[0])

    def compute_ratio_change(field_name: str, periods: int = 5) -> float | None:
        history: list[tuple[datetime, float]] = []
        for row_dt, row in dated_rows:
            value = safe_float(get_first(row, field_name))
            if value is not None:
                history.append((row_dt, value))
        if len(history) <= periods:
            return None
        latest_value = history[-1][1]
        base_value = history[-1 - periods][1]
        if base_value == 0:
            return None
        return round((latest_value / base_value - 1.0) * 100.0, 2)

    return {
        "date": dt.strftime("%Y-%m-%d"),
        "recommendations": {
            "zz500": normalize_text(get_first(latest, "500建议")),
            "zz1000": normalize_text(get_first(latest, "1000建议")),
            "cyb": normalize_text(get_first(latest, "创业板建议")),
            "sh50": normalize_text(get_first(latest, "50建议")),
        },
        "ratios": {
            "zz500_ratio": safe_float(get_first(latest, "500/300比价")),
            "zz1000_ratio": safe_float(get_first(latest, "1000/300比价")),
            "cyb_ratio": safe_float(get_first(latest, "创业板/300比价")),
            "sh50_ratio": safe_float(get_first(latest, "50/创业板比价", "50/300比价")),
            "val300_ratio": safe_float(get_first(latest, "300价值/成长比价")),
        },
        "percentiles": {
            "zz500_percentile": safe_float(get_first(latest, "500分位")),
            "zz1000_percentile": safe_float(get_first(latest, "1000分位")),
            "cyb_percentile": safe_float(get_first(latest, "创业板分位")),
            "sh50_percentile": safe_float(get_first(latest, "50分位")),
            "val300_percentile": safe_float(get_first(latest, "300价值分位")),
        },
        "deviations": {
            "zz500_deviation": safe_float(get_first(latest, "500偏离(%)")),
            "zz1000_deviation": safe_float(get_first(latest, "1000偏离(%)")),
            "cyb_deviation": safe_float(get_first(latest, "创业板偏离(%)")),
            "sh50_deviation": safe_float(get_first(latest, "50偏离(%)")),
            "val300_deviation": safe_float(get_first(latest, "300价值偏离(%)")),
        },
        "changes": {
            "zz500_change_5d": compute_ratio_change("500/300比价", 5),
            "zz1000_change_5d": compute_ratio_change("1000/300比价", 5),
            "cyb_change_5d": compute_ratio_change("创业板/300比价", 5),
            "sh50_change_5d": compute_ratio_change("50/创业板比价", 5) or compute_ratio_change("50/300比价", 5),
            "val300_change_5d": compute_ratio_change("300价值/成长比价", 5),
        },
        "style": {
            "val300_recommendation": normalize_text(get_first(latest, "300价值建议")),
        },
    }


def compute_val300_style_snapshot(relative_snapshot: dict[str, Any]) -> dict[str, Any]:
    ratio = relative_snapshot["ratios"].get("val300_ratio")
    percentile = relative_snapshot["percentiles"].get("val300_percentile")
    recommendation = relative_snapshot["style"].get("val300_recommendation")
    if ratio is None or percentile is None:
        return {"available": False, "message": "Relative base does not contain VAL300/GRO300 fields"}
    return {
        "available": True,
        "date": relative_snapshot["date"],
        "ratio": round(float(ratio), 6),
        "percentile": round(float(percentile), 2),
        "recommendation": recommendation or "标配",
        "influence_mode": "execution",
    }


def trajectory_multiplier(
    deviation: float | None,
    change_5d: float | None,
    trajectory_config: dict[str, Any],
) -> tuple[float, str]:
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


def build_target_weights(
    erp_snapshot: dict[str, Any],
    relative_snapshot: dict[str, Any],
    val300_style_snapshot: dict[str, Any],
    execution_config: dict[str, Any],
    current_holdings: dict[str, float],
) -> dict[str, dict[str, Any]]:
    aggressive_total = float(erp_snapshot["aggressive_weight"])
    recs = relative_snapshot["recommendations"]
    value_style_rec = normalize_text(val300_style_snapshot.get("recommendation") or "标配")

    recommendation_multipliers = execution_config["recommendation_multipliers"]
    value_style_tilt = execution_config["value_style_tilt"]
    growth_style_tilt = execution_config["growth_style_tilt"]
    alpha_budget_weights = execution_config["alpha_budget_weights"]
    alpha_base_weights = execution_config["alpha_base_weights"]
    alpha_bucket_caps = execution_config["alpha_bucket_caps"]
    forced_exit_thresholds = execution_config.get("forced_exit_percentiles", {})
    reentry_thresholds = execution_config.get("aggressive_reentry_percentiles", {})
    reentry_min_current_amount = float(execution_config.get("reentry_min_current_amount", 1000.0))
    trajectory_config = execution_config.get("trajectory_overlay", {})
    thresholds = execution_config["percentile_thresholds"]

    value_tilt = float(value_style_tilt.get(value_style_rec, 1.0))
    growth_tilt = growth_style_tilt.get(value_style_rec, growth_style_tilt.get("标配", {}))
    alpha_budget = piecewise_linear_weight(
        float(erp_snapshot["percentile"]),
        float(thresholds["low"]),
        float(thresholds["high"]),
        float(alpha_budget_weights["low"]),
        float(alpha_budget_weights["neutral"]),
        float(alpha_budget_weights["high"]),
    )
    alpha_budget = max(0.0, min(alpha_budget, 0.45))

    sh50_percentile = relative_snapshot["percentiles"].get("sh50_percentile")
    sh50_forced_exit_threshold = forced_exit_thresholds.get("sh50")
    sh50_forced_exit = (
        sh50_forced_exit_threshold is not None
        and sh50_percentile is not None
        and float(sh50_percentile) >= float(sh50_forced_exit_threshold)
    )

    sh50_target = alpha_budget * (1.0 - aggressive_total)
    sh50_target *= recommendation_multiplier(recs.get("sh50"), recommendation_multipliers)
    sh50_target *= value_tilt
    sh50_target *= float(growth_tilt.get("sh50_bonus", 1.0))
    sh50_target = min(sh50_target, float(alpha_bucket_caps.get("sh50", 0.18)))
    if sh50_forced_exit:
        sh50_target = 0.0

    aggressive_scores = {
        "cyb": float(alpha_base_weights.get("cyb", 0.3)) * recommendation_multiplier(recs.get("cyb"), recommendation_multipliers) * float(growth_tilt.get("cyb", 1.0)),
        "zz500": float(alpha_base_weights.get("zz500", 0.4)) * recommendation_multiplier(recs.get("zz500"), recommendation_multipliers) * float(growth_tilt.get("zz500", 1.0)),
        "zz1000": float(alpha_base_weights.get("zz1000", 0.3)) * recommendation_multiplier(recs.get("zz1000"), recommendation_multipliers) * float(growth_tilt.get("zz1000", 1.0)),
    }

    aggressive_alpha_total = alpha_budget * aggressive_total
    aggressive_weights = normalize_to_weights(aggressive_scores)

    targets: dict[str, dict[str, Any]] = {}
    for bucket, local_weight in aggressive_weights.items():
        bucket_percentile = relative_snapshot["percentiles"].get(f"{bucket}_percentile")
        bucket_deviation = relative_snapshot.get("deviations", {}).get(f"{bucket}_deviation")
        bucket_change_5d = relative_snapshot.get("changes", {}).get(f"{bucket}_change_5d")
        current_amount = float(current_holdings.get(bucket, 0.0))
        forced_exit_threshold = forced_exit_thresholds.get(bucket)
        forced_exit = (
            forced_exit_threshold is not None
            and bucket_percentile is not None
            and float(bucket_percentile) >= float(forced_exit_threshold)
        )
        reentry_threshold = reentry_thresholds.get(bucket)
        reentry_blocked = (
            reentry_threshold is not None
            and bucket_percentile is not None
            and current_amount <= reentry_min_current_amount
            and float(bucket_percentile) > float(reentry_threshold)
        )
        traj_multiplier, traj_reason = trajectory_multiplier(
            bucket_deviation,
            bucket_change_5d,
            trajectory_config,
        )

        target_weight = aggressive_alpha_total * local_weight
        target_weight = min(target_weight, float(alpha_bucket_caps.get(bucket, 1.0)))
        if forced_exit:
            target_weight = 0.0
        elif reentry_blocked:
            target_weight = 0.0
        else:
            target_weight *= traj_multiplier
        targets[bucket] = {
            "bucket": bucket,
            "label": BUCKET_METADATA[bucket]["label"],
            "sleeve": "aggressive",
            "signal": recs.get(bucket) or "标配",
            "style_overlay": value_style_rec,
            "current_percentile": round(float(bucket_percentile), 2) if bucket_percentile is not None else None,
            "current_deviation": round(float(bucket_deviation), 2) if bucket_deviation is not None else None,
            "change_5d": round(float(bucket_change_5d), 2) if bucket_change_5d is not None else None,
            "forced_exit_threshold": float(forced_exit_threshold) if forced_exit_threshold is not None else None,
            "forced_exit": forced_exit,
            "reentry_threshold": float(reentry_threshold) if reentry_threshold is not None else None,
            "reentry_blocked": reentry_blocked,
            "trajectory_multiplier": round(float(traj_multiplier), 2),
            "trajectory_reason": traj_reason,
            "target_weight": round(target_weight, 4),
        }

    targets["sh50"] = {
        "bucket": "sh50",
        "label": BUCKET_METADATA["sh50"]["label"],
        "sleeve": "defensive",
        "signal": recs.get("sh50") or "标配",
        "style_overlay": value_style_rec,
        "current_percentile": round(float(sh50_percentile), 2) if sh50_percentile is not None else None,
        "forced_exit_threshold": float(sh50_forced_exit_threshold) if sh50_forced_exit_threshold is not None else None,
        "forced_exit": sh50_forced_exit,
        "target_weight": round(sh50_target, 4),
    }

    used_alpha_weight = sh50_target + sum(float(item["target_weight"]) for item in targets.values() if item["bucket"] != "sh50")
    hs300_target = max(0.0, 1.0 - used_alpha_weight)
    targets["hs300"] = {
        "bucket": "hs300",
        "label": BUCKET_METADATA["hs300"]["label"],
        "sleeve": "defensive",
        "signal": "core",
        "style_overlay": value_style_rec,
        "target_weight": round(hs300_target, 4),
    }
    return targets

def build_rebalance_plan(current_holdings: dict[str, float], unmapped_holdings: list[dict[str, Any]], targets: dict[str, dict[str, Any]], holding_breakdown: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    managed_total = round(sum(current_holdings.values()), 2)
    unmapped_total = round(sum(item["amount"] for item in unmapped_holdings), 2)
    total_erp_amount = round(managed_total + unmapped_total, 2)

    positions: list[dict[str, Any]] = []
    for bucket, target in targets.items():
        current_amount = round(current_holdings.get(bucket, 0.0), 2)
        current_weight = round(current_amount / managed_total, 4) if managed_total > 0 else 0.0
        target_amount = round(managed_total * float(target["target_weight"]), 2)
        delta_amount = round(target_amount - current_amount, 2)
        action = "hold"
        if delta_amount > 0:
            action = "buy"
        elif delta_amount < 0:
            action = "sell"

        positions.append({**target, "current_amount": current_amount, "current_weight": current_weight, "target_amount": target_amount, "delta_amount": delta_amount, "action": action, "holding_breakdown": (holding_breakdown or {}).get(bucket, [])})

    positions.sort(key=lambda item: (item["sleeve"], item["bucket"]))

    return {
        "total_erp_amount": total_erp_amount,
        "managed_amount": managed_total,
        "unmapped_amount": unmapped_total,
        "managed_position_count": len(current_holdings),
        "unmapped_position_count": len(unmapped_holdings),
        "positions": positions,
        "unmapped_holdings": unmapped_holdings,
    }


def save_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_daily_summary() -> Path | None:
    if not DEFAULT_RENDER_SCRIPT.exists():
        return None
    completed = subprocess.run([sys.executable, str(DEFAULT_RENDER_SCRIPT)], cwd=DEFAULT_RENDER_SCRIPT.parent.parent, text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Failed to render daily summary: {completed.stderr.strip() or completed.stdout.strip()}")
    output_text = (completed.stdout or "").strip()
    if not output_text:
        return None
    return Path(output_text.splitlines()[-1].strip())


def print_summary(payload: dict[str, Any]) -> None:
    erp = payload["signals"]["erp"]
    relative = payload["signals"]["relative"]
    style = payload["signals"]["val300_style"]
    portfolio = payload["portfolio"]

    print("=" * 60)
    print("ERP Execution Cloud Plan")
    print("=" * 60)
    print(f"ERP latest date: {erp['date']}")
    print(f"ERP premium / percentile: {erp['equity_premium']:.2f} / {erp['percentile']:.2f}%")
    print(f"Aggressive / defensive: {erp['aggressive_weight']:.2%} / {erp['defensive_weight']:.2%}")
    print(f"Relative latest date: {relative['date']}")
    print("Recommendations:")
    for key, value in relative["recommendations"].items():
        print(f"  - {key}: {value or '标配'}")
    if style.get("available"):
        print(f"VAL300/GRO300: {style['ratio']:.4f} / {style['percentile']:.2f}% / {style['recommendation']}")
    print(f"Managed ERP capital: {portfolio['managed_amount']:.2f}")
    for item in portfolio["positions"]:
        print(f"  - {item['label']}: current {item['current_amount']:.2f} -> target {item['target_amount']:.2f} ({item['action']} {item['delta_amount']:+.2f})")


def main() -> None:
    args = parse_args()

    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    reader = FeishuBitableReader(app_id, app_secret)

    execution_config = sanitize_structure(json.loads(Path(args.execution_config_path).read_text(encoding="utf-8")))

    erp_rows = reader.list_all_records(args.erp_app_token, args.erp_table_id, args.page_size)
    relative_rows = reader.list_all_records(args.relative_app_token, args.relative_table_id, args.page_size)
    asset_rows = reader.list_all_records(args.asset_app_token, args.asset_table_id, args.page_size)

    erp_snapshot = compute_erp_snapshot(erp_rows, execution_config["percentile_thresholds"], execution_config["aggressive_weights"])
    relative_snapshot = compute_relative_snapshot(relative_rows)
    val300_style_snapshot = compute_val300_style_snapshot(relative_snapshot)

    alias_map = {normalize_text(key): normalize_text(value) for key, value in execution_config.get("holding_alias_map", {}).items()}
    ignored_holdings = {normalize_text(item) for item in execution_config.get("ignored_erp_holdings", [])}
    current_holdings, unmapped_holdings = aggregate_current_holdings(asset_rows, alias_map, ignored_holdings)
    holding_breakdown = build_holding_breakdown(asset_rows, alias_map, ignored_holdings)

    targets = build_target_weights(erp_snapshot, relative_snapshot, val300_style_snapshot, execution_config, current_holdings)
    portfolio = build_rebalance_plan(current_holdings, unmapped_holdings, targets, holding_breakdown)

    payload = {
        "version": "1.0",
        "signal_type": "erp_execution_plan",
        "generated_at": datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds"),
        "inputs": {
            "mode": "cloud_openapi",
            "erp_table": {"app_token": args.erp_app_token, "table_id": args.erp_table_id},
            "relative_table": {"app_token": args.relative_app_token, "table_id": args.relative_table_id},
            "asset_table": {"app_token": args.asset_app_token, "table_id": args.asset_table_id},
            "execution_config_path": str(Path(args.execution_config_path).resolve()),
            "execution_config": execution_config,
        },
        "signals": {"erp": erp_snapshot, "relative": relative_snapshot, "val300_style": val300_style_snapshot},
        "portfolio": portfolio,
    }

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
