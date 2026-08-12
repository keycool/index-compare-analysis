#!/usr/bin/env python
"""Causal ERP allocation replay and one-variable sensitivity report.

This is a research audit. It does not change the production configuration, post to
Feishu, read holdings, or claim executable backtest performance.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from statistics import mean, stdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.erp_execution_cloud import (
    _REVERSE_REC,
    _derive_relative_recommendation,
    build_target_weights,
    compute_hsi_erp_snapshot_from_shared_signal,
    derive_reentry_state_from_history,
    parse_date,
    piecewise_linear_weight,
    safe_float,
    shared_erp_rows_from_payload,
)


DEFAULT_SHARED_DIR = ROOT.parent / "shared"
DEFAULT_CONFIG_PATH = ROOT / "orchestrator" / "erp_execution_config.json"
DEFAULT_REGISTRY_PATH = ROOT / "orchestrator" / "erp_parameter_registry.json"
DEFAULT_OUTPUT_DIR = ROOT / "orchestrator" / "output" / "research"
NOTIONAL = 1_000_000.0
MIN_CAUSAL_OBSERVATIONS = 60

RAW_TO_EXECUTION = {
    "date": "日期",
    "hs300": "沪深300",
    "zz500": "中证500",
    "zz1000": "中证1000",
    "zza500": "创业板指数",
    "sh50": "上证50指数",
    "kc50": "科创50指数",
    "val300": "300价值指数",
    "gro300": "300成长指数",
    "hsi": "恒生指数",
    "hstech": "恒生科技指数",
    "zz500_ratio": "500/300比价",
    "zz1000_ratio": "1000/300比价",
    "zz1000_500_ratio": "1000/500比价",
    "zza500_ratio": "创业板/300比价",
    "sh50_ratio": "创业板/上证50比价",
    "kc50_ratio": "科创50/上证50比价",
    "val300_ratio": "300价值/成长比价",
    "hstech_ratio": "恒生科技/恒生比价",
    "zz500_percentile": "500分位",
    "zz1000_percentile": "1000分位",
    "cyb_percentile": "创业板分位",
    "val300_percentile": "300价值分位",
    "gro300_percentile": "300成长分位",
    "hstech_percentile": "恒生科技分位",
}

CAUSAL_SIGNAL_FIELDS = {
    "zz500": "500/300比价",
    "zz1000": "1000/300比价",
    "zz1000_500": "1000/500比价",
    "cyb": "创业板/300比价",
    "cyb_sh50": "创业板/上证50比价",
    "sh50_300": "上证50/300比价",
    "kc50": "科创50/上证50比价",
    "kc50_300": "科创50/300比价",
    "val300": "300价值/成长比价",
    "hstech": "恒生科技/恒生比价",
}

RETURN_FIELDS = {
    "hs300": "沪深300",
    "sh50": "上证50指数",
    "zz500": "中证500",
    "zz1000": "中证1000",
    "cyb": "创业板指数",
    "kc50": "科创50指数",
    "val300": "300价值指数",
    "gro300": "300成长指数",
    "hsi": "恒生指数",
    "hstech": "恒生科技指数",
}

CASH_BUCKET = "cash"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _date_text(value: Any) -> str:
    parsed = parse_date(value)
    if not parsed:
        raise ValueError(f"Invalid date: {value!r}")
    return parsed.strftime("%Y-%m-%d")


def _raw_to_execution_row(record: dict[str, Any]) -> dict[str, Any]:
    row = {
        target: record[source]
        for source, target in RAW_TO_EXECUTION.items()
        if record.get(source) is not None
    }
    for numerator, denominator, target in (
        ("sh50", "hs300", "上证50/300比价"),
        ("kc50", "hs300", "科创50/300比价"),
        ("zza500", "sh50", "创业板/上证50比价"),
    ):
        numerator_value = safe_float(record.get(numerator))
        denominator_value = safe_float(record.get(denominator))
        if numerator_value is not None and denominator_value not in (None, 0):
            row[target] = numerator_value / denominator_value
    hstech = safe_float(record.get("hstech"))
    hstech_ratio = safe_float(record.get("hstech_ratio"))
    if "恒生指数" not in row and hstech is not None and hstech_ratio not in (None, 0):
        # The published Relative interface carries HKTECH and HKTECH/HSI, so recover HSI
        # without looking ahead to a separate price source.
        row["恒生指数"] = hstech / hstech_ratio
    return row


def _causal_erp_snapshot(history: list[float], signal_date: str) -> dict[str, Any]:
    latest = history[-1]
    percentile = round(sum(value <= latest for value in history) / len(history) * 100.0, 2)
    return {
        "date": signal_date,
        "equity_premium": round(latest, 4),
        "percentile": percentile,
        "history_points": len(history),
    }


def configured_erp_snapshot(snapshot: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Apply the tested ERP-regime configuration to a causal raw snapshot."""
    thresholds = config["percentile_thresholds"]
    weights = config["aggressive_weights"]
    aggressive_weight = piecewise_linear_weight(
        float(snapshot["percentile"]),
        float(thresholds["low"]),
        float(thresholds["high"]),
        float(weights["low"]),
        float(weights["neutral"]),
        float(weights["high"]),
    )
    configured = dict(snapshot)
    configured["aggressive_weight"] = round(aggressive_weight, 4)
    configured["defensive_weight"] = round(1.0 - aggressive_weight, 4)
    return configured


def _target_weights_for_input(
    item: dict[str, Any],
    config: dict[str, Any],
    simulated_holdings: dict[str, float],
    reentry_state: dict[str, bool],
) -> dict[str, dict[str, Any]]:
    """Use the same A-share and Hong Kong inputs for every research calculation."""
    return build_target_weights(
        configured_erp_snapshot(item["erp_snapshot"], config),
        item["hsi_erp_snapshot"],
        item["relative_snapshot"],
        config,
        simulated_holdings,
        reentry_state=reentry_state,
    )


def _next_reentry_state(targets: dict[str, dict[str, Any]]) -> dict[str, bool]:
    return {
        bucket: bool(target.get("reentry_waiting_after", False))
        for bucket, target in targets.items()
        if "reentry_waiting_after" in target
    }


