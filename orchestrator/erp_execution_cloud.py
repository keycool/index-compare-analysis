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
DEFAULT_INDEX_COMPARE_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / ".claude" / "skills" / "index-compare" / "config.json"
)

BASE_URL = "https://open.feishu.cn/open-apis"
AUTH_URL = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

DEFAULT_RELATIVE_ANALYSIS_SETTINGS = {
    "ma_window": 30,
    "trend_windows": [5, 10, 20],
    "percentile_levels": {
        "extreme_low": 15,
        "low": 30,
        "high": 70,
        "extreme_high": 85,
    },
}

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


def row_effective_date(row: dict[str, Any]) -> datetime | None:
    return parse_date(
        get_first(row, "日期", "date", "Date", "交易日期", "数据日期")
        or row.get("date")
        or row.get("日期")
    )


def filter_signal_rows_as_of(rows: list[dict[str, Any]], as_of: datetime) -> list[dict[str, Any]]:
    dated_rows: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        dt = row_effective_date(row)
        if dt is not None:
            dated_rows.append((dt, row))
    if not dated_rows:
        return rows
    return [row for dt, row in dated_rows if dt.date() <= as_of.date()]


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
    """KC50 ratio signals are already recommendations for the numerator KC50."""
    return normalize_text(rec) or "标配"


_REC_STRONG_OVER = "\u5f3a\u70c8\u8d85\u914d"
_REC_OVER = "\u8d85\u914d"
_REC_NEUTRAL = "\u6807\u914d"
_REC_UNDER = "\u4f4e\u914d"
_REC_STRONG_UNDER = "\u5f3a\u70c8\u4f4e\u914d"

_DEFAULT_RELATIVE_SIGNAL_POLICY = {
    "anchor_recommendation_keys": {
        "sh50": "sh50_300",
        "zz500": "zz500",
        "zz1000": "zz1000",
        "cyb": "cyb",
        "kc50": "kc50_300",
        "val300": "val300",
        "gro300": "gro300",
        "hstech": "hstech",
    },
    "anchor_eligible_recommendations": [_REC_NEUTRAL, _REC_OVER, _REC_STRONG_OVER],
    "pairwise_tilt_multipliers": {
        _REC_STRONG_OVER: {"numerator": 1.10, "denominator": 0.90},
        _REC_OVER: {"numerator": 1.05, "denominator": 0.95},
        _REC_NEUTRAL: {"numerator": 1.00, "denominator": 1.00},
        _REC_UNDER: {"numerator": 0.95, "denominator": 1.05},
        _REC_STRONG_UNDER: {"numerator": 0.90, "denominator": 1.10},
    },
    "pairwise_features": {
        "cyb_sh50": {"signal_key": "cyb_sh50", "numerator": "cyb", "denominator": "sh50"},
        "kc50_sh50": {"signal_key": "kc50", "numerator": "kc50", "denominator": "sh50"},
        "zz1000_500": {"signal_key": "zz1000_500", "numerator": "zz1000", "denominator": "zz500"},
    },
}


def _relative_signal_policy(execution_config: dict[str, Any]) -> dict[str, Any]:
    policy = execution_config.get("relative_signal_policy", {})
    return policy if isinstance(policy, dict) and policy else _DEFAULT_RELATIVE_SIGNAL_POLICY


