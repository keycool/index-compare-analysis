#!/usr/bin/env python
"""Build an experiment-only daily HSI ERP series from official sources."""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import os
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


HSI_ROOT_URL = "https://www.hsi.com.hk"
HSI_CATALOG_URL = f"{HSI_ROOT_URL}/data/eng/download/daily-bulletin.json"
HSI_MONTHLY_PE_URL = (
    f"{HSI_ROOT_URL}/static/uploads/contents/en/dl_centre/monthly/pe/hsi.xls"
)
TREASURY_URL_TEMPLATE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs" / "hsi_daily_erp_experiment"
ALLOWED_SOURCE_HOSTS = {"www.hsi.com.hk", "home.treasury.gov", "api.tushare.pro"}


def build_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "index-compare-analysis-hsi-erp-experiment/1.0"})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_bytes(session: requests.Session, url: str, max_bytes: int) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SOURCE_HOSTS:
        raise ValueError(f"Source URL is not allowlisted: {url}")

    response = session.get(url, timeout=(10, 40))
    response.raise_for_status()
    final_url = urlparse(response.url)
    if final_url.scheme != "https" or final_url.hostname not in ALLOWED_SOURCE_HOSTS:
        raise RuntimeError(f"Source redirected outside the allowlist: {response.url}")
    if len(response.content) > max_bytes:
        raise RuntimeError(f"Source response exceeds {max_bytes} bytes: {url}")
    return response.content


def parse_hsi_catalog(payload: bytes) -> list[dict[str, Any]]:
    document = json.loads(payload.decode("utf-8"))
    reports: dict[date, str] = {}
    for series in document.get("indexSeriesList", []):
        if series.get("seriesCode") != "hsi":
            continue
        for report in series.get("reportList", []):
            if report.get("reportType") != "idx":
                continue
            for item in report.get("reportDate", []):
                report_date = datetime.strptime(item["date"][:10], "%Y-%m-%d").date()
                report_url = urljoin(HSI_ROOT_URL, item["url"])
                if urlparse(report_url).hostname != "www.hsi.com.hk":
                    raise ValueError(f"Unexpected HSI report host: {report_url}")
                reports[report_date] = report_url
    if not reports:
        raise RuntimeError("The official HSI catalog contains no HSI idx reports.")
    return [{"date": item, "url": reports[item]} for item in sorted(reports)]


def parse_hsi_idx_csv(payload: bytes, source_url: str) -> dict[str, Any]:
    text = payload.decode("utf-16")
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if len(rows) < 3:
        raise RuntimeError(f"HSI idx report has too few rows: {source_url}")

    headers = [value.strip() for value in rows[1]]
    for values in rows[2:]:
        row = dict(zip(headers, values))
        index_name = row.get("Index", "").strip()
        english_name = index_name.split("恒生", 1)[0].strip()
        if english_name != "Hang Seng Index" or row.get("Index Currency") != "HKD":
            continue
        trade_date = datetime.strptime(row["Trade Date"], "%Y%m%d").date()
        hsi_close = float(row["Index Close"])
        hsi_pe = float(row["PE Ratio (times)"])
        if hsi_close <= 0 or hsi_pe <= 0:
            raise RuntimeError(f"HSI idx report contains non-positive values: {source_url}")
        return {
            "date": trade_date,
            "hsi_close": hsi_close,
            "hsi_pe": hsi_pe,
            "hsi_source_url": source_url,
            "hsi_pe_source_type": "official_daily",
            "hsi_pe_anchor_date": trade_date,
            "hsi_pe_anchor_value": hsi_pe,
            "hsi_close_source": "Hang Seng Indexes official idx daily CSV",
        }
    raise RuntimeError(f"Hang Seng Index row not found in official idx report: {source_url}")