def causal_percentile(values: list[Any], *, invert: bool = False) -> float | None:
    history: list[float] = []
    for value in values:
        if isinstance(value, (int, float)):
            numeric = float(value)
        else:
            numeric = safe_float(value)
        if numeric is not None and math.isfinite(numeric):
            history.append(numeric)
    if len(history) < MIN_CAUSAL_OBSERVATIONS:
        return None
    latest = 1.0 / history[-1] if invert and history[-1] else history[-1]
    transformed = [(1.0 / value if invert and value else value) for value in history]
    return round(sum(value <= latest for value in transformed) / len(transformed) * 100.0, 1)


def _zscore(values: list[float], window: int = 30) -> float | None:
    if len(values) < window:
        return None
    sample = values[-window:]
    average = mean(sample)
    dispersion = stdev(sample)
    return round((sample[-1] - average) / dispersion, 2) if dispersion else 0.0


def _deviation(values: list[float], window: int = 30) -> float | None:
    if len(values) < window:
        return None
    average = mean(values[-window:])
    return round((values[-1] / average - 1.0) * 100.0, 2) if average else None


def _changes(values: list[float]) -> dict[int, float | None]:
    result: dict[int, float | None] = {}
    for window in (5, 10, 20):
        if len(values) <= window or values[-1 - window] == 0:
            result[window] = None
        else:
            result[window] = round((values[-1] / values[-1 - window] - 1.0) * 100.0, 2)
    return result


def _causal_signal(values: list[float], invert: bool = False) -> dict[str, Any] | None:
    if len(values) < MIN_CAUSAL_OBSERVATIONS:
        return None
    series = [1.0 / value for value in values] if invert and all(values) else values
    percentile = causal_percentile(series)
    zscore = _zscore(series)
    if percentile is None or zscore is None:
        return None
    changes = _changes(series)
    recommendation = _derive_relative_recommendation(
        percentile, zscore, [changes[window] for window in (5, 10, 20)],
        {"extreme_low": 15, "low": 30, "high": 70, "extreme_high": 85},
    )
    return {
        "percentile": percentile,
        "zscore": zscore,
        "deviation": _deviation(series),
        "changes": changes,
        "recommendation": recommendation,
    }


def build_causal_relative_snapshot(histories: dict[str, list[float]], signal_date: str) -> dict[str, Any] | None:
    signals = {key: _causal_signal(values) for key, values in histories.items()}
    required = ("zz500", "zz1000", "cyb", "cyb_sh50", "sh50_300", "kc50", "kc50_300", "val300")
    if any(signals.get(key) is None for key in required):
        return None
    assert all(signals[key] is not None for key in required)

    val300 = signals["val300"]
    gro300 = _causal_signal(histories["val300"], invert=True)
    if gro300 is None:
        return None
    recommendations = {key: item["recommendation"] for key, item in signals.items() if item is not None}
    recommendations["gro300"] = gro300["recommendation"]
    recommendations["sh50"] = _REVERSE_REC.get(recommendations["cyb_sh50"], "")
    snapshot: dict[str, Any] = {
        "date": signal_date,
        "recommendations": recommendations,
        "recommendation_sources": {key: "causal_recomputed" for key in recommendations},
        "percentiles": {},
        "deviations": {},
        "changes": {},
        "zscores": {},
    }
    for key, item in signals.items():
        if item is None:
            continue
        snapshot["percentiles"][f"{key}_percentile"] = item["percentile"]
        snapshot["deviations"][f"{key}_deviation"] = item["deviation"]
        snapshot["zscores"][f"{key}_zscore"] = item["zscore"]
        for window, change in item["changes"].items():
            snapshot["changes"][f"{key}_change_{window}d"] = change
    for suffix, value in (("percentile", gro300["percentile"]), ("deviation", gro300["deviation"]), ("zscore", gro300["zscore"])):
        snapshot[f"{suffix}s" if suffix == "percentile" else f"{suffix}s"][f"gro300_{suffix}"] = value
    for window, change in gro300["changes"].items():
        snapshot["changes"][f"gro300_change_{window}d"] = change
    return snapshot


def scenario_definitions() -> list[dict[str, Any]]:
    return [
        {"name": "baseline", "path": None, "value": None},
        {"name": "ashare_60pct_waterline_minus_5pp", "path": "portfolio_deployment.ashare.breakpoints.3.weight", "value": 0.45},
        {"name": "ashare_60pct_waterline_plus_5pp", "path": "portfolio_deployment.ashare.breakpoints.3.weight", "value": 0.55},
        {"name": "erp_low_threshold_35", "path": "percentile_thresholds.low", "value": 35.0},
        {"name": "erp_high_threshold_65", "path": "percentile_thresholds.high", "value": 65.0},
        {"name": "erp_aggressive_high_0_60", "path": "aggressive_weights.high", "value": 0.60},
        {"name": "alpha_budget_neutral_minus_5pp", "path": "alpha_budget_weights.neutral", "value": 0.23},
        {"name": "alpha_budget_neutral_plus_5pp", "path": "alpha_budget_weights.neutral", "value": 0.33},
        {"name": "strong_over_multiplier_1_15", "path": "recommendation_multipliers.强烈超配", "value": 1.15},
        {"name": "trajectory_hot_multiplier_0_80", "path": "trajectory_overlay.hot.multiplier", "value": 0.80},
        {"name": "kc50_cap_0_06", "path": "alpha_bucket_caps.kc50", "value": 0.06},
        {"name": "kc50_cap_0_10", "path": "alpha_bucket_caps.kc50", "value": 0.10},
        {"name": "kc50_reentry_35", "path": "aggressive_reentry_percentiles.kc50", "value": 35.0},
        {"name": "style_pair_budget_0_20", "path": "style_pair.budget_ratio", "value": 0.20},
        {"name": "style_pair_budget_0_40", "path": "style_pair.budget_ratio", "value": 0.40},
    ]


