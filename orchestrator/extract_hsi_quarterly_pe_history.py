from __future__ import annotations

import argparse
import csv
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader


PDF_URL_TEMPLATE = "https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/publication/{stamp}T000000.pdf"


def quarter_end_dates(start_year: int, end_year: int) -> Iterable[tuple[int, int, date]]:
    quarter_ends = (
        (1, (3, 31)),
        (2, (6, 30)),
        (3, (9, 30)),
        (4, (12, 31)),
    )
    for year in range(start_year, end_year + 1):
        for quarter, (month, day) in quarter_ends:
            yield year, quarter, date(year, month, day)


def candidate_publish_dates(year: int, quarter: int, q_end: date) -> list[date]:
    offsets = [0, 7, 14, 21, 28, 30, 31]
    candidates = [q_end + timedelta(days=offset) for offset in offsets]
    if quarter == 4:
        next_year = year + 1
        candidates.extend(
            [
                date(next_year, 1, 15),
                date(next_year, 1, 20),
                date(next_year, 1, 28),
                date(next_year, 1, 31),
                date(next_year, 2, 5),
            ]
        )
    deduped: list[date] = []
    seen = set()
    for item in candidates:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def download_pdf(url: str, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["curl", "-L", "--http1.1", "--silent", "--show-error", "--fail", url, "-o", str(output_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
    except subprocess.TimeoutExpired:
        return False


def parse_quarterly_pdf(pdf_path: Path) -> dict | None:
    try:
        reader = PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages[:4])
    except Exception:
        return None

    if "Hang Seng Indexes Quarterly" not in text:
        return None

    fundamentals_match = re.search(
        r"INDEX FUNDAMENTALS.*?HSI\s+([0-9]+\.[0-9]+)\s+([0-9]+\.[0-9]+)\s+([0-9]+\.[0-9]+)\s+([0-9]+\.[0-9]+)\s+([0-9]+\.[0-9]+)",
        text,
        re.S,
    )
    as_of_match = re.search(r"All data as at\s+([0-9]{1,2}\s+[A-Za-z]{3}\s+[0-9]{4})", text)

    if not fundamentals_match or not as_of_match:
        return None

    return {
        "as_of": as_of_match.group(1),
        "dividend_yield": float(fundamentals_match.group(1)),
        "vol_1y": float(fundamentals_match.group(2)),
        "vol_3y": float(fundamentals_match.group(3)),
        "vol_5y": float(fundamentals_match.group(4)),
        "pe_ratio": float(fundamentals_match.group(5)),
    }


def collect_history(start_year: int, end_year: int, cache_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for year, quarter, q_end in quarter_end_dates(start_year, end_year):
        found = None
        for publish_date in candidate_publish_dates(year, quarter, q_end):
            stamp = publish_date.strftime("%Y%m%d")
            url = PDF_URL_TEMPLATE.format(stamp=stamp)
            pdf_path = cache_dir / f"{stamp}.pdf"
            if not download_pdf(url, pdf_path):
                continue
            parsed = parse_quarterly_pdf(pdf_path)
            if not parsed:
                continue
            found = {
                "quarter": f"{year}Q{quarter}",
                "quarter_end": q_end.isoformat(),
                "publish_date": publish_date.isoformat(),
                "url": url,
                **parsed,
            }
            rows.append(found)
            print(f"[OK] {year}Q{quarter}: {parsed['as_of']} | PE {parsed['pe_ratio']:.2f} | {stamp}")
            break
        if not found:
            print(f"[MISS] {year}Q{quarter}")
    return rows


def save_csv(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "quarter",
        "quarter_end",
        "publish_date",
        "as_of",
        "pe_ratio",
        "dividend_yield",
        "vol_1y",
        "vol_3y",
        "vol_5y",
        "url",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract quarterly HSI PE history from official PDFs.")
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument(
        "--output",
        default=str(Path("orchestrator") / "output" / "hsi_quarterly_pe_history.csv"),
    )
    args = parser.parse_args()

    cache_dir = Path("orchestrator") / "output" / "_hsi_quarterly_pdf_cache"
    rows = collect_history(args.start_year, args.end_year, cache_dir)
    save_csv(rows, Path(args.output))
    print(f"\nSaved {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
