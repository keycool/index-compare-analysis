#!/usr/bin/env python
"""Sync published ERP and Relative signals into the local shared directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHARED_DIR = REPO_ROOT.parent / "shared"
DEFAULT_SOURCE_URL = "https://keycool.github.io/index-compare-analysis/data/merged_signal.json"
DEFAULT_HSI_ERP_SOURCE_URL = "https://keycool.github.io/index-compare-analysis/data/hsi_erp_signal.json"

COMPONENT_METADATA = {
    "erp": {
        "filename": "erp_signal.json",
        "version": "1.0",
        "signal_type": "equity_risk_premium",
        "source": "Equity Risk Premium",
    },
    "relative": {
        "filename": "relative_signal.json",
        "version": "1.1",
        "signal_type": "csi300_relative_index",
        "source": "CSI300 Relative Index",
    },
}


def parse_signal_date(value: Any, label: str) -> date:
    raw = str(value or "").strip()
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{label} {raw!r} is not a valid ISO date") from exc
    if parsed > date.today():
        raise ValueError(f"{label} {parsed.isoformat()} is after today {date.today().isoformat()}")
    return parsed


def max_record_date(records: list[dict[str, Any]], label: str) -> date:
    dates: list[date] = []
    for record in records:
        for key in ("date", "日期", "trade_date"):
            if record.get(key):
                dates.append(parse_signal_date(record[key], f"{label} record {key}"))
                break
    if not dates:
        raise ValueError(f"{label} records do not contain a date")
    return max(dates)


def validate_component(name: str, component: Any) -> dict[str, Any]:
    if not isinstance(component, dict):
        raise ValueError(f"Merged signal component {name!r} is missing")
    records = component.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError(f"Merged signal component {name!r} has no records")

    latest = parse_signal_date(component.get("latest_date"), f"{name} latest_date")
    record_max = max_record_date(records, name)
    if latest != record_max:
        raise ValueError(
            f"{name} latest_date {latest.isoformat()} does not match "
            f"record max date {record_max.isoformat()}"
        )

    declared_count = component.get("record_count")
    if declared_count is not None and int(declared_count) != len(records):
        raise ValueError(
            f"{name} record_count {declared_count} does not match records length {len(records)}"
        )

    latest_signal = component.get("latest_signal")
    if not isinstance(latest_signal, dict):
        raise ValueError(f"Merged signal component {name!r} has no latest_signal")
    if latest_signal.get("date"):
        latest_signal_date = parse_signal_date(latest_signal["date"], f"{name} latest_signal date")
        if latest_signal_date != latest:
            raise ValueError(
                f"{name} latest_signal date {latest_signal_date.isoformat()} "
                f"does not match latest_date {latest.isoformat()}"
            )

    return {
        "latest_date": latest.isoformat(),
        "record_count": len(records),
        "records": records,
        "latest_signal": latest_signal,
    }


def validate_merged_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Published merged signal must be a JSON object")
    components = payload.get("components")
    if not isinstance(components, dict):
        raise ValueError("Published merged signal has no components object")

    validated = {
        name: validate_component(name, components.get(name))
        for name in COMPONENT_METADATA
    }
    expected_merged_latest = min(item["latest_date"] for item in validated.values())
    merged_latest = parse_signal_date(payload.get("latest_date"), "merged latest_date").isoformat()
    if merged_latest != expected_merged_latest:
        raise ValueError(
            f"merged latest_date {merged_latest} does not match component minimum {expected_merged_latest}"
        )
    return validated


def validate_hsi_erp_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Published HSI ERP signal must be a JSON object")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("Published HSI ERP signal has no records")
    latest = parse_signal_date(payload.get("latest_date"), "HSI ERP latest_date")
    record_max = max_record_date(records, "HSI ERP")
    if latest != record_max:
        raise ValueError(
            f"HSI ERP latest_date {latest.isoformat()} does not match record max date {record_max.isoformat()}"
        )
    declared_count = payload.get("record_count")
    if declared_count is not None and int(declared_count) != len(records):
        raise ValueError(
            f"HSI ERP record_count {declared_count} does not match records length {len(records)}"
        )
    latest_signal = payload.get("latest_signal")
    if not isinstance(latest_signal, dict):
        raise ValueError("Published HSI ERP signal has no latest_signal")
    if parse_signal_date(latest_signal.get("date"), "HSI ERP latest_signal date") != latest:
        raise ValueError("HSI ERP latest_signal date does not match latest_date")
    return payload


def build_component_payload(
    name: str,
    component: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    metadata = COMPONENT_METADATA[name]
    return {
        "version": metadata["version"],
        "signal_type": metadata["signal_type"],
        "source": metadata["source"],
        "generated_at": generated_at,
        "latest_date": component["latest_date"],
        "record_count": component["record_count"],
        "records": component["records"],
        "latest_signal": component["latest_signal"],
    }


def read_existing_latest(path: Path) -> date | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return parse_signal_date(payload.get("latest_date"), f"existing {path.name} latest_date")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def sync_payload(
    payload: dict[str, Any],
    shared_dir: Path,
    *,
    hsi_erp_payload: dict[str, Any] | None = None,
    allow_downgrade: bool = False,
    dry_run: bool = False,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    validated = validate_merged_payload(payload)
    shared_dir = shared_dir.resolve()
    targets = {
        name: shared_dir / metadata["filename"]
        for name, metadata in COMPONENT_METADATA.items()
    }
    validated_hsi_erp = validate_hsi_erp_payload(hsi_erp_payload) if hsi_erp_payload is not None else None
    if validated_hsi_erp is not None:
        targets["hsi_erp"] = shared_dir / "hsi_erp_signal.json"

    for name, target in targets.items():
        existing_latest = read_existing_latest(target)
        incoming_latest = parse_signal_date(
            (validated_hsi_erp if name == "hsi_erp" else validated[name])["latest_date"],
            f"incoming {name} latest_date",
        )
        if existing_latest and incoming_latest < existing_latest and not allow_downgrade:
            raise ValueError(
                f"Refusing to downgrade {target.name}: "
                f"{existing_latest.isoformat()} -> {incoming_latest.isoformat()}"
            )

    generated_at = str(payload.get("generated_at") or "").strip()
    if not generated_at:
        raise ValueError("Published merged signal has no generated_at")

    result = {
        "source_latest_date": payload["latest_date"],
        "generated_at": generated_at,
        "shared_dir": str(shared_dir),
        "dry_run": dry_run,
        "components": {
            name: {
                "latest_date": component["latest_date"],
                "record_count": component["record_count"],
                "path": str(targets[name]),
            }
            for name, component in validated.items()
        },
        "merged_path": str(shared_dir / "merged_signal.json"),
        "backup_dir": None,
    }
    if validated_hsi_erp is not None:
        result["hsi_erp"] = {
            "latest_date": validated_hsi_erp["latest_date"],
            "record_count": len(validated_hsi_erp["records"]),
            "path": str(targets["hsi_erp"]),
        }
    if dry_run:
        return result

    shared_dir.mkdir(parents=True, exist_ok=True)
    now = captured_at or datetime.now().astimezone()
    stamp = now.strftime("%Y%m%dT%H%M%S%z")
    backup_dir = shared_dir / "backups" / "production-signals" / stamp
    existing_targets = [*targets.values(), shared_dir / "merged_signal.json"]
    files_to_backup = [path for path in existing_targets if path.exists()]
    if files_to_backup:
        backup_dir.mkdir(parents=True, exist_ok=False)
        for path in files_to_backup:
            shutil.copy2(path, backup_dir / path.name)
        result["backup_dir"] = str(backup_dir)

    for name, target in targets.items():
        component_payload = (
            validated_hsi_erp
            if name == "hsi_erp"
            else build_component_payload(name, validated[name], generated_at)
        )
        write_json_atomic(target, component_payload)
    write_json_atomic(shared_dir / "merged_signal.json", payload)
    return result


def download_payload(source_url: str, timeout_seconds: int) -> dict[str, Any]:
    request = urllib.request.Request(source_url, headers={"User-Agent": "erp-local-signal-sync"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync published ERP/Relative signals to local shared files")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--hsi-erp-source-url", default=DEFAULT_HSI_ERP_SOURCE_URL)
    parser.add_argument("--shared-dir", type=Path, default=DEFAULT_SHARED_DIR)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--allow-downgrade", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = download_payload(args.source_url, args.timeout_seconds)
    hsi_erp_payload = download_payload(args.hsi_erp_source_url, args.timeout_seconds)
    result = sync_payload(
        payload,
        args.shared_dir,
        hsi_erp_payload=hsi_erp_payload,
        allow_downgrade=args.allow_downgrade,
        dry_run=args.dry_run,
    )
    result["source_url"] = args.source_url
    result["hsi_erp_source_url"] = args.hsi_erp_source_url
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