def set_config_value(config: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    clone = copy.deepcopy(config)
    target: Any = clone
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    final = parts[-1]
    if isinstance(target, list):
        target[int(final)] = value
    else:
        target[final] = value
    return clone


def _max_drawdown(returns: list[float]) -> float:
    wealth = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in returns:
        wealth *= 1.0 + value
        peak = max(peak, wealth)
        drawdown = min(drawdown, wealth / peak - 1.0)
    return drawdown


def _metrics(
    returns: list[float], turnovers: list[float], weights: list[dict[str, float]], trading_days_per_period: int
) -> dict[str, Any]:
    if not returns:
        return {"observations": 0}
    wealth = math.prod(1.0 + value for value in returns)
    periods_per_year = 252.0 / trading_days_per_period
    years = len(returns) / periods_per_year
    annual_return = wealth ** (1.0 / years) - 1.0 if years > 0 else 0.0
    annual_volatility = stdev(returns) * math.sqrt(periods_per_year) if len(returns) > 1 else 0.0
    average_weights = {
        bucket: round(mean(day.get(bucket, 0.0) for day in weights), 4)
        for bucket in sorted({bucket for day in weights for bucket in day})
    }
    return {
        "observations": len(returns),
        "cumulative_return": round(wealth - 1.0, 6),
        "annualized_return": round(annual_return, 6),
        "annualized_volatility": round(annual_volatility, 6),
        "return_to_volatility": round(annual_return / annual_volatility, 4) if annual_volatility else None,
        "max_drawdown": round(_max_drawdown(returns), 6),
        "annualized_turnover": round(mean(turnovers) * periods_per_year, 6) if turnovers else 0.0,
        "average_weights": average_weights,
    }


def replay(
    inputs: list[dict[str, Any]],
    config: dict[str, Any],
    trading_days_per_period: int,
    initial_reentry_state: dict[str, bool] | None = None,
) -> dict[str, Any]:
    prior_weights: dict[str, float] = {"cash": 1.0}
    simulated_holdings: dict[str, float] = {}
    reentry_state = dict(initial_reentry_state or {})
    returns: list[float] = []
    turnovers: list[float] = []
    all_weights: list[dict[str, float]] = []
    skipped_returns = 0

    for index, item in enumerate(inputs):
        targets = _target_weights_for_input(item, config, simulated_holdings, reentry_state)
        reentry_state = _next_reentry_state(targets)
        weights = {bucket: float(target.get("target_weight", 0.0)) for bucket, target in targets.items()}
        turnover = sum(abs(weights.get(bucket, 0.0) - prior_weights.get(bucket, 0.0)) for bucket in set(weights) | set(prior_weights)) / 2.0
        turnovers.append(turnover)
        all_weights.append(weights)
        simulated_holdings = {bucket: weight * NOTIONAL for bucket, weight in weights.items() if bucket != "cash" and weight > 0}
        prior_weights = weights

        if index + 1 >= len(inputs):
            continue
        next_prices = inputs[index + 1]["prices"]
        portfolio_return = 0.0
        covered = True
        for bucket, field in RETURN_FIELDS.items():
            weight = weights.get(bucket, 0.0)
            if weight <= 0:
                continue
            start_price = safe_float(item["prices"].get(field))
            end_price = safe_float(next_prices.get(field))
            if start_price in (None, 0) or end_price is None:
                covered = False
                break
            portfolio_return += weight * (end_price / start_price - 1.0)
        if covered:
            returns.append(portfolio_return)
        else:
            skipped_returns += 1

    result = _metrics(returns, turnovers, all_weights, trading_days_per_period)
    result["return_coverage_skipped_days"] = skipped_returns
    result["target_dates"] = len(all_weights)
    return result


def _cash_yield_proxy(item: dict[str, Any], next_item: dict[str, Any]) -> float | None:
    """Convert the observed 10Y yield into a simple cash carry proxy, not a bond return."""
    annual_yield = safe_float(item.get("bond_yield"))
    if annual_yield is None:
        return None
    calendar_days = (date.fromisoformat(next_item["date"]) - date.fromisoformat(item["date"])).days
    return annual_yield / 100.0 * max(calendar_days, 0) / 365.0


def _bucket_period_returns(item: dict[str, Any], next_item: dict[str, Any]) -> dict[str, float] | None:
    returns: dict[str, float] = {}
    for bucket, field in RETURN_FIELDS.items():
        start_price = safe_float(item["prices"].get(field))
        end_price = safe_float(next_item["prices"].get(field))
        if start_price in (None, 0) or end_price is None:
            return None
        returns[bucket] = end_price / start_price - 1.0
    cash_return = _cash_yield_proxy(item, next_item)
    if cash_return is None:
        return None
    returns[CASH_BUCKET] = cash_return
    return returns


def attribution_report(
    inputs: list[dict[str, Any]],
    config: dict[str, Any],
    trading_days_per_period: int,
    initial_reentry_state: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Compare the allocation against transparent A-share and yield-carry proxies."""
    prior_weights: dict[str, float] = {CASH_BUCKET: 1.0}
    simulated_holdings: dict[str, float] = {}
    reentry_state = dict(initial_reentry_state or {})
    strategy_zero_returns: list[float] = []
    strategy_carry_returns: list[float] = []
    csi300_returns: list[float] = []
    balanced_returns: list[float] = []
    turnovers: list[float] = []
    all_weights: list[dict[str, float]] = []
    contributions: dict[str, list[float]] = {bucket: [] for bucket in (*RETURN_FIELDS, CASH_BUCKET)}
    hk_activity = {
        "hsi_active_periods": 0,
        "hstech_active_periods": 0,
        "hstech_reentry_blocked_periods": 0,
    }
    full_hk_activity = {
        "first_date": inputs[0]["date"] if inputs else None,
        "last_date": inputs[-1]["date"] if inputs else None,
        "periods": len(inputs),
        "hsi_active_periods": 0,
        "hstech_active_periods": 0,
        "hstech_reentry_blocked_periods": 0,
    }
    first_date: str | None = None
    last_date: str | None = None

    for index, item in enumerate(inputs[:-1]):
        next_item = inputs[index + 1]
        targets = _target_weights_for_input(item, config, simulated_holdings, reentry_state)
        reentry_state = _next_reentry_state(targets)
        weights = {bucket: float(target.get("target_weight", 0.0)) for bucket, target in targets.items()}
        full_hk_activity["hsi_active_periods"] += int(weights.get("hsi", 0.0) > 0)
        full_hk_activity["hstech_active_periods"] += int(weights.get("hstech", 0.0) > 0)
        full_hk_activity["hstech_reentry_blocked_periods"] += int(
            bool(targets.get("hstech", {}).get("reentry_blocked"))
        )
        simulated_holdings = {
            bucket: weight * NOTIONAL
            for bucket, weight in weights.items()
            if bucket != CASH_BUCKET and weight > 0
        }
        period_returns = _bucket_period_returns(item, next_item)
        if period_returns is None:
            continue
        hk_activity["hsi_active_periods"] += int(weights.get("hsi", 0.0) > 0)
        hk_activity["hstech_active_periods"] += int(weights.get("hstech", 0.0) > 0)
        hk_activity["hstech_reentry_blocked_periods"] += int(
            bool(targets.get("hstech", {}).get("reentry_blocked"))
        )
        turnover = sum(
            abs(weights.get(bucket, 0.0) - prior_weights.get(bucket, 0.0))
            for bucket in set(weights) | set(prior_weights)
        ) / 2.0
        zero_return = 0.0
        carry_return = 0.0
        for bucket, asset_return in period_returns.items():
            weight = weights.get(bucket, 0.0)
            contribution = weight * asset_return
            contributions[bucket].append(contribution)
            carry_return += contribution
            if bucket != CASH_BUCKET:
                zero_return += contribution

        strategy_zero_returns.append(zero_return)
        strategy_carry_returns.append(carry_return)
        csi300_returns.append(period_returns["hs300"])
        balanced_returns.append(0.5 * period_returns["hs300"] + 0.5 * period_returns[CASH_BUCKET])
        turnovers.append(turnover)
        all_weights.append(weights)
        prior_weights = weights
        first_date = first_date or item["date"]
        last_date = next_item["date"]

    carry_metrics = _metrics(strategy_carry_returns, turnovers, all_weights, trading_days_per_period)
    zero_metrics = _metrics(strategy_zero_returns, turnovers, all_weights, trading_days_per_period)
    csi300_metrics = _metrics(csi300_returns, [], [{"hs300": 1.0}] * len(csi300_returns), trading_days_per_period)
    balanced_metrics = _metrics(balanced_returns, [], [{"hs300": 0.5, CASH_BUCKET: 0.5}] * len(balanced_returns), trading_days_per_period)
    periods_per_year = 252.0 / trading_days_per_period
    bucket_contributions = []
    for bucket, values in contributions.items():
        average_weight = carry_metrics.get("average_weights", {}).get(bucket, 0.0)
        bucket_contributions.append({
            "bucket": bucket,
            "average_target_weight": average_weight,
            "annualized_arithmetic_contribution": round(mean(values) * periods_per_year, 6) if values else 0.0,
            "observations": len(values),
        })
    bucket_contributions.sort(key=lambda item: abs(item["annualized_arithmetic_contribution"]), reverse=True)
    return {
        "coverage": {
            "first_date": first_date,
            "last_date": last_date,
            "observations": len(strategy_carry_returns),
            "cash_yield_proxy_first_date": first_date,
            "hsi_erp": "causal monthly shared history; Hong Kong target returns are included when available",
            "bond_total_return": "unavailable; 10Y yield is used only as a simple cash carry proxy",
        },
        "strategy_cash_zero": zero_metrics,
        "strategy_cash_10y_yield_carry_proxy": carry_metrics,
        "benchmarks": {
            "csi300_total_equity": csi300_metrics,
            "half_csi300_half_10y_yield_carry_proxy": balanced_metrics,
        },
        "contributions": bucket_contributions,
        "hk_bucket_activity": hk_activity,
        "full_replay_hk_bucket_activity": full_hk_activity,
    }


def _target_weight_path(
    inputs: list[dict[str, Any]],
    config: dict[str, Any],
    initial_reentry_state: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    simulated_holdings: dict[str, float] = {}
    reentry_state = dict(initial_reentry_state or {})
    path: list[dict[str, Any]] = []
    for item in inputs:
        targets = _target_weights_for_input(item, config, simulated_holdings, reentry_state)
        reentry_state = _next_reentry_state(targets)
        weights = {bucket: float(target.get("target_weight", 0.0)) for bucket, target in targets.items()}
        path.append({"date": item["date"], "weights": weights})
        simulated_holdings = {
            bucket: weight * NOTIONAL
            for bucket, weight in weights.items()
            if bucket != CASH_BUCKET and weight > 0
        }
    return path


def _quantile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    location = (len(sorted_values) - 1) * percentile
    lower = math.floor(location)
    upper = math.ceil(location)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (location - lower)


def _high_utilization_episodes(equity_weights: list[float], threshold: float) -> list[int]:
    return [
        index for index, weight in enumerate(equity_weights)
        if weight >= threshold and (index == 0 or equity_weights[index - 1] < threshold)
    ]


def _forward_summary(returns: list[float], start_indexes: list[int], horizon_periods: int) -> dict[str, Any]:
    outcomes = []
    drawdowns = []
    for index in start_indexes:
        window = returns[index:index + horizon_periods]
        if len(window) != horizon_periods:
            continue
        outcomes.append(math.prod(1.0 + value for value in window) - 1.0)
        drawdowns.append(_max_drawdown(window))
    if not outcomes:
        return {"eligible_episodes": 0}
    return {
        "eligible_episodes": len(outcomes),
        "average_return": round(mean(outcomes), 6),
        "median_return": round(_quantile(outcomes, 0.5) or 0.0, 6),
        "positive_rate": round(sum(value > 0 for value in outcomes) / len(outcomes), 6),
        "worst_return": round(min(outcomes), 6),
        "worst_path_drawdown": round(min(drawdowns), 6),
    }


def utilization_report(
    inputs: list[dict[str, Any]],
    config: dict[str, Any],
    initial_reentry_state: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Describe realised equity utilisation and ex-post strategy results after high deployment."""
    path = _target_weight_path(inputs, config, initial_reentry_state)
    equity_weights = [sum(weight for bucket, weight in item["weights"].items() if bucket != CASH_BUCKET) for item in path]
    strategy_returns: list[float] = []
    for index, item in enumerate(inputs[:-1]):
        next_item = inputs[index + 1]
        period_return = 0.0
        complete = True
        for bucket, field in RETURN_FIELDS.items():
            start_price = safe_float(item["prices"].get(field))
            end_price = safe_float(next_item["prices"].get(field))
            if start_price in (None, 0) or end_price is None:
                complete = False
                break
            period_return += path[index]["weights"].get(bucket, 0.0) * (end_price / start_price - 1.0)
        if not complete:
            raise RuntimeError("Incomplete A-share price coverage in utilization analysis")
        strategy_returns.append(period_return)

    maximum = max(enumerate(equity_weights), key=lambda item: item[1])
    thresholds = [0.60, 0.65, 0.80, 0.90]
    threshold_counts = [
        {
            "threshold": threshold,
            "target_dates": sum(weight >= threshold for weight in equity_weights),
            "episodes": len(_high_utilization_episodes(equity_weights, threshold)),
        }
        for threshold in thresholds
    ]
    high_episode_starts = _high_utilization_episodes(equity_weights, 0.65)
    forward = {
        f"{days}d": _forward_summary(strategy_returns, high_episode_starts, periods)
        for days, periods in ((5, 1), (20, 4), (60, 12))
    }
    return {
        "definition": "equity utilization is total target weight excluding cash, including Hong Kong when causal HSI ERP is available",
        "summary": {
            "observations": len(equity_weights),
            "average": round(mean(equity_weights), 6),
            "median": round(_quantile(equity_weights, 0.5) or 0.0, 6),
            "p90": round(_quantile(equity_weights, 0.9) or 0.0, 6),
            "maximum": round(maximum[1], 6),
            "maximum_date": path[maximum[0]]["date"],
        },
        "threshold_counts": threshold_counts,
        "observed_high_utilization": {
            "threshold": 0.65,
            "episode_start_dates": [path[index]["date"] for index in high_episode_starts],
            "forward_strategy_results": forward,
            "interpretation": "descriptive ex-post result with overlapping future windows; not a tradable forecast",
        },
    }


def _pearson_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left) * sum((y - right_mean) ** 2 for y in right)
    )
    return numerator / denominator if denominator else None


