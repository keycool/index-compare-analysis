#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ERP execution layer — local (lark-cli).
Reads Feishu bases via lark-cli, delegates all computation to the cloud module.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Import cloud module's computation functions ──────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))

from erp_execution_cloud import (  # noqa: E402
    compute_erp_snapshot,
    compute_hsi_erp_snapshot,
    compute_relative_snapshot,
    build_target_weights,
    build_rebalance_plan,
    build_holding_breakdown,
    build_data_health,
    validate_execution_payload,
    aggregate_current_holdings,
    save_output,
    print_summary,
    piecewise_linear_weight,
    normalize_to_weights,
    recommendation_multiplier,
    trajectory_multiplier,
    parse_date,
    safe_float,
    parse_multiselect,
    cell_texts,
    normalize_text,
    repair_text,
)

# ── Paths & defaults ────────────────────────────────────────
DEFAULT_ERP_BASE_TOKEN = "KfaSbpRdiaYFdWsCTRfcWpocnbd"
DEFAULT_ERP_TABLE_ID = "tblRAs2p4woXE1ig"
DEFAULT_RELATIVE_BASE_TOKEN = "POghbC154ablpxs20USc6veDnlh"
DEFAULT_RELATIVE_TABLE_ID = "tblnsUexqsEiLZs9"
DEFAULT_ASSET_BASE_TOKEN = "TiVJb2a5GaRiZTsoeXFcO6BCn8e"
DEFAULT_ASSET_TABLE_ID = "tbl1qLL1iXMykQRd"
DEFAULT_HSI_ERP_BASE_TOKEN = ""
DEFAULT_HSI_ERP_TABLE_ID = ""

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "erp_execution_plan.json"
DEFAULT_LARK_CLI = Path(
    os.environ.get("APPDATA", r"C:\\Users\\Administrator\\AppData\\Roaming")
) / "npm" / "lark-cli.cmd"
DEFAULT_EXECUTION_CONFIG_PATH = Path(__file__).resolve().parent / "erp_execution_config.json"


@dataclass
class BaseTable:
    base_token: str
    table_id: str
    name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ERP execution plan from Feishu bases (local lark-cli)")
    parser.add_argument("--erp-base-token", default=DEFAULT_ERP_BASE_TOKEN)
    parser.add_argument("--erp-table-id", default=DEFAULT_ERP_TABLE_ID)
    parser.add_argument("--relative-base-token", default=DEFAULT_RELATIVE_BASE_TOKEN)
    parser.add_argument("--relative-table-id", default=DEFAULT_RELATIVE_TABLE_ID)
    parser.add_argument("--asset-base-token", default=DEFAULT_ASSET_BASE_TOKEN)
    parser.add_argument("--asset-table-id", default=DEFAULT_ASSET_TABLE_ID)
    parser.add_argument("--hsi-erp-base-token", default=DEFAULT_HSI_ERP_BASE_TOKEN)
    parser.add_argument("--hsi-erp-table-id", default=DEFAULT_HSI_ERP_TABLE_ID)
    parser.add_argument("--as-identity", default="user", choices=["user", "bot"])
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--lark-cli", default=str(DEFAULT_LARK_CLI))
    parser.add_argument("--execution-config-path", default=str(DEFAULT_EXECUTION_CONFIG_PATH))
    parser.add_argument("--as-of", default=os.environ.get("ERP_EXECUTION_AS_OF", ""))
    parser.add_argument(
        "--execution-mode",
        default=os.environ.get("ERP_EXECUTION_MODE", "rebalance"),
        choices=["rebalance", "research"],
        help="rebalance blocks on stale holdings; research keeps stale holdings as warnings",
    )
    return parser.parse_args()


# ── lark-cli data readers ───────────────────────────────────

def run_lark_record_list(table: BaseTable, identity: str, limit: int, offset: int, lark_cli: str) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("LARK_CLI_NO_PROXY", "1")
    command = [
        lark_cli, "base", "+record-list",
        "--base-token", table.base_token,
        "--table-id", table.table_id,
        "--as", identity,
        "--limit", str(limit),
        "--offset", str(offset),
        "--format", "json",
    ]
    completed = subprocess.run(command, text=True, capture_output=True, env=env,
                               encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Failed to fetch {table.name} via lark-cli (offset={offset}): "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
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
            row = {"record_id": record_ids[idx] if idx < len(record_ids) else None}
            for col_idx, field_name in enumerate(columns):
                normalized = unicodedata.normalize("NFKC", str(field_name)).strip()
                row[normalized] = values[col_idx] if col_idx < len(values) else None
            rows.append(row)
        if not has_more or not matrix:
            break
        offset += len(matrix)
    return rows


def load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ── Main ────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    as_of = parse_date(args.as_of) if args.as_of else datetime.now().astimezone()
    if as_of is None:
        raise ValueError(f"Invalid --as-of date: {args.as_of}")
    execution_config = load_json_file(Path(args.execution_config_path).resolve())

    erp_table = BaseTable(args.erp_base_token, args.erp_table_id, "ERP")
    relative_table = BaseTable(args.relative_base_token, args.relative_table_id, "CSI300 relative")
    asset_table = BaseTable(args.asset_base_token, args.asset_table_id, "Asset beta-alpha")

    erp_rows = load_all_records(erp_table, args.as_identity, args.limit, args.lark_cli)
    relative_rows = load_all_records(relative_table, args.as_identity, args.limit, args.lark_cli)
    asset_rows = load_all_records(asset_table, args.as_identity, args.limit, args.lark_cli)

    # HSI ERP (optional)
    hsi_rows = None
    if args.hsi_erp_base_token and args.hsi_erp_table_id:
        try:
            hsi_table = BaseTable(args.hsi_erp_base_token, args.hsi_erp_table_id, "HSI ERP")
            hsi_rows = load_all_records(hsi_table, args.as_identity, args.limit, args.lark_cli)
        except Exception:
            hsi_rows = None

    erp_snapshot = compute_erp_snapshot(
        erp_rows, execution_config["percentile_thresholds"], execution_config["aggressive_weights"],
    )
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
        require_asset_timestamp=args.execution_mode == "rebalance",
    )

    payload = {
        "version": "3.0",
        "signal_type": "erp_execution_plan",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "mode": "lark_cli",
            "execution_mode": args.execution_mode,
            "erp_table": vars(erp_table),
            "relative_table": vars(relative_table),
            "asset_table": vars(asset_table),
            "identity": args.as_identity,
            "lark_cli": args.lark_cli,
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
    print_summary(payload)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
