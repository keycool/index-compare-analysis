#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Push a compact ERP execution monitor snapshot to an optional webhook."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parent
PLAN_PATH = ROOT / "output" / "erp_execution_plan.json"


def _round(value: Any, digits: int = 4) -> float | None:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def build_snapshot(plan: dict[str, Any]) -> dict[str, Any]:
    portfolio = plan.get("portfolio", {})
    signals = plan.get("signals", {})
    health = signals.get("data_health", {})
    relative = signals.get("relative", {})
    positions = portfolio.get("positions", [])
    reference_allocations = sorted(
        [
            {
                "bucket": item.get("bucket"),
                "label": item.get("label"),
                "pool": item.get("pool"),
                "sleeve": item.get("sleeve"),
                "target_weight": _round(item.get("target_weight"), 4),
                "reference_amount": _round(item.get("reference_amount"), 2),
                "signal": item.get("signal"),
                "anchor_signal": item.get("anchor_signal"),
                "anchor_signal_key": item.get("anchor_signal_key"),
                "anchor_eligible": item.get("anchor_eligible"),
                "feature_tilt_multiplier": _round(item.get("feature_tilt_multiplier"), 4),
                "feature_tilts": item.get("feature_tilts", []),
                "allocation_score": _round(item.get("allocation_score"), 6),
                "forced_exit": item.get("forced_exit"),
                "reentry_blocked": item.get("reentry_blocked"),
                "reentry_threshold": _round(item.get("reentry_threshold"), 2),
                "reentry_waiting_before": item.get("reentry_waiting_before"),
                "reentry_waiting_after": item.get("reentry_waiting_after"),
                "trajectory_multiplier": _round(item.get("trajectory_multiplier"), 4),
                "trajectory_reason": item.get("trajectory_reason"),
            }
            for item in positions
            if item.get("bucket") != "cash"
        ],
        key=lambda item: float(item.get("reference_amount") or 0.0),
        reverse=True,
    )
    return {
        "signal_type": "erp_execution_monitor",
        "monitor_schema_version": 3,
        "version": plan.get("version"),
        "generated_at": plan.get("generated_at"),
        "execution_mode": plan.get("inputs", {}).get("execution_mode"),
        "trigger": {
            "source": os.environ.get("ERP_MONITOR_TRIGGER_SOURCE", "local"),
            "request_id": os.environ.get("ERP_MONITOR_REQUEST_ID", "").strip() or None,
        },
        "as_of": health.get("as_of"),
        "ok": not health.get("errors"),
        "errors": health.get("errors", []),
        "warnings": health.get("warnings", []),
        "dates": health.get("dates", {}),
        "portfolio": {
            "strategy_reference_notional": _round(portfolio.get("reference_notional"), 2),
            "reference_currency": portfolio.get("reference_currency"),
            "actual_allocation_owner": portfolio.get("actual_allocation_owner"),
            "actual_allocation_in_strategy": False,
            "ashare_pool": _round(portfolio.get("ashare_pool"), 4),
            "hkshare_pool": _round(portfolio.get("hkshare_pool"), 4),
            "reserve_pool": _round(portfolio.get("reserve_pool"), 4),
            "target_weight_sum": _round(portfolio.get("target_weight_sum"), 6),
        },
        "signals": {
            "erp": signals.get("erp", {}),
            "hsi_erp": signals.get("hsi_erp", {}),
            "relative": {
                "date": relative.get("date"),
                "recommendations": relative.get("recommendations", {}),
                "recommendation_sources": relative.get("recommendation_sources", {}),
                "percentiles": relative.get("percentiles", {}),
            },
        },
        "strategy_state": plan.get("strategy_state", {}),
        "reference_allocations": reference_allocations,
        "actual_allocation_contract": {
            "owner": "external_monitor",
            "strategy_input": "not_used",
            "expected_fields": ["observed_at", "total_amount", "currency", "positions"],
        },
    }


def main() -> None:
    webhook_url = os.environ.get("ERP_MONITOR_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("ERP monitor webhook not configured; skipping.")
        return
    if not PLAN_PATH.exists():
        raise RuntimeError(f"Missing plan file: {PLAN_PATH}")

    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    payload = build_snapshot(plan)
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("ERP_MONITOR_WEBHOOK_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.post(webhook_url, json=payload, headers=headers, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"monitor webhook failed: {response.status_code} {response.text[:300]}")
    print("ERP monitor snapshot pushed.")


if __name__ == "__main__":
    main()
