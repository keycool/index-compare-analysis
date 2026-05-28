#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Sync existing local index-compare outputs to Feishu Bitable without refetching data.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_COMPARE_MAIN = REPO_ROOT / ".claude" / "skills" / "index-compare" / "scripts" / "main.py"
INDEX_COMPARE_ROOT = INDEX_COMPARE_MAIN.parent.parent
PROCESSED_DATA = INDEX_COMPARE_ROOT / "data" / "processed_data.csv"
CONCLUSIONS_DATA = INDEX_COMPARE_ROOT / "data" / "conclusions.json"


def load_module():
    spec = importlib.util.spec_from_file_location("index_compare_main", INDEX_COMPARE_MAIN)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {INDEX_COMPARE_MAIN}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_module()
    module.load_env_file()

    if not PROCESSED_DATA.exists():
        raise FileNotFoundError(f"Missing processed data: {PROCESSED_DATA}")
    if not CONCLUSIONS_DATA.exists():
        raise FileNotFoundError(f"Missing conclusions data: {CONCLUSIONS_DATA}")

    with CONCLUSIONS_DATA.open("r", encoding="utf-8") as handle:
        conclusions = json.load(handle)

    processed_df = pd.read_csv(PROCESSED_DATA, parse_dates=["trade_date"])
    export_df = module.build_export_dataframe(processed_df, conclusions)
    result = module.sync_to_feishu_bitable(export_df)

    print(json.dumps(
        {
            "success": bool(result.get("success")),
            "record_count": int(len(export_df)),
            "latest_date": str(export_df.iloc[-1]["日期"]) if not export_df.empty else None,
            "bitable_result": result,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
