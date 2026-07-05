#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ERP execution layer prototype.

Reads three Feishu bases directly via the official lark-cli:
1. ERP signal base
2. CSI300 relative base
3. Asset allocation base (beta|alpha table, ERP-tagged holdings only)

Then it builds a minimal executable plan:
- latest ERP percentile and implied aggressive sleeve weight
- latest relative recommendations
- current ERP-tagged holdings
- target weights/amounts for managed buckets
- rebalance deltas
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import unicodedata
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_ERP_BASE_TOKEN = "KfaSbpRdiaYFdWsCTRfcWpocnbd"
DEFAULT_ERP_TABLE_ID = "tblRAs2p4woXE1ig"
DEFAULT_RELATIVE_BASE_TOKEN = "POghbC154ablpxs20USc6veDnlh"
DEFAULT_RELATIVE_TABLE_ID = "tblnsUexqsEiLZs9"
DEFAULT_ASSET_BASE_TOKEN = "TiVJb2a5GaRiZTsoeXFcO6BCn8e"
DEFAULT_ASSET_TABLE_ID = "tbl1qLL1iXMykQRd"

DEFAULT_LOW_THRESHOLD = 40.0
DEFAULT_HIGH_THRESHOLD = 60.0
DEFAULT_LOW_AGGRESSIVE_WEIGHT = 0.35
DEFAULT_NEUTRAL_AGGRESSIVE_WEIGHT = 0.50
DEFAULT_HIGH_AGGRESSIVE_WEIGHT = 0.65

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "erp_execution_plan.json"
DEFAULT_LARK_CLI = Path(os.environ.get("APPDATA", r"C:\Users\Administrator\AppData\Roaming")) / "npm" / "lark-cli.cmd"
DEFAULT_STYLE_DATA_PATH = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "index-compare" / "data" / "raw_data.csv"
DEFAULT_STYLE_CONFIG_PATH = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "index-compare" / "config.json"
DEFAULT_EXECUTION_CONFIG_PATH = Path(__file__).resolve().parent / "erp_execution_config.json"

RECOMMENDATION_MULTIPLIERS = {
    "强烈超配": 1.30,
    "超配": 1.15,
    "标配": 1.00,
    "低配": 0.85,
    "强烈低配": 0.70,
}

VALUE_STYLE_TILT = {
    "强烈超配": 1.30,
    "超配": 1.15,
    "标配": 1.00,
    "低配": 0.90,
    "强烈低配": 0.80,
}

GROWTH_STYLE_TILT = {
    "强烈超配": {"cyb": 0.85, "zz500": 1.10, "zz1000": 1.10, "sh50_bonus": 1.15},
    "超配": {"cyb": 0.92, "zz500": 1.05, "zz1000": 1.05, "sh50_bonus": 1.08},
    "标配": {"cyb": 1.00, "zz500": 1.00, "zz1000": 1.00, "sh50_bonus": 1.00},
    "低配": {"cyb": 1.08, "zz500": 0.97, "zz1000": 0.97, "sh50_bonus": 0.95},
    "强烈低配": {"cyb": 1.15, "zz500": 0.94, "zz1000": 0.94, "sh50_bonus": 0.90},
}

BUCKET_METADATA = {
    "hs300": {"label": "沪深300", "sleeve": "defensive"},
    "sh50": {"label": "防守价值（上证50/红利）", "sleeve": "defensive"},
    "cyb": {"label": "创业板", "sleeve": "aggressive"},
    "zz500": {"label": "中证500", "sleeve": "aggressive"},
    "zz1000": {"label": "中证1000", "sleeve": "aggressive"},
}

HOLDING_ALIAS_MAP = {
    "沪深300ETF": "hs300",
    "300ETF": "hs300",
    "沪深300": "hs300",
    "上证50": "sh50",
    "50ETF": "sh50",
    "上证50ETF": "sh50",
    "红利ETF": "sh50",
    "创业板增强": "cyb",
    "创业板ETF": "cyb",
    "创业板指": "cyb",
    "创业板": "cyb",
    "500ETF": "zz500",
    "中证500": "zz500",
    "中证500ETF": "zz500",
    "1000ETF": "zz1000",
    "中证1000": "zz1000",
    "中证1000ETF": "zz1000",
}

IGNORED_ERP_HOLDINGS = {
    "科创50ETF",
    "恒生消费ETF",
    "十年期国债ETF",
}