def parse_official_monthly_pe(payload: bytes) -> list[dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for the monthly HSI PE workbook") from exc

    try:
        frame = pd.read_excel(io.BytesIO(payload), header=2)
    except ImportError as exc:
        raise RuntimeError(
            "xlrd is required for the official HSI monthly PE workbook; "
            "install erp_improvement_sandbox/requirements-hsi-experiment.txt"
        ) from exc
    if frame.empty or "Hang Seng Index" not in frame.columns:
        raise RuntimeError("Official monthly HSI PE workbook has an unexpected schema.")
    date_column = frame.columns[0]
    output = []
    for raw_date, raw_pe in frame[[date_column, "Hang Seng Index"]].itertuples(index=False):
        parsed_date = pd.to_datetime(raw_date, errors="coerce")
        parsed_pe = pd.to_numeric(raw_pe, errors="coerce")
        if pd.isna(parsed_date) or pd.isna(parsed_pe) or float(parsed_pe) <= 0:
            continue
        output.append({"date": parsed_date.date(), "hsi_pe": float(parsed_pe)})
    if not output:
        raise RuntimeError("Official monthly HSI PE workbook contains no usable HSI rows.")
    return sorted(output, key=lambda row: row["date"])


def subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def fetch_tushare_hsi_closes(start_date: date, end_date: date) -> list[dict[str, Any]]:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for the six-month HSI close history.")
    try:
        import tushare as ts
    except ImportError as exc:
        raise RuntimeError("tushare is required for the six-month experiment") from exc

    ts.set_token(token)
    frame = ts.pro_api().index_global(
        ts_code="HSI",
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
        fields="trade_date,close",
    )
    if frame is None or frame.empty:
        raise RuntimeError("Tushare returned no HSI close history.")
    output = []
    for raw_date, raw_close in frame[["trade_date", "close"]].itertuples(index=False):
        trade_date = datetime.strptime(str(raw_date), "%Y%m%d").date()
        close = float(raw_close)
        if close > 0:
            output.append({"date": trade_date, "hsi_close": close})
    if not output:
        raise RuntimeError("Tushare HSI close history contains no usable rows.")
    return sorted(output, key=lambda row: row["date"])


def build_hybrid_hsi_records(
    close_records: list[dict[str, Any]],
    monthly_pe_records: list[dict[str, Any]],
    official_daily_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    close_by_date = {row["date"]: float(row["hsi_close"]) for row in close_records}
    close_dates = sorted(close_by_date)
    monthly_dates = sorted(row["date"] for row in monthly_pe_records)
    monthly_by_date = {row["date"]: float(row["hsi_pe"]) for row in monthly_pe_records}
    anchors = []
    for anchor_date in monthly_dates:
        close_index = bisect_right(close_dates, anchor_date) - 1
        if close_index < 0:
            continue
        close_date = close_dates[close_index]
        anchor_close = close_by_date[close_date]
        anchors.append(
            {
                "date": anchor_date,
                "hsi_pe": monthly_by_date[anchor_date],
                "hsi_close": anchor_close,
                "hsi_close_date": close_date,
            }
        )
    if not anchors:
        raise RuntimeError("No official monthly PE anchor could be paired with an HSI close.")

    anchor_dates = [row["date"] for row in anchors]
    official_by_date = {row["date"]: row for row in official_daily_records}
    output = []
    for trade_date in close_dates:
        official = official_by_date.get(trade_date)
        if official:
            output.append({**official})
            continue
        anchor_index = bisect_right(anchor_dates, trade_date) - 1
        if anchor_index < 0:
            continue
        anchor = anchors[anchor_index]
        earnings_level = anchor["hsi_close"] / anchor["hsi_pe"]
        estimated_pe = close_by_date[trade_date] / earnings_level
        output.append(
            {
                "date": trade_date,
                "hsi_close": close_by_date[trade_date],
                "hsi_pe": estimated_pe,
                "hsi_source_url": HSI_MONTHLY_PE_URL,
                "hsi_pe_source_type": "derived_from_official_monthly",
                "hsi_pe_anchor_date": anchor["date"],
                "hsi_pe_anchor_value": anchor["hsi_pe"],
                "hsi_close_source": "Tushare index_global HSI",
            }
        )
    if not output:
        raise RuntimeError("No hybrid HSI PE records could be built.")
    return sorted(output, key=lambda row: row["date"])


def parse_treasury_xml(payload: bytes) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(payload)
    data_ns = "http://schemas.microsoft.com/ado/2007/08/dataservices"
    metadata_ns = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
    rates: dict[date, float] = {}
    for properties in root.iter(f"{{{metadata_ns}}}properties"):
        date_node = properties.find(f"{{{data_ns}}}NEW_DATE")
        rate_node = properties.find(f"{{{data_ns}}}BC_10YEAR")
        if date_node is None or rate_node is None or not date_node.text or not rate_node.text:
            continue
        rate_date = datetime.fromisoformat(date_node.text.replace("Z", "+00:00")).date()
        rate = float(rate_node.text)
        if rate > 0:
            rates[rate_date] = rate
    if not rates:
        raise RuntimeError("The official Treasury feed contains no 10-year rates.")
    return [{"date": item, "us10y": rates[item]} for item in sorted(rates)]


def build_daily_erp_records(
    hsi_records: list[dict[str, Any]],
    treasury_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    treasury_by_date = {row["date"]: row["us10y"] for row in treasury_records}
    treasury_dates = sorted(treasury_by_date)
    output: list[dict[str, Any]] = []
    for hsi in sorted(hsi_records, key=lambda row: row["date"]):
        index = bisect_right(treasury_dates, hsi["date"]) - 1
        if index < 0:
            continue
        rate_date = treasury_dates[index]
        rate = treasury_by_date[rate_date]
        earnings_yield = 100.0 / hsi["hsi_pe"]
        output.append(
            {
                "date": hsi["date"].isoformat(),
                "hsi_close": round(hsi["hsi_close"], 4),
                "hsi_pe": round(hsi["hsi_pe"], 4),
                "earnings_yield_pct": round(earnings_yield, 6),
                "us10y_pct": round(rate, 4),
                "us10y_date": rate_date.isoformat(),
                "rate_lag_days": (hsi["date"] - rate_date).days,
                "hsi_erp_pct": round(earnings_yield - rate, 6),
                "hsi_source_url": hsi["hsi_source_url"],
                "hsi_pe_source_type": hsi.get("hsi_pe_source_type", "unknown"),
                "hsi_pe_anchor_date": hsi.get("hsi_pe_anchor_date", hsi["date"]).isoformat(),
                "hsi_pe_anchor_value": round(
                    float(hsi.get("hsi_pe_anchor_value", hsi["hsi_pe"])), 4
                ),
                "hsi_close_source": hsi.get("hsi_close_source", "unknown"),
                "treasury_source_url": TREASURY_URL_TEMPLATE.format(year=rate_date.year),
            }
        )
    if not output:
        raise RuntimeError("No HSI observations could be aligned with prior Treasury rates.")
    return output


def assess_freshness(
    records: list[dict[str, Any]],
    as_of: date,
    max_hsi_age_days: int,
    max_rate_lag_days: int,
) -> dict[str, Any]:
    latest = records[-1]
    hsi_date = date.fromisoformat(latest["date"])
    hsi_age_days = (as_of - hsi_date).days
    errors = []
    if hsi_age_days < 0:
        errors.append("latest HSI record is after as_of")
    if hsi_age_days > max_hsi_age_days:
        errors.append(f"HSI record age {hsi_age_days} days exceeds {max_hsi_age_days}")
    if latest["rate_lag_days"] > max_rate_lag_days:
        errors.append(
            f"Treasury rate lag {latest['rate_lag_days']} days exceeds {max_rate_lag_days}"
        )
    return {
        "ok": not errors,
        "as_of": as_of.isoformat(),
        "latest_hsi_date": latest["date"],
        "latest_us10y_date": latest["us10y_date"],
        "hsi_age_days": hsi_age_days,
        "rate_lag_days": latest["rate_lag_days"],
        "errors": errors,
    }


def fetch_hsi_record(report: dict[str, Any]) -> dict[str, Any]:
    with build_session() as session:
        payload = fetch_bytes(session, report["url"], max_bytes=200_000)
    record = parse_hsi_idx_csv(payload, report["url"])
    if record["date"] != report["date"]:
        raise RuntimeError(
            f"HSI report date mismatch: catalog={report['date']} file={record['date']}"
        )
    return record


def collect_hsi_records(reports: list[dict[str, Any]], workers: int) -> list[dict[str, Any]]:
    records = []
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_hsi_record, report): report for report in reports}
        for future in as_completed(futures):
            report = futures[future]
            try:
                records.append(future.result())
            except Exception as exc:
                failures.append(f"{report['date']}: {exc}")
    if not records:
        raise RuntimeError("All official HSI idx downloads failed: " + "; ".join(failures[:3]))
    if failures:
        print(f"Warning: {len(failures)} HSI report downloads failed; continuing with valid reports.")
    return sorted(records, key=lambda row: row["date"])


def collect_treasury_records(start_year: int, end_year: int) -> list[dict[str, Any]]:
    records: dict[date, dict[str, Any]] = {}
    with build_session() as session:
        for year in range(start_year, end_year + 1):
            url = TREASURY_URL_TEMPLATE.format(year=year)
            payload = fetch_bytes(session, url, max_bytes=2_000_000)
            for row in parse_treasury_xml(payload):
                records[row["date"]] = row
    return [records[item] for item in sorted(records)]


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "hsi_daily_erp_experiment.json"
    csv_path = output_dir / "hsi_daily_erp_experiment.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = [
        "date",
        "hsi_close",
        "hsi_pe",
        "earnings_yield_pct",
        "us10y_pct",
        "us10y_date",
        "rate_lag_days",
        "hsi_erp_pct",
        "hsi_source_url",
        "hsi_pe_source_type",
        "hsi_pe_anchor_date",
        "hsi_pe_anchor_value",
        "hsi_close_source",
        "treasury_source_url",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(payload["records"])
    return json_path, csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the isolated official daily HSI ERP experiment.")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-reports", type=int, default=0)
    parser.add_argument("--lookback-months", type=int, default=6)
    parser.add_argument("--max-hsi-age-days", type=int, default=4)
    parser.add_argument("--max-rate-lag-days", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    as_of = date.fromisoformat(args.as_of)
    if args.workers < 1 or args.workers > 8:
        raise ValueError("--workers must be between 1 and 8")
    if args.lookback_months < 1 or args.lookback_months > 12:
        raise ValueError("--lookback-months must be between 1 and 12")

    experiment_start = subtract_months(as_of, args.lookback_months)
    close_fetch_start = experiment_start.replace(day=1)
    close_fetch_start = subtract_months(close_fetch_start, 1)

    with build_session() as session:
        catalog = fetch_bytes(session, HSI_CATALOG_URL, max_bytes=5_000_000)
    reports = [report for report in parse_hsi_catalog(catalog) if report["date"] <= as_of]
    if args.max_reports > 0:
        reports = reports[-args.max_reports :]
    if not reports:
        raise RuntimeError(f"No official HSI reports are available on or before {as_of}.")

    official_daily_records = collect_hsi_records(reports, args.workers)
    with build_session() as session:
        monthly_pe_payload = fetch_bytes(session, HSI_MONTHLY_PE_URL, max_bytes=500_000)
    monthly_pe_records = parse_official_monthly_pe(monthly_pe_payload)
    close_records = fetch_tushare_hsi_closes(close_fetch_start, as_of)
    hsi_records = build_hybrid_hsi_records(
        close_records,
        monthly_pe_records,
        official_daily_records,
    )
    hsi_records = [row for row in hsi_records if experiment_start <= row["date"] <= as_of]
    if not hsi_records:
        raise RuntimeError("The requested experiment window contains no HSI records.")
    treasury_records = collect_treasury_records(hsi_records[0]["date"].year, as_of.year)
    records = build_daily_erp_records(hsi_records, treasury_records)
    freshness = assess_freshness(
        records,
        as_of,
        max_hsi_age_days=args.max_hsi_age_days,
        max_rate_lag_days=args.max_rate_lag_days,
    )
    payload = {
        "schema_version": "hsi-erp-daily-experiment.v1",
        "experiment_only": True,
        "production_consumable": False,
        "methodology": (
            "official daily HSI PE where published; otherwise causal PE derived from the latest "
            "prior official monthly PE anchor and Tushare HSI close; minus latest prior official US 10Y"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "sources": {
            "hsi_catalog": HSI_CATALOG_URL,
            "hsi_monthly_pe": HSI_MONTHLY_PE_URL,
            "hsi_daily_pe": "Hang Seng Indexes official HSI idx daily CSV where retained",
            "hsi_close_history": "Tushare index_global HSI",
            "us10y": TREASURY_URL_TEMPLATE.format(year=as_of.year),
            "allowlisted_hosts": sorted(ALLOWED_SOURCE_HOSTS),
        },
        "freshness": freshness,
        "window": {
            "start_date": experiment_start.isoformat(),
            "end_date": as_of.isoformat(),
            "lookback_months": args.lookback_months,
        },
        "source_type_counts": {
            source_type: sum(1 for row in records if row["hsi_pe_source_type"] == source_type)
            for source_type in sorted({row["hsi_pe_source_type"] for row in records})
        },
        "record_count": len(records),
        "latest_signal": records[-1],
        "records": records,
    }
    json_path, csv_path = write_outputs(Path(args.output_dir).resolve(), payload)

    latest = records[-1]
    print("=" * 64)
    print("HSI Daily ERP Experiment (not connected to production)")
    print("=" * 64)
    print(f"Date: {latest['date']}")
    print(f"HSI close: {latest['hsi_close']:.2f}")
    print(f"Official daily HSI PE: {latest['hsi_pe']:.2f}")
    print(f"US 10Y: {latest['us10y_pct']:.2f}% ({latest['us10y_date']})")
    print(f"Daily HSI ERP: {latest['hsi_erp_pct']:.2f}%")
    print(f"PE source: {latest['hsi_pe_source_type']}")
    print(f"Experiment window: {records[0]['date']} -> {records[-1]['date']} ({len(records)} rows)")
    print(f"Freshness: {'OK' if freshness['ok'] else 'BLOCKED'}")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    return 0 if freshness["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
