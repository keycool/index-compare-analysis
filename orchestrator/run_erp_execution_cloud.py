#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Wrapper for the cloud ERP execution workflow.

Responsibilities:
- generate the latest ERP execution plan through OpenAPI
- render the human-readable summary
- optionally push the summary to Feishu webhook
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXECUTION_SCRIPT = ROOT / "erp_execution_cloud.py"
PUSH_SCRIPT = ROOT / "push_erp_daily_summary_to_feishu.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run cloud ERP execution workflow")
    parser.add_argument(
        "--push-summary",
        action="store_true",
        default=False,
        help="Push the generated summary to the configured Feishu webhook",
    )
    return parser.parse_args()


def run_python(script: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT.parent,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.stdout:
        print(completed.stdout)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed: {script.name}")


def main() -> None:
    args = parse_args()
    run_python(EXECUTION_SCRIPT)
    if args.push_summary:
        run_python(PUSH_SCRIPT)


if __name__ == "__main__":
    main()