@dataclass
class BaseTable:
    base_token: str
    table_id: str
    name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ERP execution plan from Feishu bases")
    parser.add_argument("--erp-base-token", default=DEFAULT_ERP_BASE_TOKEN)
    parser.add_argument("--erp-table-id", default=DEFAULT_ERP_TABLE_ID)
    parser.add_argument("--relative-base-token", default=DEFAULT_RELATIVE_BASE_TOKEN)
    parser.add_argument("--relative-table-id", default=DEFAULT_RELATIVE_TABLE_ID)
    parser.add_argument("--asset-base-token", default=DEFAULT_ASSET_BASE_TOKEN)
    parser.add_argument("--asset-table-id", default=DEFAULT_ASSET_TABLE_ID)
    parser.add_argument("--as-identity", default="user", choices=["user", "bot"])
    parser.add_argument("--limit", type=int, default=200, help="Page size for lark-cli pagination")
    parser.add_argument("--low-threshold", type=float, default=DEFAULT_LOW_THRESHOLD)
    parser.add_argument("--high-threshold", type=float, default=DEFAULT_HIGH_THRESHOLD)
    parser.add_argument("--low-aggressive-weight", type=float, default=DEFAULT_LOW_AGGRESSIVE_WEIGHT)
    parser.add_argument("--neutral-aggressive-weight", type=float, default=DEFAULT_NEUTRAL_AGGRESSIVE_WEIGHT)
    parser.add_argument("--high-aggressive-weight", type=float, default=DEFAULT_HIGH_AGGRESSIVE_WEIGHT)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--lark-cli", default=str(DEFAULT_LARK_CLI))
    parser.add_argument("--style-data-path", default=str(DEFAULT_STYLE_DATA_PATH))
    parser.add_argument("--style-config-path", default=str(DEFAULT_STYLE_CONFIG_PATH))
    parser.add_argument("--execution-config-path", default=str(DEFAULT_EXECUTION_CONFIG_PATH))
    return parser.parse_args()


def run_lark_record_list(table: BaseTable, identity: str, limit: int, offset: int, lark_cli: str) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("LARK_CLI_NO_PROXY", "1")

    command = [
        lark_cli,
        "base",
        "+record-list",
        "--base-token",
        table.base_token,
        "--table-id",
        table.table_id,
        "--as",
        identity,
        "--limit",
        str(limit),
        "--offset",
        str(offset),
        "--format",
        "json",
    ]

    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env=env,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Failed to fetch {table.name} via lark-cli (offset={offset}): {completed.stderr.strip() or completed.stdout.strip()}"
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from lark-cli for {table.name}: {exc}") from exc

    if not payload.get("ok"):
        raise RuntimeError(f"lark-cli returned failure for {table.name}: {payload}")
    return payload


