#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fetch monthly HSI PE history from HKCoding and validate recent observations
against the official Hang Seng monthly PE workbook.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests


HKCODING_URL = "https://hkcoding.com/hsi-pe-ratio"
OFFICIAL_XLS_URL = "https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/monthly/pe/hsi.xls"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def fetch_text(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def fetch_bytes(url: str) -> bytes:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.content


def parse_hkcoding_monthly_pe(html: str) -> pd.DataFrame:
    pattern = re.compile(
        r'\[new Date\((\d{4}),(\d{1,2}),(\d{1,2})\),"Col_A",([0-9]+\.[0-9]+)\]',
        re.I,
    )
    rows = []
    for year, month_zero_based, day, pe in pattern.findall(html):
        actual_month = int(month_zero_based) + 1
        date = datetime(int(year), actual_month, int(day))
        rows.append({"date": pd.Timestamp(date), "hsi_pe": float(pe)})

    if not rows:
        raise RuntimeError("No HKCoding HSI PE rows were parsed from the page.")

    df = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df


def parse_official_monthly_pe(xls_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(BytesIO(xls_bytes), header=2)
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "date", "Hang Seng Index": "hsi_pe"})
    df = df[["date", "hsi_pe"]].dropna()
    df["date"] = pd.to_datetime(df["date"])
    df["hsi_pe"] = pd.to_numeric(df["hsi_pe"], errors="coerce")
    df = df.dropna().sort_values("date").reset_index(drop=True)
    return df


def build_validation(hkcoding_df: pd.DataFrame, official_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    merged = hkcoding_df.merge(
        official_df,
        on="date",
        how="inner",
        suffixes=("_hkcoding", "_official"),
    )
    if merged.empty:
        raise RuntimeError("No overlapping months were found between HKCoding and official HSI PE data.")

    merged["diff"] = merged["hsi_pe_hkcoding"] - merged["hsi_pe_official"]
    merged["abs_diff"] = merged["diff"].abs()

    summary = {
        "overlap_count": int(len(merged)),
        "date_start": merged["date"].min().strftime("%Y-%m-%d"),
        "date_end": merged["date"].max().strftime("%Y-%m-%d"),
        "max_abs_diff": round(float(merged["abs_diff"].max()), 4),
        "mean_abs_diff": round(float(merged["abs_diff"].mean()), 4),
        "median_abs_diff": round(float(merged["abs_diff"].median()), 4),
        "latest_hkcoding": round(float(hkcoding_df.iloc[-1]["hsi_pe"]), 4),
        "latest_hkcoding_date": hkcoding_df.iloc[-1]["date"].strftime("%Y-%m-%d"),
        "latest_official": round(float(official_df.iloc[-1]["hsi_pe"]), 4),
        "latest_official_date": official_df.iloc[-1]["date"].strftime("%Y-%m-%d"),
    }
    return merged, summary


def write_outputs(
    output_dir: Path,
    hkcoding_df: pd.DataFrame,
    official_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    summary: dict,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    hkcoding_path = output_dir / "hsi_pe_monthly_hkcoding.csv"
    official_path = output_dir / "hsi_pe_monthly_official_recent.csv"
    validation_path = output_dir / "hsi_pe_monthly_validation.csv"
    summary_path = output_dir / "hsi_pe_monthly_validation_summary.json"

    hkcoding_df.to_csv(hkcoding_path, index=False, encoding="utf-8-sig")
    official_df.to_csv(official_path, index=False, encoding="utf-8-sig")
    validation_df.to_csv(validation_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "hkcoding_path": str(hkcoding_path),
        "official_path": str(official_path),
        "validation_path": str(validation_path),
        "summary_path": str(summary_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch HSI monthly PE history and validate sources.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()

    hkcoding_html = fetch_text(HKCODING_URL)
    official_xls = fetch_bytes(OFFICIAL_XLS_URL)

    hkcoding_df = parse_hkcoding_monthly_pe(hkcoding_html)
    official_df = parse_official_monthly_pe(official_xls)
    validation_df, summary = build_validation(hkcoding_df, official_df)
    paths = write_outputs(output_dir, hkcoding_df, official_df, validation_df, summary)

    print("=" * 60)
    print("HSI Monthly PE Validation")
    print("=" * 60)
    print(f"HKCoding samples: {len(hkcoding_df)}")
    print(f"Official recent samples: {len(official_df)}")
    print(
        f"Overlap: {summary['overlap_count']} months "
        f"({summary['date_start']} -> {summary['date_end']})"
    )
    print(f"Max abs diff: {summary['max_abs_diff']:.4f}")
    print(f"Mean abs diff: {summary['mean_abs_diff']:.4f}")
    print(f"Latest HKCoding: {summary['latest_hkcoding_date']} {summary['latest_hkcoding']:.4f}")
    print(f"Latest official: {summary['latest_official_date']} {summary['latest_official']:.4f}")
    print("")
    print(f"Saved HKCoding history: {paths['hkcoding_path']}")
    print(f"Saved official recent: {paths['official_path']}")
    print(f"Saved validation table: {paths['validation_path']}")
    print(f"Saved validation summary: {paths['summary_path']}")


if __name__ == "__main__":
    main()
