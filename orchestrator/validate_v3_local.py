#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Validate the current ERP v3 execution artifact with production rules.

This script intentionally does not reimplement allocation logic. It validates the
generated plan through orchestrator.erp_execution_cloud.validate_execution_payload
so local checks cannot drift from the production execution path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from erp_execution_cloud import validate_execution_payload


ROOT = Path(__file__).resolve().parent
DEFAULT_PLAN = ROOT / "output" / "erp_execution_plan.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an ERP execution plan artifact")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN), help="Path to erp_execution_plan.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan_path = Path(args.plan).resolve()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_execution_payload(payload)

    positions = payload.get("portfolio", {}).get("positions", [])
    total_weight = sum(float(item.get("target_weight", 0.0)) for item in positions)
    health = payload.get("signals", {}).get("data_health", {})
    print(f"ERP execution plan OK: {plan_path}")
    print(f"as_of={health.get('as_of', '-')}")
    print(f"target_weight_sum={total_weight:.4%}")
    if health.get("warnings"):
        print("warnings:")
        for warning in health["warnings"]:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