def _anchor_signal_context(recommendations: dict[str, Any], policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    anchor_keys = policy.get("anchor_recommendation_keys", _DEFAULT_RELATIVE_SIGNAL_POLICY["anchor_recommendation_keys"])
    eligible_recommendations = {
        normalize_text(value)
        for value in policy.get("anchor_eligible_recommendations", _DEFAULT_RELATIVE_SIGNAL_POLICY["anchor_eligible_recommendations"])
    }
    return {
        bucket: {
            "signal_key": signal_key,
            "recommendation": normalize_text(recommendations.get(signal_key)),
            "eligible": normalize_text(recommendations.get(signal_key)) in eligible_recommendations,
        }
        for bucket, signal_key in anchor_keys.items()
    }


def _feature_tilt_context(
    recommendations: dict[str, Any],
    anchors: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    raw_tilts: dict[str, list[dict[str, Any]]] = {}
    tilt_mapping = policy.get("pairwise_tilt_multipliers", _DEFAULT_RELATIVE_SIGNAL_POLICY["pairwise_tilt_multipliers"])
    for feature_name, feature in policy.get("pairwise_features", {}).items():
        numerator = feature.get("numerator")
        denominator = feature.get("denominator")
        if not numerator or not denominator:
            continue
        if not anchors.get(numerator, {}).get("eligible") or not anchors.get(denominator, {}).get("eligible"):
            continue
        recommendation = normalize_text(recommendations.get(feature.get("signal_key")))
        multipliers = tilt_mapping.get(recommendation)
        if not isinstance(multipliers, dict):
            continue
        for bucket, role in ((numerator, "numerator"), (denominator, "denominator")):
            multiplier = safe_float(multipliers.get(role))
            if multiplier is None:
                continue
            raw_tilts.setdefault(bucket, []).append({
                "feature": feature_name,
                "signal_key": feature.get("signal_key"),
                "recommendation": recommendation,
                "role": role,
                "multiplier": round(multiplier, 4),
            })

    result: dict[str, dict[str, Any]] = {}
    for bucket in anchors:
        details = raw_tilts.get(bucket, [])
        multiplier = sum(item["multiplier"] for item in details) / len(details) if details else 1.0
        result[bucket] = {"multiplier": round(multiplier, 4), "details": details}
    return result


def _required_relative_recommendation_keys(execution_config: dict[str, Any]) -> list[str]:
    policy = _relative_signal_policy(execution_config)
    keys = list(policy.get("anchor_recommendation_keys", {}).values())
    keys.extend(
        feature.get("signal_key")
        for feature in policy.get("pairwise_features", {}).values()
        if feature.get("signal_key")
    )
    return list(dict.fromkeys(keys))


def load_relative_analysis_settings() -> dict[str, Any]:
    settings = json.loads(json.dumps(DEFAULT_RELATIVE_ANALYSIS_SETTINGS))
    config_path = Path(os.environ.get("ERP_RELATIVE_ANALYSIS_CONFIG_PATH") or DEFAULT_INDEX_COMPARE_CONFIG_PATH)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return settings

    analysis = config.get("analysis", {}) if isinstance(config, dict) else {}
    percentile_levels = config.get("percentile_levels", {}) if isinstance(config, dict) else {}
    if isinstance(analysis.get("ma_window"), int):
        settings["ma_window"] = analysis["ma_window"]
    if isinstance(analysis.get("trend_windows"), list):
        windows = [int(float(item)) for item in analysis["trend_windows"] if safe_float(item) is not None]
        if windows:
            settings["trend_windows"] = windows
    if isinstance(percentile_levels, dict):
        settings["percentile_levels"].update(
            {key: float(value) for key, value in percentile_levels.items() if safe_float(value) is not None}
        )
    return settings


def _recommendation_from_score(score: float) -> str:
    if score > 1.0:
        return _REC_STRONG_OVER
    if score > 0.5:
        return _REC_OVER
    if score > -0.5:
        return _REC_NEUTRAL
    if score > -1.0:
        return _REC_UNDER
    return _REC_STRONG_UNDER


def _percentile_score(percentile: Any, levels: dict[str, Any]) -> int | None:
    value = safe_float(percentile)
    if value is None:
        return None
    if value <= float(levels["extreme_low"]):
        return 2
    if value <= float(levels["low"]):
        return 1
    if value < float(levels["high"]):
        return 0
    if value < float(levels["extreme_high"]):
        return -1
    return -2


def _trend_score(changes: list[Any]) -> int:
    values = [float(value) for value in (safe_float(item) for item in changes) if value is not None]
    if not values:
        return 0
    up_count = sum(1 for value in values if value > 0.5)
    down_count = sum(1 for value in values if value < -0.5)
    if all(value > 1 for value in values):
        return 2
    if all(value < -1 for value in values):
        return -2
    if up_count >= 2:
        return 1
    if down_count >= 2:
        return -1
    return 0


def _deviation_score_from_zscore(zscore: Any) -> int:
    value = safe_float(zscore)
    if value is None:
        return 0
    if value >= 2.0:
        return -2
    if value >= 1.0:
        return -1
    if value <= -2.0:
        return 2
    if value <= -1.0:
        return 1
    return 0


def _derive_relative_recommendation(
    percentile: Any,
    zscore: Any,
    changes: list[Any],
    percentile_levels: dict[str, Any],
) -> str:
    percentile_component = _percentile_score(percentile, percentile_levels)
    if percentile_component is None:
        return ""
    trend_component = _trend_score(changes)
    percentile_value = float(safe_float(percentile) or 0.0)
    if percentile_value > 60:
        trend_component = -trend_component
    score = (
        percentile_component * 0.6
        + trend_component * 0.25
        + _deviation_score_from_zscore(zscore) * 0.15
    )
    return _recommendation_from_score(score)


def _fill_derived_relative_recommendations(snapshot: dict[str, Any]) -> None:
    recs = snapshot.setdefault("recommendations", {})
    sources = snapshot.setdefault("recommendation_sources", {})
    settings = load_relative_analysis_settings()
    trend_windows = [int(item) for item in settings.get("trend_windows", [5, 10, 20])]
    percentile_levels = settings.get("percentile_levels", DEFAULT_RELATIVE_ANALYSIS_SETTINGS["percentile_levels"])
    for key, value in recs.items():
        if normalize_text(value):
            sources.setdefault(key, "table")

    fields: dict[str, tuple[str, str, str, bool]] = {
        "zz500": ("zz500_percentile", "zz500_zscore", "zz500_change", False),
        "zz1000": ("zz1000_percentile", "zz1000_zscore", "zz1000_change", False),
        "zz1000_500": ("zz1000_500_percentile", "zz1000_500_zscore", "zz1000_500_change", False),
        "cyb": ("cyb_percentile", "cyb_zscore", "cyb_change", False),
        "cyb_sh50": ("cyb_sh50_percentile", "cyb_sh50_zscore", "cyb_sh50_change", False),
        "sh50": ("sh50_percentile", "sh50_zscore", "sh50_change", True),
        "sh50_300": ("sh50_300_percentile", "sh50_300_zscore", "sh50_300_change", False),
        "kc50": ("kc50_percentile", "kc50_zscore", "kc50_change", False),
        "kc50_300": ("kc50_300_percentile", "kc50_300_zscore", "kc50_300_change", False),
        "gro300": ("gro300_percentile", "gro300_zscore", "gro300_change", False),
        "hstech": ("hstech_percentile", "hstech_zscore", "hstech_change", False),
    }
    percentiles = snapshot.get("percentiles", {})
    zscores = snapshot.get("zscores", {})
    changes = snapshot.get("changes", {})
    for key, (percentile_key, zscore_key, change_prefix, reverse) in fields.items():
        if normalize_text(recs.get(key)):
            continue
        derived = _derive_relative_recommendation(
            percentiles.get(percentile_key),
            zscores.get(zscore_key),
            [changes.get(f"{change_prefix}_{window}d") for window in trend_windows],
            percentile_levels,
        )
        if reverse and derived:
            derived = _REVERSE_REC.get(derived, "")
        if derived:
            recs[key] = derived
            sources[key] = "derived_from_analyze_rules"
        else:
            sources[key] = "missing"

    if not normalize_text(recs.get("val300")):
        growth_rec = normalize_text(recs.get("gro300"))
        reversed_growth = _REVERSE_REC.get(growth_rec, "")
        if reversed_growth:
            recs["val300"] = reversed_growth
            sources["val300"] = "derived_from_growth_recommendation_reverse"
        else:
            sources["val300"] = "missing"


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


def _copy_first(source: dict[str, Any], target: dict[str, Any], target_name: str, *source_names: str) -> None:
    value = get_first(source, target_name, *source_names)
    if value is not None:
        target[target_name] = value


def shared_erp_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_records = payload.get("records", [])
    if isinstance(source_records, list):
        for record in source_records:
            if not isinstance(record, dict):
                continue
            row: dict[str, Any] = {}
            _copy_first(record, row, "日期", "date", "trade_date")
            _copy_first(record, row, "股权溢价指数", "equity_premium", "erp", "risk_premium")
            if get_first(row, "日期") is not None and get_first(row, "股权溢价指数") is not None:
                rows.append(row)

    latest_signal = payload.get("latest_signal", {})
    if isinstance(latest_signal, dict):
        latest_row = dict(latest_signal)
        if payload.get("latest_date") and get_first(latest_row, "日期", "date", "trade_date") is None:
            latest_row["date"] = payload.get("latest_date")
        row = {}
        _copy_first(latest_row, row, "日期", "date", "trade_date")
        _copy_first(latest_row, row, "股权溢价指数", "equity_premium", "erp", "risk_premium")
        if get_first(row, "日期") is not None and get_first(row, "股权溢价指数") is not None:
            rows.append(row)

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        dt = parse_date(get_first(row, "日期"))
        if dt:
            deduped[dt.strftime("%Y-%m-%d")] = row
    return [deduped[key] for key in sorted(deduped)]


def shared_relative_row_to_execution_row(record: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    field_aliases: dict[str, tuple[str, ...]] = {
        "日期": ("date", "trade_date"),
        "沪深300": ("hs300", "csi300", "csi300_close"),
        "中证500": ("zz500",),
        "中证1000": ("zz1000",),
        "创业板指数": ("zza500", "cyb"),
        "上证50指数": ("sh50",),
        "科创50指数": ("kc50",),
        "300价值指数": ("val300",),
        "300成长指数": ("gro300",),
        "上证综指": ("shci",),
        "恒生指数": ("hsi", "hs_index"),
        "恒生科技指数": ("hstech",),
        "500/300比价": ("zz500_ratio",),
        "1000/300比价": ("zz1000_ratio",),
        "创业板/300比价": ("zza500_ratio", "cyb_ratio"),
        "50/创业板比价": ("sh50_ratio",),
        "科创50/上证50比价": ("kc50_ratio",),
        "300价值/成长比价": ("val300_ratio",),
        "恒生科技/恒生比价": ("hstech_ratio",),
        "500分位": ("zz500_percentile",),
        "1000分位": ("zz1000_percentile",),
        "创业板分位": ("zza500_percentile", "cyb_percentile"),
        "50分位": ("sh50_percentile",),
        "科创50分位": ("kc50_percentile",),
        "300价值分位": ("val300_percentile",),
        "300成长分位": ("gro300_percentile",),
        "恒生科技分位": ("hstech_percentile",),
        "500偏离(%)": ("zz500_deviation",),
        "1000偏离(%)": ("zz1000_deviation",),
        "创业板偏离(%)": ("zza500_deviation", "cyb_deviation"),
        "50偏离(%)": ("sh50_deviation",),
        "科创50偏离(%)": ("kc50_deviation",),
        "300价值偏离(%)": ("val300_deviation",),
        "300成长偏离(%)": ("gro300_deviation",),
        "恒生科技偏离(%)": ("hstech_deviation",),
        "500建议": ("zz500_recommendation",),
        "1000建议": ("zz1000_recommendation",),
        "创业板建议": ("zza500_recommendation", "cyb_recommendation"),
        "50建议": ("sh50_recommendation",),
        "科创50建议": ("kc50_recommendation",),
        "300价值建议": ("val300_recommendation",),
        "300成长建议": ("gro300_recommendation",),
        "恒生科技建议": ("hstech_recommendation",),
    }
    for target_name, aliases in field_aliases.items():
        _copy_first(record, row, target_name, *aliases)
    return row


def shared_relative_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_records = payload.get("records", [])
    if isinstance(source_records, list):
        for record in source_records:
            if isinstance(record, dict):
                row = shared_relative_row_to_execution_row(record)
                if get_first(row, "日期") is not None:
                    rows.append(row)

    latest_signal = payload.get("latest_signal", {})
    if isinstance(latest_signal, dict):
        latest_record = dict(latest_signal)
        if payload.get("latest_date") and get_first(latest_record, "日期", "date", "trade_date") is None:
            latest_record["date"] = payload.get("latest_date")
        latest_row = shared_relative_row_to_execution_row(latest_record)
        latest_dt = parse_date(get_first(latest_row, "日期"))
        if latest_dt:
            latest_key = latest_dt.strftime("%Y-%m-%d")
            merged = False
            for index, row in enumerate(rows):
                row_dt = parse_date(get_first(row, "日期"))
                if row_dt and row_dt.strftime("%Y-%m-%d") == latest_key:
                    rows[index] = {**row, **latest_row}
                    merged = True
                    break
            if not merged:
                rows.append(latest_row)

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        dt = parse_date(get_first(row, "日期"))
        if dt:
            deduped[dt.strftime("%Y-%m-%d")] = row
    return [deduped[key] for key in sorted(deduped)]


def load_shared_erp_rows(path: str) -> list[dict[str, Any]]:
    payload = sanitize_structure(json.loads(Path(path).read_text(encoding="utf-8")))
    rows = shared_erp_rows_from_payload(payload)
    if not rows:
        raise ValueError(f"ERP shared signal has no valid rows: {path}")
    return rows


def load_shared_relative_rows(path: str) -> list[dict[str, Any]]:
    payload = sanitize_structure(json.loads(Path(path).read_text(encoding="utf-8")))
    rows = shared_relative_rows_from_payload(payload)
    if not rows:
        raise ValueError(f"Relative shared signal has no valid rows: {path}")
    return rows


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
        "1000/500建议", "上证50/300建议", "科创50/300建议", "创业板/上证50建议",
        "500分位", "1000分位", "创业板分位", "50分位", "科创50分位",
        "1000/500分位", "上证50/300分位", "科创50/300分位",
        "300价值分位", "300成长分位", "恒生科技分位",
        "500/300比价", "1000/300比价", "创业板/300比价",
        "1000/500比价", "上证50/300比价", "科创50/300比价", "创业板/上证50比价",
        "科创50/上证50比价", "300价值/成长比价", "恒生科技/恒生比价",
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

    def compute_inverse_ratio_change(field_name: str, periods: int = 5) -> float | None:
        history: list[tuple[datetime, float]] = []
        for row_dt, r in dated_rows:
            value = safe_float(get_first(r, field_name))
            if value not in (None, 0):
                history.append((row_dt, 1.0 / float(value)))
        if len(history) <= periods:
            return None
        latest_val = history[-1][1]
        base_val = history[-1 - periods][1]
        if base_val == 0:
            return None
        return round((latest_val / base_val - 1.0) * 100.0, 2)

    def compute_inverse_ratio_deviation(field_name: str, window: int = 30) -> float | None:
        history: list[float] = []
        for _, r in dated_rows:
            value = safe_float(get_first(r, field_name))
            if value not in (None, 0):
                history.append(1.0 / float(value))
        if len(history) < window:
            return None
        latest_val = history[-1]
        ma_value = sum(history[-window:]) / window
        if ma_value == 0:
            return None
        return round((latest_val / ma_value - 1.0) * 100.0, 2)

    analysis_settings = load_relative_analysis_settings()
    ma_window = int(analysis_settings.get("ma_window", 30))

    def compute_ratio_zscore(field_name: str, window: int = ma_window) -> float:
        history: list[float] = []
        for _, r in dated_rows:
            value = safe_float(get_first(r, field_name))
            if value is not None:
                history.append(float(value))
        if len(history) < window:
            return 0.0
        window_values = history[-window:]
        ma_value = sum(window_values) / len(window_values)
        if len(window_values) <= 1:
            return 0.0
        std_value = math.sqrt(sum((value - ma_value) ** 2 for value in window_values) / (len(window_values) - 1))
        if std_value == 0:
            return 0.0
        return round((window_values[-1] - ma_value) / std_value, 2)

    def compute_inverse_ratio_zscore(field_name: str, window: int = ma_window) -> float:
        history: list[float] = []
        for _, r in dated_rows:
            value = safe_float(get_first(r, field_name))
            if value not in (None, 0):
                history.append(1.0 / float(value))
        if len(history) < window:
            return 0.0
        window_values = history[-window:]
        ma_value = sum(window_values) / len(window_values)
        if len(window_values) <= 1:
            return 0.0
        std_value = math.sqrt(sum((value - ma_value) ** 2 for value in window_values) / (len(window_values) - 1))
        if std_value == 0:
            return 0.0
        return round((window_values[-1] - ma_value) / std_value, 2)

    def first_ratio_change(periods: int, *field_names: str) -> float | None:
        for field_name in field_names:
            value = compute_ratio_change(field_name, periods)
            if value is not None:
                return value
        return None

    def first_inverse_ratio_change(periods: int, *field_names: str) -> float | None:
        for field_name in field_names:
            value = compute_inverse_ratio_change(field_name, periods)
            if value is not None:
                return value
        return None

    def first_ratio_zscore(*field_names: str) -> float:
        for field_name in field_names:
            if any(safe_float(get_first(r, field_name)) is not None for _, r in dated_rows):
                return compute_ratio_zscore(field_name)
        return 0.0

    def first_inverse_ratio_zscore(*field_names: str) -> float:
        for field_name in field_names:
            if any((safe_float(get_first(r, field_name)) not in (None, 0)) for _, r in dated_rows):
                return compute_inverse_ratio_zscore(field_name)
        return 0.0

    def has_ratio_field(*field_names: str) -> bool:
        return any(
            any(safe_float(get_first(r, field_name)) is not None for _, r in dated_rows)
            for field_name in field_names
        )

    def invert_percent_change(change_pct: float | None) -> float | None:
        if change_pct is None:
            return None
        ratio = 1.0 + float(change_pct) / 100.0
        if ratio == 0:
            return None
        return round((1.0 / ratio - 1.0) * 100.0, 2)

    def latest_index_ratio(numerator_field: str, denominator_field: str) -> float | None:
        numerator = safe_float(get_first(latest, numerator_field))
        denominator = safe_float(get_first(latest, denominator_field))
        if numerator is None or denominator in (None, 0):
            return None
        return numerator / denominator

    def compute_index_ratio_percentile(numerator_field: str, denominator_field: str) -> float | None:
        history: list[float] = []
        for _, r in dated_rows:
            numerator = safe_float(get_first(r, numerator_field))
            denominator = safe_float(get_first(r, denominator_field))
            if numerator is None or denominator in (None, 0):
                continue
            history.append(numerator / denominator)
        if not history:
            return None
        latest_val = history[-1]
        return round(sum(value <= latest_val for value in history) / len(history) * 100.0, 1)

    sh50_300_ratio = (
        safe_float(get_first(latest, "上证50/300比价", "50/300比价"))
        or latest_index_ratio("上证50指数", "沪深300")
    )
    kc50_300_ratio = (
        safe_float(get_first(latest, "科创50/300比价", "科创50/沪深300比价"))
        or latest_index_ratio("科创50指数", "沪深300")
    )
    sh50_300_percentile = (
        safe_float(get_first(latest, "上证50/300分位", "50/300分位"))
        or compute_index_ratio_percentile("上证50指数", "沪深300")
    )
    kc50_300_percentile = (
        safe_float(get_first(latest, "科创50/300分位", "科创50/沪深300分位"))
        or compute_index_ratio_percentile("科创50指数", "沪深300")
    )
    cyb_sh50_recommendation = normalize_text(get_first(latest, "创业板/上证50建议", "50/创业板建议"))
    if not cyb_sh50_recommendation:
        cyb_sh50_recommendation = _REVERSE_REC.get(normalize_text(get_first(latest, "50建议")), "")

    trend_windows = [int(item) for item in analysis_settings.get("trend_windows", [5, 10, 20])]
    zz500_changes = {window: first_ratio_change(window, "500/300比价") for window in trend_windows}
    zz1000_changes = {window: first_ratio_change(window, "1000/300比价") for window in trend_windows}
    zz1000_500_changes = {window: first_ratio_change(window, "1000/500比价") for window in trend_windows}
    cyb_changes = {window: first_ratio_change(window, "创业板/300比价") for window in trend_windows}
    cyb_sh50_changes = {window: first_ratio_change(window, "创业板/上证50比价") for window in trend_windows}
    sh50_300_changes = {
        window: first_ratio_change(window, "上证50/300比价", "50/300比价")
        for window in trend_windows
    }
    kc50_300_changes = {
        window: first_ratio_change(window, "科创50/300比价", "科创50/沪深300比价")
        for window in trend_windows
    }
    sh50_changes = {
        window: first_ratio_change(window, "创业板/上证50比价", "50/创业板比价")
        for window in trend_windows
    }
    kc50_changes = {window: first_ratio_change(window, "科创50/上证50比价") for window in trend_windows}
    val300_changes = {window: first_ratio_change(window, "300价值/成长比价") for window in trend_windows}
    def compute_gro300_change(window: int) -> float | None:
        direct = first_ratio_change(window, "300成长/价值比价", "300成长/300价值比价")
        if direct is not None:
            return direct
        inverse = first_inverse_ratio_change(window, "300价值/成长比价")
        if inverse is not None:
            return inverse
        return invert_percent_change(val300_changes.get(window))

    gro300_changes = {window: compute_gro300_change(window) for window in trend_windows}
    gro300_zscore = (
        first_ratio_zscore("300成长/价值比价", "300成长/300价值比价")
        if has_ratio_field("300成长/价值比价", "300成长/300价值比价")
        else first_inverse_ratio_zscore("300价值/成长比价")
    )
    hstech_changes = {window: first_ratio_change(window, "恒生科技/恒生比价") for window in trend_windows}

    val300_change_5d = val300_changes.get(5)
    gro300_change_5d = gro300_changes.get(5)
    val300_deviation = safe_float(get_first(latest, "300价值偏离(%)"))
    gro300_deviation = safe_float(get_first(latest, "300成长偏离(%)"))
    if gro300_deviation is None and val300_deviation is not None:
        gro300_deviation = compute_inverse_ratio_deviation("300价值/成长比价", 30)
    if gro300_deviation is None and val300_deviation is not None:
        gro300_deviation = round(-float(val300_deviation), 2)

    snapshot = {
        "date": dt.strftime("%Y-%m-%d"),
        "recommendations": {
            "zz500": normalize_text(get_first(latest, "500建议")),
            "zz1000": normalize_text(get_first(latest, "1000建议")),
            "zz1000_500": normalize_text(get_first(latest, "1000/500建议")),
            "cyb": normalize_text(get_first(latest, "创业板建议")),
            "sh50_300": normalize_text(get_first(latest, "上证50/300建议", "50/300建议")),
            "kc50_300": normalize_text(get_first(latest, "科创50/300建议", "科创50/沪深300建议")),
            "cyb_sh50": cyb_sh50_recommendation,
            "sh50": normalize_text(get_first(latest, "50建议")),
            "kc50": normalize_text(get_first(latest, "科创50建议")),
            "val300": normalize_text(get_first(latest, "300价值建议")),
            "gro300": normalize_text(get_first(latest, "300成长建议")),
            "hstech": normalize_text(get_first(latest, "恒生科技建议")),
        },
        "ratios": {
            "zz500_ratio": safe_float(get_first(latest, "500/300比价")),
            "zz1000_ratio": safe_float(get_first(latest, "1000/300比价")),
            "zz1000_500_ratio": safe_float(get_first(latest, "1000/500比价")),
            "cyb_ratio": safe_float(get_first(latest, "创业板/300比价")),
            "sh50_300_ratio": sh50_300_ratio,
            "kc50_300_ratio": kc50_300_ratio,
            "sh50_ratio": safe_float(get_first(latest, "创业板/上证50比价", "50/创业板比价", "50/300比价")),
            "kc50_ratio": safe_float(get_first(latest, "科创50/上证50比价")),
            "val300_ratio": safe_float(get_first(latest, "300价值/成长比价")),
            "hstech_ratio": safe_float(get_first(latest, "恒生科技/恒生比价")),
        },
        "percentiles": {
            "zz500_percentile": safe_float(get_first(latest, "500分位")),
            "zz1000_percentile": safe_float(get_first(latest, "1000分位")),
            "zz1000_500_percentile": safe_float(get_first(latest, "1000/500分位")),
            "cyb_percentile": safe_float(get_first(latest, "创业板分位")),
            "cyb_sh50_percentile": safe_float(get_first(latest, "创业板/上证50分位", "50分位")),
            "sh50_300_percentile": sh50_300_percentile,
            "kc50_300_percentile": kc50_300_percentile,
            "sh50_percentile": safe_float(get_first(latest, "50分位")),
            "kc50_percentile": safe_float(get_first(latest, "科创50分位")),
            "val300_percentile": safe_float(get_first(latest, "300价值分位")),
            "gro300_percentile": safe_float(get_first(latest, "300成长分位")),
            "hstech_percentile": safe_float(get_first(latest, "恒生科技分位")),
        },
        "deviations": {
            "zz500_deviation": safe_float(get_first(latest, "500偏离(%)")),
            "zz1000_deviation": safe_float(get_first(latest, "1000偏离(%)")),
            "zz1000_500_deviation": safe_float(get_first(latest, "1000/500偏离(%)")),
            "cyb_deviation": safe_float(get_first(latest, "创业板偏离(%)")),
            "cyb_sh50_deviation": safe_float(get_first(latest, "创业板/上证50偏离(%)", "50偏离(%)")),
            "sh50_300_deviation": safe_float(get_first(latest, "上证50/300偏离(%)", "50/300偏离(%)")),
            "kc50_300_deviation": safe_float(get_first(latest, "科创50/300偏离(%)", "科创50/沪深300偏离(%)")),
            "sh50_deviation": safe_float(get_first(latest, "创业板/上证50偏离(%)", "50偏离(%)")),
            "kc50_deviation": safe_float(get_first(latest, "科创50偏离(%)")),
            "val300_deviation": val300_deviation,
            "gro300_deviation": gro300_deviation,
            "hstech_deviation": safe_float(get_first(latest, "恒生科技偏离(%)")),
        },
        "zscores": {
            "zz500_zscore": first_ratio_zscore("500/300比价"),
            "zz1000_zscore": first_ratio_zscore("1000/300比价"),
            "zz1000_500_zscore": first_ratio_zscore("1000/500比价"),
            "cyb_zscore": first_ratio_zscore("创业板/300比价"),
            "cyb_sh50_zscore": first_ratio_zscore("创业板/上证50比价", "50/创业板比价"),
            "sh50_300_zscore": first_ratio_zscore("上证50/300比价", "50/300比价"),
            "kc50_300_zscore": first_ratio_zscore("科创50/300比价", "科创50/沪深300比价"),
            "sh50_zscore": first_ratio_zscore("创业板/上证50比价", "50/创业板比价", "50/300比价"),
            "kc50_zscore": first_ratio_zscore("科创50/上证50比价"),
            "val300_zscore": first_ratio_zscore("300价值/成长比价"),
            "gro300_zscore": gro300_zscore,
            "hstech_zscore": first_ratio_zscore("恒生科技/恒生比价"),
        },
        "changes": {
            **{f"zz500_change_{window}d": value for window, value in zz500_changes.items()},
            **{f"zz1000_change_{window}d": value for window, value in zz1000_changes.items()},
            **{f"zz1000_500_change_{window}d": value for window, value in zz1000_500_changes.items()},
            **{f"cyb_change_{window}d": value for window, value in cyb_changes.items()},
            **{f"cyb_sh50_change_{window}d": value for window, value in cyb_sh50_changes.items()},
            **{f"sh50_300_change_{window}d": value for window, value in sh50_300_changes.items()},
            **{f"kc50_300_change_{window}d": value for window, value in kc50_300_changes.items()},
            **{f"sh50_change_{window}d": value for window, value in sh50_changes.items()},
            **{f"kc50_change_{window}d": value for window, value in kc50_changes.items()},
            **{f"val300_change_{window}d": value for window, value in val300_changes.items()},
            **{f"gro300_change_{window}d": value for window, value in gro300_changes.items()},
            **{f"hstech_change_{window}d": value for window, value in hstech_changes.items()},
        },
    }
    _fill_derived_relative_recommendations(snapshot)
    return snapshot


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
        "source": "feishu_hsi_erp_table",
    }


def compute_hsi_erp_snapshot_from_shared_signal(
    payload: dict[str, Any],
    hk_config: dict[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    """Load the scheduler-published HSI ERP interface without requiring a Feishu archive table."""
    records = payload.get("records")
    if isinstance(records, list):
        rows = [
            {"日期": record.get("date"), "恒生ERP": record.get("hsi_erp")}
            for record in records
            if isinstance(record, dict)
        ]
        snapshot = compute_hsi_erp_snapshot(filter_signal_rows_as_of(rows, as_of), hk_config)
        if snapshot.get("available"):
            snapshot["source"] = "shared_hsi_erp_history"
            return snapshot

    signal_date = parse_date(payload.get("latest_date") or payload.get("date"))
    latest_value = safe_float(payload.get("latest_value") or payload.get("equity_premium") or payload.get("hsi_erp"))
    percentile = safe_float(payload.get("percentile"))
    sample_count = safe_float(payload.get("sample_count"))
    if signal_date is None or latest_value is None or percentile is None or not sample_count:
        return _hsi_erp_neutral(hk_config)
    if signal_date.date() > as_of.date():
        return _hsi_erp_neutral(hk_config)

    thresholds = hk_config.get("percentile_thresholds", {"low": 40.0, "high": 60.0})
    weights = hk_config.get("aggressive_weights", {"low": 0.30, "neutral": 0.45, "high": 0.60})
    aggressive_weight = piecewise_linear_weight(
        percentile,
        float(thresholds["low"]), float(thresholds["high"]),
        float(weights["low"]), float(weights["neutral"]), float(weights["high"]),
    )
    return {
        "date": signal_date.strftime("%Y-%m-%d"),
        "equity_premium": round(latest_value, 4),
        "percentile": round(percentile, 2),
        "aggressive_weight": round(aggressive_weight, 4),
        "defensive_weight": round(1.0 - aggressive_weight, 4),
        "history_points": int(sample_count),
        "available": True,
        "source": "shared_hsi_erp_summary",
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
        "source": None,
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

def _reentry_gate(
    bucket: str,
    percentile: float | None,
    forced_exit: bool,
    threshold: float | None,
    reentry_state: dict[str, bool],
) -> tuple[bool, bool, bool]:
    """Apply a stateful reentry gate that starts only after a forced exit."""
    waiting_before = bool(reentry_state.get(bucket, False))
    if threshold is None:
        return False, waiting_before, False
    if forced_exit:
        return False, waiting_before, True
    if not waiting_before:
        return False, False, False
    if percentile is not None and float(percentile) <= float(threshold):
        return False, True, False
    return True, True, True


_REENTRY_PERCENTILE_FIELDS = {
    "zz500": ("500分位",),
    "zz1000": ("1000分位",),
    "cyb": ("创业板分位",),
    "val300": ("300价值分位",),
    "gro300": ("300成长分位",),
    "hstech": ("恒生科技分位",),
}


def derive_reentry_state_from_history(
    rows: list[dict[str, Any]],
    execution_config: dict[str, Any],
    before_date: datetime | None = None,
) -> dict[str, bool]:
    """Rebuild strategy reentry state from signal history before the current decision date."""
    dated_rows = sorted(
        (
            (dt, row)
            for row in rows
            if (dt := parse_date(get_first(row, "日期", "date", "trade_date"))) is not None
            and (before_date is None or dt.date() < before_date.date())
        ),
        key=lambda item: item[0],
    )
    thresholds = execution_config.get("aggressive_reentry_percentiles", {})
    forced_thresholds = execution_config.get("forced_exit_percentiles", {})
    anchor_keys = (
        execution_config.get("relative_signal_policy", {})
        .get("anchor_recommendation_keys", {})
    )
    state = {bucket: False for bucket in thresholds}
    kc50_300_history: list[float] = []

    for _, row in dated_rows:
        numerator = safe_float(get_first(row, "科创50指数"))
        denominator = safe_float(get_first(row, "沪深300"))
        if numerator is not None and denominator not in (None, 0):
            kc50_300_history.append(numerator / denominator)
        kc50_300_percentile = None
        if kc50_300_history:
            latest = kc50_300_history[-1]
            kc50_300_percentile = round(
                sum(value <= latest for value in kc50_300_history) / len(kc50_300_history) * 100.0,
                1,
            )

        for bucket, threshold in thresholds.items():
            signal_key = anchor_keys.get(bucket, bucket)
            if signal_key == "kc50_300":
                percentile = kc50_300_percentile
            else:
                fields = _REENTRY_PERCENTILE_FIELDS.get(bucket)
                percentile = safe_float(get_first(row, *fields)) if fields else None
            if percentile is None:
                continue
            forced_threshold = safe_float(forced_thresholds.get(bucket))
            if forced_threshold is not None and percentile >= forced_threshold:
                state[bucket] = True
            elif state.get(bucket, False) and percentile <= float(threshold):
                state[bucket] = False
    return state


def build_strategy_state(
    targets: dict[str, dict[str, Any]],
    as_of: str,
    source: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "as_of": as_of,
        "source": source,
        "bootstrap_policy": "unblocked_until_forced_exit",
        "reentry_waiting": {
            bucket: bool(target.get("reentry_waiting_after", False))
            for bucket, target in targets.items()
            if "reentry_waiting_after" in target
        },
    }

def _build_pool_aggressive_buckets(
    bucket_keys: list[str],
    relative_snapshot: dict[str, Any],
    execution_config: dict[str, Any],
    aggressive_alpha_total: float,
    bucket_metadata: dict[str, dict[str, Any]],
    anchor_context: dict[str, dict[str, Any]],
    feature_tilts: dict[str, dict[str, Any]],
    reentry_state: dict[str, bool],
) -> dict[str, dict[str, Any]]:
    """Build aggressive bucket targets for a pool."""
    base_weights = execution_config["alpha_base_weights"]
    caps = execution_config["alpha_bucket_caps"]
    multipliers = execution_config["recommendation_multipliers"]
    forced_exit_thresholds = execution_config.get("forced_exit_percentiles", {})
    reentry_thresholds = execution_config.get("aggressive_reentry_percentiles", {})
    trajectory_config = execution_config.get("trajectory_overlay", {})

    scores: dict[str, float] = {}
    for bucket in bucket_keys:
        base = float(base_weights.get(bucket, 0.3))
        anchor = anchor_context.get(bucket, {})
        feature_tilt = feature_tilts.get(bucket, {})
        rec = normalize_text(anchor.get("recommendation"))
        scores[bucket] = (
            base * recommendation_multiplier(rec, multipliers) * float(feature_tilt.get("multiplier", 1.0))
            if anchor.get("eligible") else 0.0
        )

    local_weights = normalize_to_weights(scores)

    targets: dict[str, dict[str, Any]] = {}
    for bucket, local_w in local_weights.items():
        anchor = anchor_context.get(bucket, {})
        anchor_key = anchor.get("signal_key", bucket)
        feature_tilt = feature_tilts.get(bucket, {})
        percentile = relative_snapshot["percentiles"].get(f"{anchor_key}_percentile")
        deviation = relative_snapshot.get("deviations", {}).get(f"{anchor_key}_deviation")
        change_5d = relative_snapshot.get("changes", {}).get(f"{anchor_key}_change_5d")
        force_threshold = forced_exit_thresholds.get(bucket)
        forced_exit = (
            force_threshold is not None and percentile is not None
            and float(percentile) >= float(force_threshold)
        )
        reentry_threshold = reentry_thresholds.get(bucket)
        reentry_blocked, waiting_before, waiting_after = _reentry_gate(
            bucket,
            percentile,
            forced_exit,
            reentry_threshold,
            reentry_state,
        )
        traj_mult, traj_reason = trajectory_multiplier(deviation, change_5d, trajectory_config)

        tw = aggressive_alpha_total * local_w
        tw = min(tw, float(caps.get(bucket, 1.0)))
        if not anchor.get("eligible"):
            tw = 0.0
        elif forced_exit:
            tw = 0.0
        elif reentry_blocked:
            tw = 0.0
        else:
            tw *= traj_mult
            tw = min(tw, float(caps.get(bucket, 1.0)))

        meta = bucket_metadata.get(bucket, {})
        targets[bucket] = {
            "bucket": bucket,
            "label": meta.get("label", bucket),
            "sleeve": meta.get("sleeve", "aggressive"),
            "pool": meta.get("pool", "ashare"),
            "signal": normalize_text(anchor.get("recommendation")),
            "anchor_signal": normalize_text(anchor.get("recommendation")),
            "anchor_signal_key": anchor_key,
            "anchor_eligible": bool(anchor.get("eligible")),
            "feature_tilt_multiplier": round(float(feature_tilt.get("multiplier", 1.0)), 4),
            "feature_tilts": feature_tilt.get("details", []),
            "allocation_score": round(scores[bucket], 6),
            "current_percentile": round(float(percentile), 2) if percentile is not None else None,
            "current_deviation": round(float(deviation), 2) if deviation is not None else None,
            "change_5d": round(float(change_5d), 2) if change_5d is not None else None,
            "forced_exit_threshold": float(force_threshold) if force_threshold is not None else None,
            "forced_exit": forced_exit,
            "reentry_threshold": float(reentry_threshold) if reentry_threshold is not None else None,
            "reentry_blocked": reentry_blocked,
            "reentry_waiting_before": waiting_before,
            "reentry_waiting_after": waiting_after,
            "trajectory_multiplier": round(float(traj_mult), 2),
            "trajectory_reason": traj_reason,
            "target_weight": round(tw, 4),
        }
    return targets


def _apply_bucket_group_caps(
    targets: dict[str, dict[str, Any]], group_caps: dict[str, Any]
) -> None:
    """Proportionally trim configured bucket groups to their hard caps."""
    for group_name, group_config in group_caps.items():
        buckets = [bucket for bucket in group_config.get("buckets", []) if bucket in targets]
        cap = safe_float(group_config.get("cap"))
        if cap is None or cap < 0 or not buckets:
            continue

        active_buckets = [
            bucket for bucket in buckets if float(targets[bucket].get("target_weight", 0.0)) > 0
        ]
        group_total = sum(float(targets[bucket].get("target_weight", 0.0)) for bucket in active_buckets)
        if group_total <= cap or not active_buckets:
            continue

        scale = cap / group_total
        allocated = 0.0
        for index, bucket in enumerate(active_buckets):
            previous = float(targets[bucket]["target_weight"])
            if index == len(active_buckets) - 1:
                capped_weight = round(max(0.0, cap - allocated), 4)
            else:
                capped_weight = round(previous * scale, 4)
                allocated += capped_weight
            targets[bucket]["target_weight"] = capped_weight
            targets[bucket]["group_cap_name"] = group_name
            targets[bucket]["group_cap"] = round(cap, 4)
            targets[bucket]["group_cap_released"] = round(previous - capped_weight, 4)


def _apply_bucket_caps(
    targets: dict[str, dict[str, Any]], bucket_caps: dict[str, Any]
) -> None:
    """Trim individual buckets after deployment scaling or internal rotation."""
    for bucket, raw_cap in bucket_caps.items():
        if bucket not in targets:
            continue
        cap = safe_float(raw_cap)
        if cap is None or cap < 0:
            continue
        previous = float(targets[bucket].get("target_weight", 0.0))
        if previous <= cap:
            continue
        capped_weight = round(cap, 4)
        targets[bucket]["target_weight"] = capped_weight
        targets[bucket]["bucket_cap"] = capped_weight
        targets[bucket]["bucket_cap_released"] = round(
            float(targets[bucket].get("bucket_cap_released", 0.0)) + previous - capped_weight,
            4,
        )


def _rec_for_bucket(bucket: str, recs: dict[str, str]) -> str:
    return recs.get(bucket, "标配")


def _style_pair_budget_ratio(val300_pct: float | None, style_config: dict[str, Any]) -> float:
    """Return fraction of style pair budget allocated to VAL300."""
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


def _balance_target_weights(targets: dict[str, dict[str, Any]], core_bucket: str = "hs300") -> None:
    total = sum(float(item.get("target_weight", 0.0)) for item in targets.values())
    diff = 1.0 - total
    core = targets.get(core_bucket)
    if core is None or abs(diff) < 0.00005:
        return
    core["target_weight"] = round(max(0.0, float(core.get("target_weight", 0.0)) + diff), 4)


def _piecewise_from_points(value: float | None, points: list[dict[str, Any]], default: float) -> float:
    if value is None or not points:
        return default
    clean_points: list[tuple[float, float]] = []
    for point in points:
        percentile = safe_float(point.get("percentile"))
        weight = safe_float(point.get("weight"))
        if percentile is not None and weight is not None:
            clean_points.append((float(percentile), float(weight)))
    if not clean_points:
        return default
    clean_points.sort(key=lambda item: item[0])
    if value <= clean_points[0][0]:
        return max(0.0, min(clean_points[0][1], 1.0))
    if value >= clean_points[-1][0]:
        return max(0.0, min(clean_points[-1][1], 1.0))
    for (left_pct, left_weight), (right_pct, right_weight) in zip(clean_points, clean_points[1:]):
        if left_pct <= value <= right_pct:
            ratio = (value - left_pct) / max(1e-9, right_pct - left_pct)
            return max(0.0, min(left_weight + (right_weight - left_weight) * ratio, 1.0))
    return default


def _deployment_factor(percentile: float | None, deployment_config: dict[str, Any], market: str) -> float:
    market_config = deployment_config.get(market, {})
    if not market_config.get("enabled", deployment_config.get("enabled", False)):
        return 1.0
    return _piecewise_from_points(
        percentile,
        market_config.get("breakpoints", []),
        float(market_config.get("default_weight", 1.0)),
    )


def _core_cap(percentile: float | None, deployment_config: dict[str, Any], bucket: str) -> float | None:
    bucket_config = deployment_config.get("core_caps", {}).get(bucket, {})
    if not bucket_config.get("enabled", deployment_config.get("enabled", False)):
        return None
    return _piecewise_from_points(
        percentile,
        bucket_config.get("breakpoints", []),
        float(bucket_config.get("default_weight", 1.0)),
    )


def _add_cash_target(targets: dict[str, dict[str, Any]], weight: float, reason: str) -> None:
    if abs(weight) < 0.00005:
        return
    existing = targets.get("cash")
    if existing:
        existing["target_weight"] = round(float(existing.get("target_weight", 0.0)) + weight, 4)
        existing["signal"] = reason
        return
    targets["cash"] = {
        "bucket": "cash",
        "label": "现金/低风险",
        "sleeve": "reserve",
        "pool": "reserve",
        "signal": reason,
        "target_weight": round(weight, 4),
    }


def _hs300_rotation_budget(percentile: float | None, deployment_config: dict[str, Any]) -> float:
    rotation_config = deployment_config.get("core_rotation", {}).get("hs300", {})
    if not rotation_config.get("enabled", False):
        return 0.0
    return _piecewise_from_points(
        percentile,
        rotation_config.get("breakpoints", []),
        float(rotation_config.get("default_weight", 0.0)),
    )


def _rotate_hs300_release(
    targets: dict[str, dict[str, Any]],
    released_weight: float,
    percentile: float | None,
    deployment_config: dict[str, Any],
    execution_config: dict[str, Any],
) -> float:
    """Move capped HS300 weight only to signal-qualified A-share satellite targets."""
    raw_budget = min(max(0.0, released_weight), _hs300_rotation_budget(percentile, deployment_config))
    budget = math.floor((raw_budget + 1e-12) * 10000) / 10000
    if budget <= 0:
        return 0.0

    eligible_signals = {
        normalize_text(value)
        for value in execution_config.get("relative_signal_policy", {}).get("anchor_eligible_recommendations", [])
    }
    caps = execution_config.get("alpha_bucket_caps", {})
    candidates = [
        key for key, target in targets.items()
        if key != "hs300"
        and target.get("pool") == "ashare"
        and float(target.get("target_weight", 0.0)) > 0
        and normalize_text(target.get("signal")) in eligible_signals
        and not target.get("forced_exit", False)
        and not target.get("reentry_blocked", False)
        and float(caps.get(key, 1.0)) > float(target.get("target_weight", 0.0))
    ]
    if not candidates:
        return 0.0

    remaining = budget
    allocated = 0.0
    for _ in range(len(candidates)):
        active = [
            key for key in candidates
            if float(caps.get(key, 1.0)) - float(targets[key].get("target_weight", 0.0)) > 0.00005
        ]
        if not active or remaining <= 0.00005:
            break
        score_total = sum(float(targets[key]["target_weight"]) for key in active)
        if score_total <= 0:
            break
        used_this_round = 0.0
        for key in active:
            current = float(targets[key]["target_weight"])
            room = max(0.0, float(caps.get(key, 1.0)) - current)
            available_budget = max(0.0, budget - allocated - used_this_round)
            allocation = min(remaining * current / score_total, room, available_budget)
            if allocation <= 0:
                continue
            new_weight = min(float(caps.get(key, 1.0)), round(current + allocation, 4))
            actual_added = max(0.0, new_weight - current)
            if actual_added > available_budget:
                actual_added = math.floor((available_budget + 1e-12) * 10000) / 10000
                new_weight = round(current + actual_added, 4)
            if actual_added <= 0:
                continue
            targets[key]["target_weight"] = new_weight
            targets[key]["core_rotation_added"] = round(
                float(targets[key].get("core_rotation_added", 0.0)) + actual_added, 4
            )
            used_this_round += actual_added
        if used_this_round <= 0.00005:
            break
        allocated += used_this_round
        remaining = max(0.0, budget - allocated)
    return round(min(allocated, budget), 4)


def apply_portfolio_deployment_layer(
    targets: dict[str, dict[str, Any]],
    erp_snapshot: dict[str, Any],
    hsi_erp_snapshot: dict[str, Any],
    execution_config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Scale ETF targets by ERP deployment waterline and send undeployed weight to cash."""
    deployment_config = execution_config.get("portfolio_deployment", {})
    if not deployment_config.get("enabled", False):
        _balance_target_weights(targets)
        return targets

    legacy_ashare_pool = sum(float(item.get("target_weight", 0.0)) for item in targets.values() if item.get("pool") == "ashare")
    legacy_hk_pool = sum(float(item.get("target_weight", 0.0)) for item in targets.values() if item.get("pool") == "hkshare")

    ashare_factor = _deployment_factor(safe_float(erp_snapshot.get("percentile")), deployment_config, "ashare")
    hk_cap = float(execution_config.get("cross_market", {}).get("hk_pool_cap", 0.20))
    if hsi_erp_snapshot.get("available"):
        hk_factor = _deployment_factor(safe_float(hsi_erp_snapshot.get("percentile")), deployment_config, "hkshare")
        hk_deployment = min(hk_cap, legacy_hk_pool) * hk_factor
    else:
        hk_deployment = min(hk_cap, legacy_hk_pool)
    ashare_deployment = max(0.0, 1.0 - hk_deployment) * ashare_factor

    scaled: dict[str, dict[str, Any]] = {}
    for key, item in targets.items():
        old_weight = float(item.get("target_weight", 0.0))
        if item.get("pool") == "ashare":
            new_weight = old_weight / max(legacy_ashare_pool, 1e-9) * ashare_deployment
        elif item.get("pool") == "hkshare":
            new_weight = old_weight / max(legacy_hk_pool, 1e-9) * hk_deployment
        else:
            new_weight = old_weight
        scaled[key] = {**item, "target_weight": round(max(0.0, new_weight), 4)}

    hs300_released = 0.0
    hs300_cap = _core_cap(safe_float(erp_snapshot.get("percentile")), deployment_config, "hs300")
    if hs300_cap is not None and "hs300" in scaled:
        current = float(scaled["hs300"].get("target_weight", 0.0))
        if current > hs300_cap:
            hs300_released = current - hs300_cap
            scaled["hs300"]["target_weight"] = round(hs300_cap, 4)
            scaled["hs300"]["core_cap"] = round(hs300_cap, 4)
            scaled["hs300"]["cap_released_to_cash"] = round(hs300_released, 4)

    _apply_bucket_caps(scaled, execution_config.get("alpha_bucket_caps", {}))
    _apply_bucket_group_caps(scaled, execution_config.get("alpha_group_caps", {}))
    rotation_before = sum(
        float(item.get("target_weight", 0.0))
        for key, item in scaled.items()
        if key != "hs300" and item.get("pool") == "ashare"
    )
    _rotate_hs300_release(
        scaled,
        hs300_released,
        safe_float(erp_snapshot.get("percentile")),
        deployment_config,
        execution_config,
    )
    _apply_bucket_caps(scaled, execution_config.get("alpha_bucket_caps", {}))
    _apply_bucket_group_caps(scaled, execution_config.get("alpha_group_caps", {}))
    rotation_added = max(0.0, sum(
        float(item.get("target_weight", 0.0))
        for key, item in scaled.items()
        if key != "hs300" and item.get("pool") == "ashare"
    ) - rotation_before)
    if hs300_released > 0:
        scaled["hs300"]["cap_released_to_rotation"] = round(rotation_added, 4)
        scaled["hs300"]["cap_released_to_cash"] = round(max(0.0, hs300_released - rotation_added), 4)

    surplus = max(0.0, hs300_released - rotation_added)

    hsi_cap = _core_cap(safe_float(hsi_erp_snapshot.get("percentile")), deployment_config, "hsi")
    if hsi_cap is not None and "hsi" in scaled:
        current = float(scaled["hsi"].get("target_weight", 0.0))
        if current > hsi_cap:
            surplus += current - hsi_cap
            scaled["hsi"]["target_weight"] = round(hsi_cap, 4)
            scaled["hsi"]["core_cap"] = round(hsi_cap, 4)
            scaled["hsi"]["cap_released_to_cash"] = round(current - hsi_cap, 4)

    non_cash_total = sum(float(item.get("target_weight", 0.0)) for key, item in scaled.items() if key != "cash")
    _add_cash_target(scaled, max(0.0, 1.0 - non_cash_total) + surplus, "ERP deployment reserve")
    total = sum(float(item.get("target_weight", 0.0)) for item in scaled.values())
    _add_cash_target(scaled, 1.0 - total, "rounding reserve")
    if "cash" in scaled:
        scaled["cash"]["target_weight"] = round(max(0.0, float(scaled["cash"].get("target_weight", 0.0))), 4)
    return scaled


def build_target_weights(
    erp_snapshot: dict[str, Any],
    hsi_erp_snapshot: dict[str, Any],
    relative_snapshot: dict[str, Any],
    execution_config: dict[str, Any],
    current_holdings: dict[str, float],
    reentry_state: dict[str, bool] | None = None,
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
    reentry_state = dict(reentry_state or {})
    trajectory_config = execution_config.get("trajectory_overlay", {})
    bucket_meta = execution_config.get("bucket_metadata", {})
    signal_policy = _relative_signal_policy(execution_config)
    anchor_context = _anchor_signal_context(recs, signal_policy)
    feature_tilts = _feature_tilt_context(recs, anchor_context, signal_policy)

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
        ft = forced_exit_thresholds.get(bucket)
        fe = ft is not None and pct is not None and float(pct) >= float(ft)
        rt = reentry_thresholds.get(bucket)
        rb, waiting_before, waiting_after = _reentry_gate(
            bucket, pct, fe, rt, reentry_state
        )
        tm, tr = trajectory_multiplier(dev, chg, trajectory_config)
        tw = min(tw, float(caps.get(bucket, 1.0)))
        if fe:
            tw = 0.0
        elif rb:
            tw = 0.0
        else:
            tw *= tm
            tw = min(tw, float(caps.get(bucket, 1.0)))
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
            "reentry_waiting_before": waiting_before,
            "reentry_waiting_after": waiting_after,
            "trajectory_multiplier": round(float(tm), 2),
            "trajectory_reason": tr,
            "target_weight": round(tw, 4),
        }

    val300_tw = style_pair_budget * val300_frac
    gro300_tw = style_pair_budget * (1.0 - val300_frac)
    targets["val300"] = _style_bucket("val300", val300_tw, "val300")
    targets["gro300"] = _style_bucket("gro300", gro300_tw, "gro300")

    # -- SH50 (defensive alpha) --
    sh50_anchor = anchor_context.get("sh50", {})
    sh50_anchor_key = sh50_anchor.get("signal_key", "sh50_300")
    sh50_percentile = relative_snapshot["percentiles"].get(f"{sh50_anchor_key}_percentile")
    sh50_ft = forced_exit_thresholds.get("sh50")
    sh50_exit_threshold = float(sh50_ft) if sh50_ft is not None else None
    sh50_fe = (
        sh50_exit_threshold is not None and sh50_percentile is not None
        and float(sh50_percentile) >= sh50_exit_threshold
    )

    sh50_tw = def_alpha_total * (1.0 - style_budget_ratio)
    sh50_signal = normalize_text(sh50_anchor.get("recommendation"))
    sh50_feature_tilt = feature_tilts.get("sh50", {})
    sh50_tw *= recommendation_multiplier(sh50_signal, multipliers)
    sh50_tw *= float(sh50_feature_tilt.get("multiplier", 1.0))
    sh50_tw = min(sh50_tw, float(caps.get("sh50", 0.18)))
    if not sh50_anchor.get("eligible") or sh50_fe:
        sh50_tw = 0.0

    meta_sh50 = bucket_meta.get("sh50", {})
    targets["sh50"] = {
        "bucket": "sh50", "label": meta_sh50.get("label", "防守价值"),
        "sleeve": "defensive", "pool": "ashare",
        "signal": sh50_signal,
        "anchor_signal": sh50_signal,
        "anchor_signal_key": sh50_anchor_key,
        "anchor_eligible": bool(sh50_anchor.get("eligible")),
        "feature_tilt_multiplier": round(float(sh50_feature_tilt.get("multiplier", 1.0)), 4),
        "feature_tilts": sh50_feature_tilt.get("details", []),
        "allocation_score": round(
            recommendation_multiplier(sh50_signal, multipliers) * float(sh50_feature_tilt.get("multiplier", 1.0)), 6
        ) if sh50_anchor.get("eligible") else 0.0,
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
        relative_snapshot, execution_config, agg_alpha_total,
        bucket_meta, anchor_context, feature_tilts, reentry_state,
    )
    _apply_bucket_group_caps(agg_buckets, execution_config.get("alpha_group_caps", {}))
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
            "reentry_waiting_before": bool(reentry_state.get("hstech", False)),
            "reentry_waiting_after": bool(reentry_state.get("hstech", False)),
            "reentry_blocked": False,
        }
        _balance_target_weights(targets)
        return apply_portfolio_deployment_layer(targets, erp_snapshot, hsi_erp_snapshot, execution_config)

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
    hstech_ft = forced_exit_thresholds.get("hstech")
    hstech_fe = hstech_ft is not None and hstech_pct is not None and float(hstech_pct) >= float(hstech_ft)
    hstech_rt = reentry_thresholds.get("hstech")
    hstech_rb, hstech_waiting_before, hstech_waiting_after = _reentry_gate(
        "hstech", hstech_pct, hstech_fe, hstech_rt, reentry_state
    )
    hstech_tm, hstech_tr = trajectory_multiplier(hstech_dev, hstech_chg, trajectory_config)

    hstech_tw = hk_agg_total
    hstech_tw = min(hstech_tw, float(caps.get("hstech", 0.08)))
    if hstech_fe:
        hstech_tw = 0.0
    elif hstech_rb:
        hstech_tw = 0.0
    else:
        hstech_tw *= hstech_tm
        hstech_tw = min(hstech_tw, float(caps.get("hstech", 0.08)))

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
        "reentry_waiting_before": hstech_waiting_before,
        "reentry_waiting_after": hstech_waiting_after,
        "trajectory_multiplier": round(float(hstech_tm), 2),
        "trajectory_reason": hstech_tr,
        "target_weight": round(hstech_tw, 4),
    }

    _balance_target_weights(targets)
    return apply_portfolio_deployment_layer(targets, erp_snapshot, hsi_erp_snapshot, execution_config)


# ── Rebalance plan ───────────────────────────────────────────

def build_rebalance_plan(
    current_holdings: dict[str, float],
    unmapped_holdings: list[dict[str, Any]],
    targets: dict[str, dict[str, Any]],
    holding_breakdown: dict[str, list[dict[str, Any]]] | None = None,
    total_capital: float | None = None,
) -> dict[str, Any]:
    current_equity_total = round(sum(current_holdings.values()), 2)
    using_total_capital = bool(total_capital and total_capital > 0)
    managed_total = round(float(total_capital), 2) if using_total_capital else current_equity_total
    unmapped_total = round(sum(item["amount"] for item in unmapped_holdings), 2)
    total_erp_amount = managed_total if using_total_capital else round(managed_total + unmapped_total, 2)
    current_cash_amount = round(max(0.0, managed_total - current_equity_total), 2)

    positions: list[dict[str, Any]] = []
    for bucket, target in targets.items():
        current_amount = current_cash_amount if bucket == "cash" else round(current_holdings.get(bucket, 0.0), 2)
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
        {"ashare": 0, "hkshare": 1, "reserve": 2}.get(item.get("pool", ""), 3),
        {"defensive": 0, "aggressive": 1, "reserve": 2}.get(item.get("sleeve", ""), 3),
        item.get("bucket", ""),
    ))
    target_weight_sum = sum(float(item.get("target_weight", 0.0)) for item in positions)

    return {
        "total_erp_amount": total_erp_amount,
        "managed_amount": managed_total,
        "capital_base_source": "total_capital" if using_total_capital else "mapped_erp_holdings",
        "current_equity_amount": current_equity_total,
        "current_cash_amount": current_cash_amount,
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
        "reserve_pool": round(sum(
            float(t.get("target_weight", 0)) for k, t in targets.items()
            if t.get("pool") == "reserve"
        ), 4),
        "positions": positions,
        "unmapped_holdings": unmapped_holdings,
    }


# ── Output ───────────────────────────────────────────────────

def build_reference_allocation_plan(
    targets: dict[str, dict[str, Any]],
    strategy_reference: dict[str, Any],
) -> dict[str, Any]:
    """Build a model allocation from a fixed notional, independent of live holdings."""
    notional = safe_float(strategy_reference.get("notional"))
    if notional is None or notional <= 0:
        raise ValueError("strategy_reference.notional must be a positive number")
    notional = round(notional, 2)

    positions = [
        {
            **target,
            "reference_amount": round(notional * float(target["target_weight"]), 2),
        }
        for target in targets.values()
    ]
    positions.sort(key=lambda item: (
        {"ashare": 0, "hkshare": 1, "reserve": 2}.get(item.get("pool", ""), 3),
        {"defensive": 0, "aggressive": 1, "reserve": 2}.get(item.get("sleeve", ""), 3),
        item.get("bucket", ""),
    ))
    target_weight_sum = sum(float(item.get("target_weight", 0.0)) for item in positions)

    return {
        "managed_amount": notional,
        "capital_base_source": "strategy_reference_notional",
        "reference_notional": notional,
        "reference_currency": str(strategy_reference.get("currency") or "CNY"),
        "actual_allocation_owner": str(strategy_reference.get("actual_allocation_owner") or "external_monitor"),
        "actual_allocation_in_strategy": False,
        "unmapped_amount": 0.0,
        "managed_position_count": 0,
        "unmapped_position_count": 0,
        "unmapped_holdings": [],
        "target_weight_sum": round(target_weight_sum, 6),
        "ashare_pool": round(sum(
            float(item.get("target_weight", 0.0)) for item in positions
            if item.get("pool") == "ashare"
        ), 4),
        "hkshare_pool": round(sum(
            float(item.get("target_weight", 0.0)) for item in positions
            if item.get("pool") == "hkshare"
        ), 4),
        "reserve_pool": round(sum(
            float(item.get("target_weight", 0.0)) for item in positions
            if item.get("pool") == "reserve"
        ), 4),
        "positions": positions,
    }


def erp_asset_update_bounds(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates: list[datetime] = []
    total = 0
    missing = 0
    for row in rows:
        third_level = parse_multiselect(get_first(row, "Ⅲ级分类", "III级分类", "三级分类"))
        if "ERP" not in third_level:
            continue
        total += 1
        dt = parse_date(row.get("_last_modified_time") or row.get("_created_time"))
        if dt:
            dates.append(dt)
        else:
            missing += 1
    return {
        "oldest": min(dates) if dates else None,
        "newest": max(dates) if dates else None,
        "total_count": total,
        "missing_count": missing,
    }


def latest_asset_update(rows: list[dict[str, Any]]) -> datetime | None:
    return erp_asset_update_bounds(rows)["newest"]


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
    strict_signal_dates: bool = True,
    portfolio_snapshot_as_of: datetime | None = None,
) -> dict[str, Any]:
    config = execution_config.get("data_quality", {})
    max_staleness = config.get("max_staleness_days", {})
    max_gap_days = int(config.get("max_signal_date_gap_days", 10))
    asset_update = erp_asset_update_bounds(asset_rows)
    asset_dt = portfolio_snapshot_as_of or asset_update["oldest"]
    asset_date_source = "operator_asserted_portfolio_snapshot_as_of" if portfolio_snapshot_as_of else "record_update_time"
    dates = {
        "erp": _snapshot_date(erp_snapshot),
        "relative": _snapshot_date(relative_snapshot),
        "hsi_erp": _snapshot_date(hsi_erp_snapshot),
        "asset": asset_dt,
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

    def add_signal_issue(message: str) -> None:
        if strict_signal_dates:
            errors.append(message)
        else:
            warnings.append(message)

    def add_recommendation_issue(message: str) -> None:
        if strict_signal_dates:
            errors.append(message)
        else:
            warnings.append(message)

    for name in ("erp", "relative"):
        dt = dates[name]
        if dt is None:
            add_signal_issue(f"{name} date is missing")
            ages[name] = None
            continue
        age = (as_of.date() - dt.date()).days
        ages[name] = age
        if age < 0:
            add_signal_issue(f"{name} date {dt.date()} is after as_of {as_of.date()}")
        elif age > limits[name]:
            add_signal_issue(f"{name} data is stale: {age} days > {limits[name]}")

    if dates["erp"] is not None and dates["relative"] is not None:
        gap = abs((dates["relative"].date() - dates["erp"].date()).days)
        if gap > max_gap_days:
            add_signal_issue(f"ERP/relative date gap is too large: {gap} days > {max_gap_days}")

    hsi_dt = dates["hsi_erp"]
    if hsi_erp_snapshot.get("available"):
        if hsi_dt is None:
            add_signal_issue("hsi_erp date is missing")
            ages["hsi_erp"] = None
        else:
            age = (as_of.date() - hsi_dt.date()).days
            ages["hsi_erp"] = age
            if age < 0:
                add_signal_issue(f"hsi_erp date {hsi_dt.date()} is after as_of {as_of.date()}")
            elif age > limits["hsi_erp"]:
                add_signal_issue(f"hsi_erp data is stale: {age} days > {limits['hsi_erp']}")
    else:
        ages["hsi_erp"] = None
        warnings.append("HSI ERP unavailable; no new HK strategy exposure is added")

    required_recommendations = _required_relative_recommendation_keys(execution_config)
    recommendations = relative_snapshot.get("recommendations", {})
    missing_recommendations = [
        key for key in required_recommendations
        if not normalize_text(recommendations.get(key))
    ]
    if missing_recommendations:
        add_recommendation_issue(
            "relative recommendations missing for "
            + ", ".join(missing_recommendations)
            + "; refusing to treat missing recommendations as neutral in rebalance mode"
        )

    if portfolio_snapshot_as_of is None and asset_update["missing_count"]:
        message = (
            f"asset record update timestamp is missing for "
            f"{asset_update['missing_count']} of {asset_update['total_count']} ERP rows"
        )
        if require_asset_timestamp:
            errors.append(message)
        else:
            warnings.append(message)
    elif portfolio_snapshot_as_of is not None and asset_update["missing_count"]:
        warnings.append(
            "portfolio snapshot date is operator asserted; "
            f"asset record update timestamp is missing for {asset_update['missing_count']} "
            f"of {asset_update['total_count']} ERP rows"
        )

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
            message = f"asset data is stale: {age} days > {limits['asset']}"
            if require_asset_timestamp:
                errors.append(message)
            else:
                warnings.append(message)

    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "dates": {key: value.strftime("%Y-%m-%d") if value else None for key, value in dates.items()},
        "asset_update": {
            "oldest": asset_update["oldest"].strftime("%Y-%m-%d") if asset_update["oldest"] else None,
            "newest": asset_update["newest"].strftime("%Y-%m-%d") if asset_update["newest"] else None,
            "total_count": asset_update["total_count"],
            "missing_count": asset_update["missing_count"],
        },
        "portfolio_snapshot_as_of": portfolio_snapshot_as_of.strftime("%Y-%m-%d") if portfolio_snapshot_as_of else None,
        "asset_date_source": asset_date_source,
        "portfolio_snapshot_assertion": {
            "mode": "operator_asserted" if portfolio_snapshot_as_of else None,
            "verified_by_record_timestamps": portfolio_snapshot_as_of is None and asset_update["missing_count"] == 0,
        },
        "relative_recommendations": {
            "required": required_recommendations,
            "missing": missing_recommendations,
        },
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
    execution_config = payload.get("inputs", {}).get("execution_config", {})
    positions_by_bucket = {item.get("bucket"): item for item in positions}
    for bucket, raw_cap in execution_config.get("alpha_bucket_caps", {}).items():
        cap = safe_float(raw_cap)
        if cap is None:
            continue
        bucket_weight = float(positions_by_bucket.get(bucket, {}).get("target_weight", 0.0))
        if bucket_weight > cap + tolerance:
            errors.append(
                f"bucket cap {bucket} exceeded: {bucket_weight:.6f} > {cap:.6f}"
            )
    for group_name, group_config in execution_config.get("alpha_group_caps", {}).items():
        cap = safe_float(group_config.get("cap"))
        if cap is None:
            continue
        group_weight = sum(
            float(positions_by_bucket.get(bucket, {}).get("target_weight", 0.0))
            for bucket in group_config.get("buckets", [])
        )
        if group_weight > cap + tolerance:
            errors.append(
                f"group cap {group_name} exceeded: {group_weight:.6f} > {cap:.6f}"
            )
    strategy_state = payload.get("strategy_state", {})
    if strategy_state.get("schema_version") != 1:
        errors.append("strategy_state schema_version must be 1")
    if strategy_state.get("source") != "derived_from_relative_history":
        errors.append("strategy_state source must be derived_from_relative_history")
    waiting = strategy_state.get("reentry_waiting")
    if not isinstance(waiting, dict):
        errors.append("strategy_state reentry_waiting must be an object")
    else:
        for bucket, position in positions_by_bucket.items():
            if "reentry_waiting_after" not in position:
                continue
            if waiting.get(bucket) is not bool(position.get("reentry_waiting_after")):
                errors.append(f"strategy_state reentry_waiting mismatch for {bucket}")
    errors.extend(payload.get("signals", {}).get("data_health", {}).get("errors", []))
    if payload.get("inputs", {}).get("execution_mode") == "rebalance":
        required_recommendations = _required_relative_recommendation_keys(
            payload.get("inputs", {}).get("execution_config", {})
        )
        recommendations = (
            payload.get("signals", {})
            .get("relative", {})
            .get("recommendations", {})
        )
        missing = [
            key for key in required_recommendations
            if not normalize_text(recommendations.get(key))
        ]
        already_reported = any("relative recommendations missing" in error for error in errors)
        if missing and not already_reported:
            errors.append(
                "relative recommendations missing for "
                + ", ".join(missing)
                + "; rebalance plans cannot treat missing recommendations as neutral"
            )
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
    print("ERP Execution Cloud Reference Plan v3.2")
    print("=" * 60)
    print(f"A-share ERP: {erp['date']}  premium={erp['equity_premium']:.2f}  pct={erp['percentile']:.2f}%  agg={erp['aggressive_weight']:.2%}")
    if hsi.get("available"):
        print(f"HK     ERP: {hsi['date']}  premium={hsi['equity_premium']:.2f}  pct={hsi['percentile']:.2f}%  agg={hsi['aggressive_weight']:.2%}")
    else:
        print(f"HK     ERP: {hsi.get('message', 'unavailable')}")

    pool_ashare = portfolio.get("ashare_pool", 0)
    pool_hk = portfolio.get("hkshare_pool", 0)
    pool_reserve = portfolio.get("reserve_pool", 0)
    print(f"Pool split: A-share={pool_ashare:.2%}  HK={pool_hk:.2%}  Reserve={pool_reserve:.2%}")
    print(f"Strategy reference notional: {portfolio['reference_notional']:,.2f} {portfolio['reference_currency']}")
    print(f"Actual allocation owner: {portfolio['actual_allocation_owner']}")
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
            f"weight={item['target_weight']:>7.2%}  reference={item['reference_amount']:>10,.2f}"
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
    parser.add_argument("--hsi-erp-signal-json", default=os.environ.get("ERP_EXEC_HSI_ERP_SIGNAL_JSON", ""))
    parser.add_argument("--erp-signal-json", default=os.environ.get("ERP_EXEC_ERP_SIGNAL_JSON", ""))
    parser.add_argument("--relative-signal-json", default=os.environ.get("ERP_EXEC_RELATIVE_SIGNAL_JSON", ""))
    parser.add_argument("--execution-config-path", default=os.environ.get("ERP_EXECUTION_CONFIG_PATH", str(DEFAULT_EXECUTION_CONFIG_PATH)))
    parser.add_argument("--output", default=os.environ.get("ERP_EXECUTION_OUTPUT_PATH", str(DEFAULT_OUTPUT)))
    parser.add_argument("--as-of", default=os.environ.get("ERP_EXECUTION_AS_OF", ""))
    parser.add_argument("--portfolio-snapshot-as-of", default=os.environ.get("ERP_PORTFOLIO_SNAPSHOT_AS_OF", ""))
    parser.add_argument(
        "--execution-mode",
        default=os.environ.get("ERP_EXECUTION_MODE", "rebalance"),
        choices=["rebalance", "research"],
        help="rebalance blocks on stale holdings; research keeps stale holdings as warnings",
    )
    parser.add_argument("--page-size", type=int, default=500)
    return parser.parse_args()


# ── Main ─────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    as_of = parse_date(args.as_of) if args.as_of else datetime.now(SHANGHAI_TZ)
    if as_of is None:
        raise ValueError(f"Invalid --as-of date: {args.as_of}")
    portfolio_snapshot_as_of = parse_date(args.portfolio_snapshot_as_of) if args.portfolio_snapshot_as_of else None
    if args.portfolio_snapshot_as_of and portfolio_snapshot_as_of is None:
        raise ValueError(f"Invalid --portfolio-snapshot-as-of date: {args.portfolio_snapshot_as_of}")
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    reader = FeishuBitableReader(app_id, app_secret) if app_id and app_secret else None
    if reader is None and (not args.erp_signal_json or not args.relative_signal_json):
        raise ValueError("Missing FEISHU_APP_ID / FEISHU_APP_SECRET for Feishu ERP or Relative signal reads")

    execution_config = sanitize_structure(json.loads(Path(args.execution_config_path).read_text(encoding="utf-8")))

    if args.erp_signal_json:
        erp_rows = load_shared_erp_rows(args.erp_signal_json)
        print(f"Loaded ERP shared signal JSON: {args.erp_signal_json} ({len(erp_rows)} rows)")
    else:
        assert reader is not None
        erp_rows = reader.list_all_records(args.erp_app_token, args.erp_table_id, args.page_size)
    erp_rows = filter_signal_rows_as_of(erp_rows, as_of)

    if args.relative_signal_json:
        relative_rows = load_shared_relative_rows(args.relative_signal_json)
        print(f"Loaded Relative shared signal JSON: {args.relative_signal_json} ({len(relative_rows)} rows)")
    else:
        assert reader is not None
        relative_rows = reader.list_all_records(args.relative_app_token, args.relative_table_id, args.page_size)
    relative_rows = filter_signal_rows_as_of(relative_rows, as_of)

    try:
        if reader is None:
            raise RuntimeError("Feishu credentials are not configured")
        asset_rows = reader.list_all_records(args.asset_app_token, args.asset_table_id, args.page_size)
    except Exception as exc:
        asset_rows = []
        print(f"Asset-table audit skipped: {exc}", file=sys.stderr)

    # HSI ERP: prefer the scheduler-published shared signal; Feishu is a legacy fallback.
    hsi_rows: list[dict[str, Any]] | None = None
    hsi_erp_payload: dict[str, Any] | None = None
    if args.hsi_erp_signal_json:
        try:
            candidate = json.loads(Path(args.hsi_erp_signal_json).read_text(encoding="utf-8"))
            hsi_erp_payload = candidate if isinstance(candidate, dict) else None
        except Exception as exc:
            print(f"HSI ERP shared signal unavailable: {exc}", file=sys.stderr)
    if hsi_erp_payload is None and args.hsi_erp_app_token and args.hsi_erp_table_id:
        try:
            if reader is None:
                raise RuntimeError("Feishu credentials are not configured")
            hsi_rows = reader.list_all_records(args.hsi_erp_app_token, args.hsi_erp_table_id, args.page_size)
            hsi_rows = filter_signal_rows_as_of(hsi_rows, as_of)
        except Exception:
            hsi_rows = None

    erp_snapshot = compute_erp_snapshot(erp_rows, execution_config["percentile_thresholds"], execution_config["aggressive_weights"])
    hsi_erp_snapshot = (
        compute_hsi_erp_snapshot_from_shared_signal(hsi_erp_payload, execution_config.get("hk_erp", {}), as_of)
        if hsi_erp_payload is not None
        else compute_hsi_erp_snapshot(hsi_rows, execution_config.get("hk_erp", {}))
    )
    relative_snapshot = compute_relative_snapshot(relative_rows)

    relative_decision_date = parse_date(relative_snapshot.get("date"))
    prior_reentry_state = derive_reentry_state_from_history(
        relative_rows,
        execution_config,
        before_date=relative_decision_date,
    )
    targets = build_target_weights(
        erp_snapshot,
        hsi_erp_snapshot,
        relative_snapshot,
        execution_config,
        {},
        reentry_state=prior_reentry_state,
    )
    strategy_state = build_strategy_state(
        targets,
        relative_snapshot["date"],
        "derived_from_relative_history",
    )
    portfolio = build_reference_allocation_plan(
        targets,
        execution_config.get("strategy_reference", {}),
    )
    strict_mode = args.execution_mode == "rebalance"
    data_health = build_data_health(
        erp_snapshot,
        hsi_erp_snapshot,
        relative_snapshot,
        asset_rows,
        execution_config,
        as_of,
        require_asset_timestamp=False,
        strict_signal_dates=strict_mode,
        portfolio_snapshot_as_of=portfolio_snapshot_as_of,
    )

    payload = {
        "version": "3.2",
        "signal_type": "erp_execution_plan",
        "generated_at": datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds"),
        "inputs": {
            "mode": "cloud_openapi",
            "execution_mode": args.execution_mode,
            "erp_table": {"app_token": args.erp_app_token, "table_id": args.erp_table_id},
            "relative_table": {"app_token": args.relative_app_token, "table_id": args.relative_table_id},
            "erp_signal_json": str(Path(args.erp_signal_json).resolve()) if args.erp_signal_json else None,
            "relative_signal_json": str(Path(args.relative_signal_json).resolve()) if args.relative_signal_json else None,
            "hsi_erp_signal_json": str(Path(args.hsi_erp_signal_json).resolve()) if args.hsi_erp_signal_json else None,
            "asset_table": {"app_token": args.asset_app_token, "table_id": args.asset_table_id, "role": "audit_only"},
            "hsi_erp_table": {"app_token": args.hsi_erp_app_token, "table_id": args.hsi_erp_table_id} if args.hsi_erp_app_token else None,
            "as_of": as_of.strftime("%Y-%m-%d"),
            "portfolio_snapshot_as_of": portfolio_snapshot_as_of.strftime("%Y-%m-%d") if portfolio_snapshot_as_of else None,
            "strategy_reference_notional": portfolio["reference_notional"],
            "actual_allocation_owner": portfolio["actual_allocation_owner"],
            "strategy_state_source": strategy_state["source"],
            "execution_config_path": str(Path(args.execution_config_path).resolve()),
            "execution_config": execution_config,
        },
        "signals": {
            "erp": erp_snapshot,
            "hsi_erp": hsi_erp_snapshot,
            "relative": relative_snapshot,
            "data_health": data_health,
        },
        "strategy_state": strategy_state,
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