def exposure_return_report(
    inputs: list[dict[str, Any]],
    config: dict[str, Any],
    initial_reentry_state: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Describe, without forecasting, the relationship between current equity exposure and next-period returns."""
    path = _target_weight_path(inputs, config, initial_reentry_state)
    observations: list[tuple[float, float]] = []
    for index, item in enumerate(inputs[:-1]):
        next_item = inputs[index + 1]
        next_return = 0.0
        for bucket, field in RETURN_FIELDS.items():
            start_price = safe_float(item["prices"].get(field))
            end_price = safe_float(next_item["prices"].get(field))
            if start_price in (None, 0) or end_price is None:
                raise RuntimeError("Incomplete A-share price coverage in exposure-return analysis")
            next_return += path[index]["weights"].get(bucket, 0.0) * (end_price / start_price - 1.0)
        exposure = sum(weight for bucket, weight in path[index]["weights"].items() if bucket != CASH_BUCKET)
        observations.append((exposure, next_return))

    bands = [
        (0.0, 0.40, "<=40%"),
        (0.40, 0.50, "40%-50%"),
        (0.50, 0.60, "50%-60%"),
        (0.60, math.inf, ">=60%"),
    ]
    groups = []
    for lower, upper, label in bands:
        values = [
            result for exposure, result in observations
            if (exposure >= lower if lower == 0 else exposure > lower) and exposure <= upper
        ]
        groups.append({
            "band": label,
            "observations": len(values),
            "average_next_5d_return": round(mean(values), 6) if values else None,
            "next_5d_volatility": round(stdev(values), 6) if len(values) > 1 else None,
            "positive_rate": round(sum(value > 0 for value in values) / len(values), 6) if values else None,
            "worst_next_5d_return": round(min(values), 6) if values else None,
            "best_next_5d_return": round(max(values), 6) if values else None,
        })
    exposures = [item[0] for item in observations]
    returns = [item[1] for item in observations]
    return {
        "definition": "current equity utilization versus the following five-trading-day strategy return across A-share and Hong Kong buckets; cash return is zero",
        "observations": len(observations),
        "pearson_exposure_to_next_return": round(_pearson_correlation(exposures, returns) or 0.0, 6),
        "pearson_exposure_to_absolute_next_return": round(_pearson_correlation(exposures, [abs(value) for value in returns]) or 0.0, 6),
        "groups": groups,
        "interpretation": "descriptive, overlapping market regimes; correlation is not a forecast or a causal estimate",
    }


def build_inputs(
    erp_payload: dict[str, Any],
    relative_payload: dict[str, Any],
    hsi_erp_payload: dict[str, Any],
    config: dict[str, Any],
    start_date: str | None,
    rebalance_every_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    erp_rows = shared_erp_rows_from_payload(erp_payload)
    erp_series = [
        (_date_text(row["日期"]), safe_float(row.get("股权溢价指数")))
        for row in erp_rows
        if safe_float(row.get("股权溢价指数")) is not None
    ]
    bond_yield_series = [
        (_date_text(record.get("date")), safe_float(record.get("bond_yield")))
        for record in erp_payload.get("records", [])
        if isinstance(record, dict) and safe_float(record.get("bond_yield")) is not None
    ]
    raw_records = [record for record in relative_payload.get("records", []) if isinstance(record, dict)]
    raw_records.sort(key=lambda record: _date_text(record.get("date")))
    execution_rows = [_raw_to_execution_row(record) for record in raw_records]

    causal_start = date.fromisoformat(start_date) if start_date else None
    required_causal_fields = (
        "zz500", "zz1000", "cyb", "sh50_300", "kc50_300", "val300", "hstech",
    )
    inputs: list[dict[str, Any]] = []
    skipped = {
        "before_start": 0,
        "missing_erp": 0,
        "missing_hsi_erp": 0,
        "missing_return_prices": 0,
        "insufficient_causal_history": 0,
    }
    histories: dict[str, list[float]] = {key: [] for key in CAUSAL_SIGNAL_FIELDS}
    usable_start_index: int | None = None
    erp_history: list[float] = []
    erp_index = 0
    bond_yield: float | None = None
    bond_index = 0
    for index, (raw, row) in enumerate(zip(raw_records, execution_rows)):
        row_date = _date_text(row.get("日期"))
        while erp_index < len(erp_series) and erp_series[erp_index][0] <= row_date:
            erp_history.append(float(erp_series[erp_index][1]))
            erp_index += 1
        while bond_index < len(bond_yield_series) and bond_yield_series[bond_index][0] <= row_date:
            bond_yield = bond_yield_series[bond_index][1]
            bond_index += 1
        for key, field in CAUSAL_SIGNAL_FIELDS.items():
            value = safe_float(row.get(field))
            if value is not None and math.isfinite(value):
                histories[key].append(value)
        if usable_start_index is None and all(
            len(histories[key]) >= MIN_CAUSAL_OBSERVATIONS
            for key in required_causal_fields
        ):
            usable_start_index = index
        if usable_start_index is None:
            skipped["insufficient_causal_history"] += 1
            continue
        if (index - usable_start_index) % rebalance_every_days != 0:
            continue
        if causal_start and date.fromisoformat(row_date) < causal_start:
            skipped["before_start"] += 1
            continue
        if not erp_history:
            skipped["missing_erp"] += 1
            continue
        relative_snapshot = build_causal_relative_snapshot(histories, row_date)
        if relative_snapshot is None:
            skipped["insufficient_causal_history"] += 1
            continue
        hsi_erp_snapshot = compute_hsi_erp_snapshot_from_shared_signal(
            hsi_erp_payload,
            config.get("hk_erp", {}),
            datetime.combine(date.fromisoformat(row_date), datetime.min.time()),
        )
        if not hsi_erp_snapshot.get("available"):
            skipped["missing_hsi_erp"] += 1
            continue
        if any(
            safe_float(row.get(field)) in (None, 0)
            for field in RETURN_FIELDS.values()
        ):
            skipped["missing_return_prices"] += 1
            continue
        erp_snapshot = _causal_erp_snapshot(erp_history, row_date)
        inputs.append({
            "date": row_date,
            "erp_snapshot": erp_snapshot,
            "hsi_erp_snapshot": hsi_erp_snapshot,
            "relative_snapshot": relative_snapshot,
            "prices": row,
            "bond_yield": bond_yield,
        })
    prehistory_rows = [
        row for row in execution_rows
        if inputs and _date_text(row.get("日期")) < inputs[0]["date"]
    ]
    return inputs, prehistory_rows, {
        "skipped": skipped,
        "candidate_dates": len(raw_records),
        "rebalance_every_trading_days": rebalance_every_days,
        "hsi_erp_history_points": len(hsi_erp_payload.get("records", [])),
        "causal_start_after_all_required_signals": _date_text(execution_rows[usable_start_index]["日期"])
        if usable_start_index is not None else None,
    }


def history_coverage(relative_payload: dict[str, Any], long_history_minimum: int = 2500) -> list[dict[str, Any]]:
    records = [record for record in relative_payload.get("records", []) if isinstance(record, dict)]
    items = [
        ("KC50 / HS300", lambda r: _ratio(r, "kc50", "hs300")),
        ("KC50 / SH50", lambda r: _ratio(r, "kc50", "sh50")),
        ("HS TECH / HSI", lambda r: safe_float(r.get("hstech_ratio"))),
        ("ZZ500 / HS300", lambda r: safe_float(r.get("zz500_ratio"))),
        ("ZZ1000 / HS300", lambda r: safe_float(r.get("zz1000_ratio"))),
    ]
    coverage = []
    for name, getter in items:
        valid = [record for record in records if getter(record) not in (None, 0)]
        coverage.append({
            "signal": name,
            "observations": len(valid),
            "first_date": valid[0].get("date") if valid else None,
            "last_date": valid[-1].get("date") if valid else None,
            "long_history_minimum": long_history_minimum,
            "status": "short_history_warning" if len(valid) < long_history_minimum else "long_history",
        })
    return coverage


def _ratio(record: dict[str, Any], numerator: str, denominator: str) -> float | None:
    top = safe_float(record.get(numerator))
    bottom = safe_float(record.get(denominator))
    return top / bottom if top is not None and bottom not in (None, 0) else None


def render_markdown(report: dict[str, Any]) -> str:
    baseline = report["sensitivity"][0]
    lines = [
        "# ERP 第一阶段研究审计",
        "",
        f"生成时间：`{report['generated_at']}`",
        f"因果回放区间：`{report['replay']['first_date']}` 至 `{report['replay']['last_date']}`，共 `{report['replay']['usable_dates']}` 个调仓观察日。",
        "",
        "## 研究边界",
        "",
        "- 本报告不改变生产配置、不触发飞书、不读取真实持仓。",
        "- 每日仅使用当日及以前数据重算 ERP 分位、比价分位、30 日 Z 分数与 5/10/20 日趋势。",
        f"- 回放采用独立重入状态机：首次未阻断，强制退出后等待达到配置分位；每 {report['replay']['rebalance_every_trading_days']} 个交易日调仓一次，使用指数代理收益和零交易成本假设。它是参数脆弱性检查，不是可执行业绩回测。",
        "- 回放纳入月频 HSI ERP、恒生指数及恒生科技；每期只使用当日及以前已发布的 HSI ERP 月末记录。恒生科技历史较短，完整组合区间会相应收敛。",
        "",
        "## 基线结果",
        "",
        f"- 年化收益代理：`{baseline['metrics'].get('annualized_return', 0):.2%}`",
        f"- 年化波动代理：`{baseline['metrics'].get('annualized_volatility', 0):.2%}`",
        f"- 最大回撤代理：`{baseline['metrics'].get('max_drawdown', 0):.2%}`",
        f"- 年化目标换手：`{baseline['metrics'].get('annualized_turnover', 0):.2%}`",
        "",
        "## 单变量敏感性",
        "",
        "| 场景 | 改动 | 年化收益代理差 | 最大回撤差 | 年化换手差 | 平均现金权重差 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    base_metrics = baseline["metrics"]
    for item in report["sensitivity"]:
        metrics = item["metrics"]
        delta = item["delta_from_baseline"]
        lines.append(
            f"| {item['name']} | {item['change']} | {delta.get('annualized_return', 0):+.2%} | "
            f"{delta.get('max_drawdown', 0):+.2%} | {delta.get('annualized_turnover', 0):+.2%} | "
            f"{delta.get('average_cash_weight', 0):+.2%} |"
        )
    lines.extend(["", "## 短历史观测", "", "| 信号 | 有效样本 | 首日 | 状态 |", "|---|---:|---|---|"])
    for item in report["history_coverage"]:
        lines.append(f"| {item['signal']} | {item['observations']} | {item['first_date'] or '-'} | {item['status']} |")
    lines.extend(["", "## 参数台账", "", f"- 参数家族数：`{report['parameter_registry']['entry_count']}`。", "- 状态为 `unvalidated` 的投资假设尚未通过样本外验证；不得根据本报告自动修改生产参数。"])
    return "\n".join(lines) + "\n"


def render_attribution_markdown(report: dict[str, Any]) -> str:
    attribution = report["attribution"]
    coverage = attribution["coverage"]
    strategy = attribution["strategy_cash_10y_yield_carry_proxy"]
    zero = attribution["strategy_cash_zero"]
    csi300 = attribution["benchmarks"]["csi300_total_equity"]
    balanced = attribution["benchmarks"]["half_csi300_half_10y_yield_carry_proxy"]
    lines = [
        "# ERP 策略归因与基准研究报告",
        "",
        f"生成时间：`{report['generated_at']}`",
        f"比较区间：`{coverage['first_date']}` 至 `{coverage['last_date']}`，共 `{coverage['observations']}` 个五日研究期。",
        "",
        "## 口径",
        "",
        "- A 股策略桶使用对应指数价格；策略目标权重来自因果重算的 ERP 与比价信号。",
        "- ‘10年国债收益率计息代理’只将当日10年国债收益率按日历日简单计入现金，不代表十年国债价格或总回报。",
        "- 港股部分使用月频 HSI ERP 的当时已知历史分位，恒生指数与恒生科技使用指数价格代理；未计 HKD/CNY 汇率、ETF 跟踪误差或交易成本。",
        "- 未计 ETF 跟踪误差、交易成本、滑点、税费和真实账户限制。",
        "",
        "## 策略与基准",
        "",
        "| 组合 | 年化收益代理 | 年化波动代理 | 最大回撤代理 |",
        "|---|---:|---:|---:|",
        f"| 策略（现金零收益） | {zero.get('annualized_return', 0):.2%} | {zero.get('annualized_volatility', 0):.2%} | {zero.get('max_drawdown', 0):.2%} |",
        f"| 策略（10年收益率计息代理） | {strategy.get('annualized_return', 0):.2%} | {strategy.get('annualized_volatility', 0):.2%} | {strategy.get('max_drawdown', 0):.2%} |",
        f"| 沪深300全权益 | {csi300.get('annualized_return', 0):.2%} | {csi300.get('annualized_volatility', 0):.2%} | {csi300.get('max_drawdown', 0):.2%} |",
        f"| 50%沪深300 + 50%收益率计息代理 | {balanced.get('annualized_return', 0):.2%} | {balanced.get('annualized_volatility', 0):.2%} | {balanced.get('max_drawdown', 0):.2%} |",
        "",
        "## 标的贡献",
        "",
        "贡献为每个五日研究期的权重乘指数收益，再年化为算术贡献；它用于解释方向，不与复利年化收益逐项相加。",
        "",
        "| 标的/现金 | 平均目标权重 | 年化算术贡献代理 |",
        "|---|---:|---:|",
    ]
    labels = {
        "cash": "现金（10年收益率计息代理）", "hs300": "沪深300", "sh50": "上证50",
        "zz500": "中证500", "zz1000": "中证1000", "cyb": "创业板", "kc50": "科创50",
        "val300": "300价值", "gro300": "300成长", "hsi": "恒生指数", "hstech": "恒生科技",
    }
    for item in attribution["contributions"]:
        lines.append(
            f"| {labels.get(item['bucket'], item['bucket'])} | {item['average_target_weight']:.2%} | "
            f"{item['annualized_arithmetic_contribution']:+.2%} |"
        )
    hk_activity = attribution["hk_bucket_activity"]
    full_hk_activity = attribution["full_replay_hk_bucket_activity"]
    lines.extend([
        "",
        f"完整因果回放从 `{full_hk_activity['first_date']}` 开始，共 `{full_hk_activity['periods']}` 个观察日；"
        f"恒生科技有 `{full_hk_activity['hstech_active_periods']}` 个目标持仓日，"
        f"有 `{full_hk_activity['hstech_reentry_blocked_periods']}` 个观察日处于等待重入。"
        "首次启动不再因空仓自动阻断；只有真实触发强制退出后才进入等待状态。",
        "",
        f"在有现金收益率代理的归因区间内，恒生指数有 `{hk_activity['hsi_active_periods']}` 个目标持仓期；"
        f"恒生科技有 `{hk_activity['hstech_active_periods']}` 个目标持仓期，"
        f"其中 `{hk_activity['hstech_reentry_blocked_periods']}` 个研究期被现有 `{30:.0f}%` 重入阈值阻断。"
        "这是策略状态结果，不代表恒生科技价格或 HSI ERP 数据缺失。",
    ])
    utilization = report["utilization"]
    summary = utilization["summary"]
    lines.extend([
        "",
        "## 权益资金利用率",
        "",
        "权益资金利用率为除现金以外的目标权重之和，包含 HSI ERP 可用期间的港股目标权重。",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 平均权益水位 | {summary['average']:.2%} |",
        f"| 中位数权益水位 | {summary['median']:.2%} |",
        f"| 90分位权益水位 | {summary['p90']:.2%} |",
        f"| 历史最高权益水位 | {summary['maximum']:.2%}（{summary['maximum_date']}） |",
        "",
        "| 权益水位阈值 | 达到该阈值的目标日 | 独立进入时段次数 |",
        "|---|---:|---:|",
    ])
    for item in utilization["threshold_counts"]:
        lines.append(f"| >= {item['threshold']:.0%} | {item['target_dates']} | {item['episodes']} |")
    high = utilization["observed_high_utilization"]
    lines.extend([
        "",
        f"历史中没有出现 80% 或 90% 的近满仓权益水位；因此以下只对实际历史上较高的 >= {high['threshold']:.0%} 水位进行事后观察。",
        "",
        "| 高水位后策略路径 | 有效时段 | 平均收益 | 中位数收益 | 正收益比例 | 最差收益 | 最差路径回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for horizon, item in high["forward_strategy_results"].items():
        if item.get("eligible_episodes", 0) == 0:
            lines.append(f"| 后 {horizon} | 0 | - | - | - | - | - |")
            continue
        lines.append(
            f"| 后 {horizon} | {item['eligible_episodes']} | {item['average_return']:.2%} | "
            f"{item['median_return']:.2%} | {item['positive_rate']:.2%} | {item['worst_return']:.2%} | "
            f"{item['worst_path_drawdown']:.2%} |"
        )
    exposure_return = report["exposure_return"]
    lines.extend([
        "",
        "## 暴露与下一期收益",
        "",
        "本表将本期权益水位与随后约五个交易日的组合收益配对，包含 A 股与港股指数代理。它检验暴露是否主要放大收益，还是主要放大波动；不构成预测。",
        "",
        f"- 权益水位与下一期收益的 Pearson 相关：`{exposure_return['pearson_exposure_to_next_return']:+.2f}`。",
        f"- 权益水位与下一期收益绝对值的 Pearson 相关：`{exposure_return['pearson_exposure_to_absolute_next_return']:+.2f}`。",
        "",
        "| 权益水位 | 样本数 | 下一期平均收益 | 下一期波动 | 正收益比例 | 最差收益 | 最好收益 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for item in exposure_return["groups"]:
        lines.append(
            f"| {item['band']} | {item['observations']} | {item['average_next_5d_return'] or 0:.2%} | "
            f"{item['next_5d_volatility'] or 0:.2%} | {item['positive_rate'] or 0:.2%} | "
            f"{item['worst_next_5d_return'] or 0:.2%} | {item['best_next_5d_return'] or 0:.2%} |"
        )
    lines.extend([
        "",
        "## 数据缺口",
        "",
        "- 10年国债收益率从 2022-03-10 才能覆盖本研究期，因此本报告不对 2020-2022 年的现金利息作假设性补齐。",
        "- 需要引入十年期国债总回报指数或可交易国债 ETF 净值后，才能形成真正的股债基准。",
        "- HSI ERP 为月频、恒生科技历史较短，港股结果只覆盖共同可得区间；应独立检查其样本量与时点错配，不应与 A 股长期序列等量齐观。",
        "- 若策略目标是 ERP 极高分位时接近全仓权益，当前历史实现并未达到该状态；需要单独审查部署水线、核心上限和卫星硬上限的组合约束，而不是从不足的极值样本推断表现。",
    ])
    return "\n".join(lines) + "\n"


def run_audit(
    shared_dir: Path,
    config_path: Path,
    registry_path: Path,
    start_date: str | None,
    rebalance_every_days: int = 5,
) -> dict[str, Any]:
    erp_payload = _json(shared_dir / "erp_signal.json")
    relative_payload = _json(shared_dir / "relative_signal.json")
    hsi_erp_payload = _json(shared_dir / "hsi_erp_signal.json")
    config = _json(config_path)
    if rebalance_every_days < 1:
        raise ValueError("rebalance_every_days must be positive")
    inputs, prehistory_rows, replay_meta = build_inputs(
        erp_payload, relative_payload, hsi_erp_payload, config, start_date, rebalance_every_days
    )
    if len(inputs) < 2:
        raise RuntimeError("Insufficient causal observations for ERP research replay")

    sensitivity = []
    baseline_metrics: dict[str, Any] | None = None
    for scenario in scenario_definitions():
        scenario_config = config if scenario["path"] is None else set_config_value(config, scenario["path"], scenario["value"])
        initial_state = derive_reentry_state_from_history(prehistory_rows, scenario_config)
        metrics = replay(inputs, scenario_config, rebalance_every_days, initial_state)
        if baseline_metrics is None:
            baseline_metrics = metrics
        base_cash = baseline_metrics["average_weights"].get("cash", 0.0)
        delta = {
            "annualized_return": metrics.get("annualized_return", 0.0) - baseline_metrics.get("annualized_return", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 0.0) - baseline_metrics.get("max_drawdown", 0.0),
            "annualized_turnover": metrics.get("annualized_turnover", 0.0) - baseline_metrics.get("annualized_turnover", 0.0),
            "average_cash_weight": metrics["average_weights"].get("cash", 0.0) - base_cash,
        }
        sensitivity.append({
            "name": scenario["name"],
            "change": "baseline" if scenario["path"] is None else f"{scenario['path']} = {scenario['value']}",
            "metrics": metrics,
            "delta_from_baseline": {key: round(value, 6) for key, value in delta.items()},
        })

    registry = _json(registry_path)
    report = {
        "report_type": "erp_strategy_phase_1_research_audit",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "research_only": True,
        "source": {
            "erp": str(shared_dir / "erp_signal.json"),
            "relative": str(shared_dir / "relative_signal.json"),
            "hsi_erp": str(shared_dir / "hsi_erp_signal.json"),
        },
        "replay": {"first_date": inputs[0]["date"], "last_date": inputs[-1]["date"], "usable_dates": len(inputs), **replay_meta},
        "assumptions": {
            "signal_timing": f"close on date t allocates to the next {rebalance_every_days} trading-day return",
            "reentry_state": "bootstrap unblocked; forced exit starts a persistent waiting state that clears only at the configured reentry percentile",
            "transaction_costs": "zero",
            "return_coverage": "A-share and Hong Kong index proxies plus cash; no ETF tracking, FX, slippage or tax",
        },
        "parameter_registry": {"path": str(registry_path), "entry_count": len(registry.get("entries", []))},
        "history_coverage": history_coverage(relative_payload),
        "attribution": attribution_report(
            inputs,
            config,
            rebalance_every_days,
            derive_reentry_state_from_history(prehistory_rows, config),
        ),
        "utilization": utilization_report(
            inputs, config, derive_reentry_state_from_history(prehistory_rows, config)
        ),
        "exposure_return": exposure_return_report(
            inputs, config, derive_reentry_state_from_history(prehistory_rows, config)
        ),
        "sensitivity": sensitivity,
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ERP causal replay and single-variable sensitivity audit")
    parser.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-date", help="Optional YYYY-MM-DD causal replay start date")
    parser.add_argument(
        "--rebalance-every-days", type=int, default=5,
        help="Research rebalance interval in trading days; default is weekly (5).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_audit(
        args.shared_dir, args.config, args.registry, args.start_date, args.rebalance_every_days
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "erp_strategy_phase_1_audit.json"
    markdown_path = args.output_dir / "erp_strategy_phase_1_audit.md"
    attribution_path = args.output_dir / "erp_strategy_attribution.json"
    attribution_markdown_path = args.output_dir / "erp_strategy_attribution.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    attribution_path.write_text(json.dumps(report["attribution"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    attribution_markdown_path.write_text(render_attribution_markdown(report), encoding="utf-8")
    print(f"Saved research audit: {json_path}")
    print(f"Saved research summary: {markdown_path}")
    print(f"Saved attribution report: {attribution_markdown_path}")


if __name__ == "__main__":
    main()
