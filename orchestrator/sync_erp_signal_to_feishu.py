#!/usr/bin/env python
"""Optionally archive ERP shared signal records to a Feishu Base table.

This script is intentionally non-blocking by default. Set
ERP_ARCHIVE_REQUIRE_SUCCESS=true only for one-off smoke tests.
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://open.feishu.cn/open-apis"
DEFAULT_SIGNAL_PATH = Path("shared") / "erp_signal.json"
DEFAULT_LEGACY_APP_TOKEN = "KfaSbpRdiaYFdWsCTRfcWpocnbd"
DEFAULT_LEGACY_TABLE_ID = "tblRAs2p4woXE1ig"
SH_TZ = timezone(timedelta(hours=8))


FIELD_DATE = "日期"
FIELD_CSI300 = "沪深300点位"
FIELD_PE = "PE_TTM"
FIELD_BOND = "10年国债收益率"
FIELD_EARNINGS = "盈利收益率"
FIELD_PREMIUM = "股权溢价指数"
FIELD_SOURCE = "数据源"


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def finite_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def to_feishu_date(value: Any) -> int | Any:
    try:
        text = str(value)[:10]
        parsed = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=SH_TZ)
        return int(parsed.timestamp() * 1000)
    except Exception:
        return value


def to_date_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        ts = int(value)
        if abs(ts) < 10_000_000_000:
            ts *= 1000
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(SH_TZ).strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt != "%Y%m%d" else text[:8], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def get_tenant_token(app_id: str, app_secret: str) -> str:
    response = requests.post(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"Feishu auth failed: {payload}")
    return str(payload["tenant_access_token"])


def load_signal(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError(f"{path} missing records list")
    return payload


def build_existing_index(records_url: str, headers: dict[str, str]) -> dict[str, str]:
    existing: dict[str, str] = {}
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        response = requests.get(records_url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Feishu record list failed: {payload}")
        data = payload.get("data") or {}
        for item in data.get("items", []):
            record_id = item.get("record_id")
            fields = item.get("fields") or {}
            date_key = to_date_key(fields.get(FIELD_DATE))
            if record_id and date_key:
                existing[date_key] = record_id
        if not data.get("has_more"):
            return existing
        page_token = data.get("page_token")
        if not page_token:
            return existing


def record_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {
        FIELD_DATE: to_feishu_date(record.get("date")),
        FIELD_SOURCE: "tushare+akshare",
    }
    mapping = (
        (FIELD_CSI300, "csi300_close"),
        (FIELD_PE, "pe_ttm"),
        (FIELD_BOND, "bond_yield"),
        (FIELD_EARNINGS, "earnings_yield"),
        (FIELD_PREMIUM, "equity_premium"),
    )
    for field_name, key in mapping:
        value = finite_number(record.get(key))
        if value is not None:
            fields[field_name] = value
    return fields


def select_records(records: list[dict[str, Any]], existing: dict[str, str]) -> list[dict[str, Any]]:
    lookback_days = int(os.environ.get("ERP_ARCHIVE_LOOKBACK_DAYS", "120"))
    if not existing or lookback_days <= 0:
        return records
    cutoff = datetime.now(SH_TZ).date() - timedelta(days=lookback_days)
    selected = []
    for record in records:
        date_key = to_date_key(record.get("date"))
        if not date_key:
            selected.append(record)
            continue
        parsed = datetime.strptime(date_key, "%Y-%m-%d").date()
        if date_key not in existing or parsed >= cutoff:
            selected.append(record)
    return selected


def sync() -> dict[str, Any]:
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    app_token = (
        os.environ.get("ERP_LEGACY_FEISHU_APP_TOKEN")
        or os.environ.get("ERP_ARCHIVE_FEISHU_APP_TOKEN")
        or DEFAULT_LEGACY_APP_TOKEN
    ).strip()
    table_id = (
        os.environ.get("ERP_LEGACY_FEISHU_TABLE_ID")
        or os.environ.get("ERP_ARCHIVE_FEISHU_TABLE_ID")
        or DEFAULT_LEGACY_TABLE_ID
    ).strip()
    signal_path = Path(os.environ.get("ERP_ARCHIVE_SIGNAL_PATH", str(DEFAULT_SIGNAL_PATH)))

    if not app_id or not app_secret:
        return {"success": False, "skipped": True, "message": "missing FEISHU_APP_ID/FEISHU_APP_SECRET"}
    if not app_token or not table_id:
        return {"success": False, "skipped": True, "message": "missing legacy Feishu app token/table id"}
    if not signal_path.exists():
        return {"success": False, "skipped": True, "message": f"missing signal file: {signal_path}"}

    payload = load_signal(signal_path)
    records = payload.get("records", [])
    token = get_tenant_token(app_id, app_secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    records_url = f"{BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    existing = build_existing_index(records_url, headers)
    selected = select_records(records, existing)

    created = 0
    updated = 0
    failed = 0
    errors: list[str] = []
    for record in selected:
        date_key = to_date_key(record.get("date")) or str(record.get("date", ""))
        fields = record_fields(record)
        record_id = existing.get(date_key)
        try:
            if record_id:
                response = requests.put(
                    f"{records_url}/{record_id}",
                    json={"fields": fields},
                    headers=headers,
                    timeout=15,
                )
                action = "UPDATE"
            else:
                response = requests.post(
                    records_url,
                    json={"fields": fields},
                    headers=headers,
                    timeout=15,
                )
                action = "CREATE"
            ok = response.status_code == 200 and response.json().get("code") == 0
            if ok and action == "UPDATE":
                updated += 1
            elif ok:
                created += 1
            else:
                failed += 1
                if len(errors) < 5:
                    errors.append(f"{action} {date_key}: {response.status_code} {response.text[:180]}")
        except Exception as exc:
            failed += 1
            if len(errors) < 5:
                errors.append(f"{date_key}: {exc}")

    return {
        "success": failed == 0,
        "skipped": False,
        "app_token": app_token,
        "table_id": table_id,
        "source_latest_date": payload.get("latest_date"),
        "existing_dates": len(existing),
        "selected": len(selected),
        "created": created,
        "updated": updated,
        "failed": failed,
        "errors": errors,
    }


def main() -> None:
    require_success = truthy(os.environ.get("ERP_ARCHIVE_REQUIRE_SUCCESS"))
    try:
        result = sync()
    except Exception as exc:
        result = {"success": False, "skipped": False, "message": str(exc)}
    print("ERP legacy Feishu archive result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        print(f"::warning::ERP legacy Feishu archive did not fully succeed: {result.get('message') or result.get('errors')}")
    if require_success and not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