def load_all_records(table: BaseTable, identity: str, limit: int, lark_cli: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        payload = run_lark_record_list(table, identity, limit, offset, lark_cli)
        data = payload.get("data", {})
        columns = data.get("fields", [])
        matrix = data.get("data", [])
        record_ids = data.get("record_id_list", [])
        has_more = bool(data.get("has_more"))

        for idx, values in enumerate(matrix):
            row = {
                "record_id": record_ids[idx] if idx < len(record_ids) else None,
            }
            for col_idx, field_name in enumerate(columns):
                normalized_field_name = unicodedata.normalize("NFKC", str(field_name)).strip()
                row[normalized_field_name] = values[col_idx] if col_idx < len(values) else None
            rows.append(row)

        if not has_more or not matrix:
            break
        offset += len(matrix)

    return rows


def parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
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
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return [text] if text else []


def recommendation_multiplier(text: str | None, multipliers: dict[str, Any] | None = None) -> float:
    if not text:
        return 1.0
    mapping = multipliers or RECOMMENDATION_MULTIPLIERS
    return float(mapping.get(str(text).strip(), 1.0))


def load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_execution_config(path: Path) -> dict[str, Any]:
    return load_json_file(path)


def piecewise_linear_weight(
    percentile: float,
    low_threshold: float,
    high_threshold: float,
    low_weight: float,
    neutral_weight: float,
    high_weight: float,
) -> float:
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
    positive_scores = {k: max(0.0, float(v)) for k, v in scores.items()}
    total = sum(positive_scores.values())
    if total <= 0:
        equal_weight = 1.0 / len(positive_scores) if positive_scores else 0.0
        return {k: equal_weight for k in positive_scores}
    return {k: v / total for k, v in positive_scores.items()}


def resolve_holding_bucket(
    name: str,
    alias_lookup: dict[str, str],
    ignored_lookup: set[str],
) -> str | None:
    direct = alias_lookup.get(name)
    if direct:
        return direct

    if name in ignored_lookup:
        return "__IGNORE__"

    if "科创50" in name or "恒生消费" in name or "国债" in name:
        return "__IGNORE__"
    if "红利" in name:
        return "sh50"
    if "创业板" in name:
        return "cyb"
    if "1000" in name:
        return "zz1000"
    if "500" in name:
        return "zz500"
    if "50" in name:
        return "sh50"
    if "300" in name:
        return "hs300"
    return None


def aggregate_current_holdings(
    rows: list[dict[str, Any]],
    alias_map: dict[str, str] | None = None,
    ignored_holdings: set[str] | None = None,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    aggregated: dict[str, float] = {}
    unmapped: list[dict[str, Any]] = []
    alias_lookup = alias_map or HOLDING_ALIAS_MAP
    ignored_lookup = ignored_holdings or IGNORED_ERP_HOLDINGS

    for row in rows:
        values = list(row.values())
        name_value = row.get("????") if "????" in row else (values[1] if len(values) > 1 else None)
        source_value = row.get("??") if "??" in row else (values[2] if len(values) > 2 else None)
        level2_value = row.get("II???") if "II???" in row else (values[4] if len(values) > 4 else None)
        amount_value = row.get("??") if "??" in row else (values[5] if len(values) > 5 else None)
        third_level_value = row.get("III???") if "III???" in row else (values[10] if len(values) > 10 else None)

        third_level = parse_multiselect(third_level_value)
        if "ERP" not in third_level:
            continue

        name = str(name_value or "").strip()
        bucket = resolve_holding_bucket(name, alias_lookup, ignored_lookup)
        if bucket == "__IGNORE__":
            continue

        amount = safe_float(amount_value) or 0.0
        if bucket:
            aggregated[bucket] = aggregated.get(bucket, 0.0) + amount
        else:
            unmapped.append(
                {
                    "name": name,
                    "amount": round(amount, 2),
                    "source": parse_multiselect(source_value),
                    "level_2": parse_multiselect(level2_value),
                }
            )

    return aggregated, unmapped


def build_holding_breakdown(
    rows: list[dict[str, Any]],
    alias_map: dict[str, str] | None = None,
    ignored_holdings: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    breakdown: dict[str, list[dict[str, Any]]] = {}
    alias_lookup = alias_map or HOLDING_ALIAS_MAP
    ignored_lookup = ignored_holdings or IGNORED_ERP_HOLDINGS

    for row in rows:
        values = list(row.values())
        name_value = row.get("????") if "????" in row else (values[1] if len(values) > 1 else None)
        amount_value = row.get("??") if "??" in row else (values[5] if len(values) > 5 else None)
        third_level_value = row.get("III???") if "III???" in row else (values[10] if len(values) > 10 else None)

        third_level = parse_multiselect(third_level_value)
        if "ERP" not in third_level:
            continue

        name = str(name_value or "").strip()
        amount = safe_float(amount_value) or 0.0
        bucket = resolve_holding_bucket(name, alias_lookup, ignored_lookup)
        if not bucket or bucket == "__IGNORE__":
            continue
        breakdown.setdefault(bucket, []).append({"name": name, "amount": round(amount, 2)})

    for items in breakdown.values():
        items.sort(key=lambda item: item["amount"], reverse=True)
    return breakdown


def latest_valid_row(rows: list[dict[str, Any]], required_fields: list[str]) -> dict[str, Any]:
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        dt = parse_date(row.get("日期"))
        if not dt:
            continue
        if not any(row.get(field) not in (None, "", []) for field in required_fields):
            continue
        candidates.append((dt, row))

    if not candidates:
        raise ValueError("No valid dated rows found")

    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def compute_erp_snapshot(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    valid: list[tuple[datetime, float]] = []
    for row in rows:
        dt = parse_date(row.get("日期"))
        premium = safe_float(row.get("股权溢价指数"))
        if not dt or premium is None:
            continue
        valid.append((dt, premium))

    if not valid:
        raise ValueError("ERP table has no valid premium history")

    valid.sort(key=lambda item: item[0])
    latest_date, latest_premium = valid[-1]
    history = [value for _, value in valid]
    percentile = round(sum(1 for value in history if value <= latest_premium) / len(history) * 100, 2)
    aggressive_weight = piecewise_linear_weight(
        percentile,
        args.low_threshold,
        args.high_threshold,
        args.low_aggressive_weight,
        args.neutral_aggressive_weight,
        args.high_aggressive_weight,
    )

    return {
        "date": latest_date.strftime("%Y-%m-%d"),
        "equity_premium": round(latest_premium, 4),
        "percentile": percentile,
        "aggressive_weight": round(aggressive_weight, 4),
        "defensive_weight": round(1.0 - aggressive_weight, 4),
        "history_points": len(history),
    }


def compute_relative_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest = latest_valid_row(
        rows,
        ["500建议", "1000建议", "创业板建议", "50建议", "500/300比价", "1000/300比价", "创业板/300比价", "50/300比价"],
    )
    dt = parse_date(latest.get("日期"))
    if not dt:
        raise ValueError("Relative table latest row has invalid date")

    return {
        "date": dt.strftime("%Y-%m-%d"),
        "recommendations": {
            "zz500": str(latest.get("500建议") or "").strip(),
            "zz1000": str(latest.get("1000建议") or "").strip(),
            "cyb": str(latest.get("创业板建议") or "").strip(),
            "sh50": str(latest.get("50建议") or "").strip(),
        },
        "ratios": {
            "zz500_ratio": safe_float(latest.get("500/300比价")),
            "zz1000_ratio": safe_float(latest.get("1000/300比价")),
            "cyb_ratio": safe_float(latest.get("创业板/300比价")),
            "sh50_ratio": safe_float(latest.get("50/300比价")) or safe_float(latest.get("50/创业板比价")),
        },
        "percentiles": {
            "zz500_percentile": safe_float(latest.get("500分位")),
            "zz1000_percentile": safe_float(latest.get("1000分位")),
            "cyb_percentile": safe_float(latest.get("创业板分位")),
            "sh50_percentile": safe_float(latest.get("50分位")),
        },
    }


def recommendation_from_percentile(percentile: float, levels: dict[str, Any]) -> str:
    extreme_low = float(levels.get("extreme_low", 15))
    low = float(levels.get("low", 30))
    high = float(levels.get("high", 70))
    extreme_high = float(levels.get("extreme_high", 85))

    if percentile <= extreme_low:
        return "强烈超配"
    if percentile <= low:
        return "超配"
    if percentile < high:
        return "标配"
    if percentile < extreme_high:
        return "低配"
    return "强烈低配"


def compute_val300_style_snapshot(style_data_path: Path, style_config_path: Path) -> dict[str, Any]:
    config = load_json_file(style_config_path)
    levels = config.get("percentile_levels", {})

    history: list[tuple[datetime, float, float, float]] = []
    with style_data_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            dt = parse_date(row.get("trade_date"))
            val300 = safe_float(row.get("VAL300"))
            gro300 = safe_float(row.get("GRO300"))
            if not dt or val300 is None or gro300 is None or gro300 == 0:
                continue
            history.append((dt, val300, gro300, val300 / gro300))

    if not history:
        return {
            "available": False,
            "message": "No valid VAL300/GRO300 history found",
        }

    history.sort(key=lambda item: item[0])
    latest_date, latest_val300, latest_gro300, latest_ratio = history[-1]
    ratio_history = [item[3] for item in history]
    percentile = round(sum(1 for value in ratio_history if value <= latest_ratio) / len(ratio_history) * 100, 2)
    recommendation = recommendation_from_percentile(percentile, levels)

    return {
        "available": True,
        "date": latest_date.strftime("%Y-%m-%d"),
        "val300": round(latest_val300, 4),
        "gro300": round(latest_gro300, 4),
        "ratio": round(latest_ratio, 6),
        "percentile": percentile,
        "recommendation": recommendation,
        "history_points": len(history),
        "influence_mode": "advisory_only",
    }


def build_target_weights(
    erp_snapshot: dict[str, Any],
    relative_snapshot: dict[str, Any],
    val300_style_snapshot: dict[str, Any],
    execution_config: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    aggressive_total = float(erp_snapshot["aggressive_weight"])
    recs = relative_snapshot["recommendations"]
    value_style_rec = str(val300_style_snapshot.get("recommendation") or "???")
    config = execution_config or {}
    recommendation_multipliers = config.get("recommendation_multipliers", RECOMMENDATION_MULTIPLIERS)
    value_style_tilt = config.get("value_style_tilt", VALUE_STYLE_TILT)
    growth_style_tilt = config.get("growth_style_tilt", GROWTH_STYLE_TILT)
    alpha_budget_weights = config.get(
        "alpha_budget_weights",
        {"low": 0.20, "neutral": 0.28, "high": 0.35},
    )
    alpha_base_weights = config.get(
        "alpha_base_weights",
        {"sh50": 1.0, "zz500": 0.4, "zz1000": 0.3, "cyb": 0.3},
    )
    alpha_bucket_caps = config.get(
        "alpha_bucket_caps",
        {"sh50": 0.18, "zz500": 0.12, "zz1000": 0.08, "cyb": 0.08},
    )

    value_tilt = float(value_style_tilt.get(value_style_rec, 1.0))
    growth_tilt = growth_style_tilt.get(value_style_rec, growth_style_tilt.get("???", {}))
    alpha_budget = piecewise_linear_weight(
        float(erp_snapshot["percentile"]),
        40.0,
        60.0,
        float(alpha_budget_weights.get("low", 0.20)),
        float(alpha_budget_weights.get("neutral", 0.28)),
        float(alpha_budget_weights.get("high", 0.35)),
    )
    alpha_budget = max(0.0, min(alpha_budget, 0.45))

    sh50_target = alpha_budget * (1.0 - aggressive_total)
    sh50_target *= recommendation_multiplier(recs.get("sh50"), recommendation_multipliers)
    sh50_target *= value_tilt
    sh50_target *= float(growth_tilt.get("sh50_bonus", 1.0))
    sh50_target = min(sh50_target, float(alpha_bucket_caps.get("sh50", 0.18)))

    aggressive_scores = {
        "cyb": float(alpha_base_weights.get("cyb", 0.3))
        * recommendation_multiplier(recs.get("cyb"), recommendation_multipliers)
        * float(growth_tilt.get("cyb", 1.0)),
        "zz500": float(alpha_base_weights.get("zz500", 0.4))
        * recommendation_multiplier(recs.get("zz500"), recommendation_multipliers)
        * float(growth_tilt.get("zz500", 1.0)),
        "zz1000": float(alpha_base_weights.get("zz1000", 0.3))
        * recommendation_multiplier(recs.get("zz1000"), recommendation_multipliers)
        * float(growth_tilt.get("zz1000", 1.0)),
    }
    aggressive_alpha_total = alpha_budget * aggressive_total
    aggressive_weights = normalize_to_weights(aggressive_scores)

    targets: dict[str, dict[str, Any]] = {}
    for bucket, local_weight in aggressive_weights.items():
        target_weight = aggressive_alpha_total * local_weight
        target_weight = min(target_weight, float(alpha_bucket_caps.get(bucket, 1.0)))
        targets[bucket] = {
            "bucket": bucket,
            "label": BUCKET_METADATA[bucket]["label"],
            "sleeve": "aggressive",
            "signal": recs.get(bucket) or "???",
            "style_overlay": value_style_rec,
            "target_weight": round(target_weight, 4),
        }

    targets["sh50"] = {
        "bucket": "sh50",
        "label": BUCKET_METADATA["sh50"]["label"],
        "sleeve": "defensive",
        "signal": recs.get("sh50") or "???",
        "style_overlay": value_style_rec,
        "target_weight": round(sh50_target, 4),
    }

    used_alpha_weight = sh50_target + sum(
        float(item["target_weight"]) for item in targets.values() if item["bucket"] != "sh50"
    )
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

        positions.append(
            {
                **target,
                "current_amount": current_amount,
                "current_weight": current_weight,
                "target_amount": target_amount,
                "delta_amount": delta_amount,
                "action": action,
                "holding_breakdown": (holding_breakdown or {}).get(bucket, []),
            }
        )

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


def render_daily_summary(script_dir: Path) -> Path | None:
    render_script = script_dir / "render_erp_daily_summary.py"
    if not render_script.exists():
        return None

    completed = subprocess.run(
        [sys.executable, str(render_script)],
        cwd=script_dir.parent,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Failed to render daily summary: {completed.stderr.strip() or completed.stdout.strip()}"
        )

    output_text = (completed.stdout or "").strip()
    if not output_text:
        return None
    return Path(output_text.splitlines()[-1].strip())


def print_summary(payload: dict[str, Any]) -> None:
    erp = payload["signals"]["erp"]
    relative = payload["signals"]["relative"]
    style = payload["signals"].get("val300_style", {})
    portfolio = payload["portfolio"]

    print("=" * 60)
    print("ERP Execution Plan")
    print("=" * 60)
    print(f"ERP latest date: {erp['date']}")
    print(f"ERP premium / percentile: {erp['equity_premium']:.2f} / {erp['percentile']:.2f}%")
    print(f"Aggressive / defensive: {erp['aggressive_weight']:.2%} / {erp['defensive_weight']:.2%}")
    print(f"Relative latest date: {relative['date']}")
    print("Recommendations:")
    for key, value in relative["recommendations"].items():
        print(f"  - {key}: {value or '标配'}")
    if style.get("available"):
        print(
            f"VAL300/GRO300: {style['ratio']:.4f} / {style['percentile']:.2f}% / {style['recommendation']}"
        )
    print(f"Managed ERP capital: {portfolio['managed_amount']:.2f}")
    if portfolio["unmapped_holdings"]:
        print(f"Unmapped ERP capital kept aside: {portfolio['unmapped_amount']:.2f}")
    print("Rebalance:")
    for item in portfolio["positions"]:
        print(
            f"  - {item['label']}: current {item['current_amount']:.2f} -> target {item['target_amount']:.2f} "
            f"({item['action']} {item['delta_amount']:+.2f})"
        )


def main() -> None:
    args = parse_args()
    execution_config = load_execution_config(Path(args.execution_config_path).resolve())

    erp_table = BaseTable(args.erp_base_token, args.erp_table_id, "ERP")
    relative_table = BaseTable(args.relative_base_token, args.relative_table_id, "CSI300 relative")
    asset_table = BaseTable(args.asset_base_token, args.asset_table_id, "Asset beta-alpha")

    erp_rows = load_all_records(erp_table, args.as_identity, args.limit, args.lark_cli)
    relative_rows = load_all_records(relative_table, args.as_identity, args.limit, args.lark_cli)
    asset_rows = load_all_records(asset_table, args.as_identity, args.limit, args.lark_cli)

    erp_snapshot = compute_erp_snapshot(erp_rows, args)
    relative_snapshot = compute_relative_snapshot(relative_rows)
    alias_map = {str(k): str(v) for k, v in execution_config.get("holding_alias_map", HOLDING_ALIAS_MAP).items()}
    ignored_holdings = set(str(item) for item in execution_config.get("ignored_erp_holdings", list(IGNORED_ERP_HOLDINGS)))
    current_holdings, unmapped_holdings = aggregate_current_holdings(asset_rows, alias_map, ignored_holdings)
    holding_breakdown = build_holding_breakdown(asset_rows, alias_map, ignored_holdings)
    val300_style_snapshot = compute_val300_style_snapshot(
        Path(args.style_data_path).resolve(),
        Path(args.style_config_path).resolve(),
    )
    targets = build_target_weights(erp_snapshot, relative_snapshot, val300_style_snapshot, execution_config)
    portfolio = build_rebalance_plan(current_holdings, unmapped_holdings, targets, holding_breakdown)

    payload = {
        "version": "1.0",
        "signal_type": "erp_execution_plan",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "erp_table": vars(erp_table),
            "relative_table": vars(relative_table),
            "asset_table": vars(asset_table),
            "identity": args.as_identity,
            "lark_cli": args.lark_cli,
            "execution_config_path": str(Path(args.execution_config_path).resolve()),
            "thresholds": {
                "low_threshold": args.low_threshold,
                "high_threshold": args.high_threshold,
                "low_aggressive_weight": args.low_aggressive_weight,
                "neutral_aggressive_weight": args.neutral_aggressive_weight,
                "high_aggressive_weight": args.high_aggressive_weight,
            },
            "execution_config": execution_config,
        },
        "signals": {
            "erp": erp_snapshot,
            "relative": relative_snapshot,
            "val300_style": val300_style_snapshot,
        },
        "portfolio": portfolio,
    }

    output_path = Path(args.output).resolve()
    save_output(output_path, payload)
    summary_path = render_daily_summary(Path(__file__).resolve().parent)
    print_summary(payload)
    print(f"\nSaved to: {output_path}")
    if summary_path is not None:
        print(f"Daily summary: {summary_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
