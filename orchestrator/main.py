#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CSI300 Relative Index 仓库内的主编排入口。

适用于 GitHub Actions 方案 A：
以当前仓库为主调度仓库，额外 checkout Equity Risk Premium 仓库后统一调度。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


CSI_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_ROOT = CSI_ROOT.parent
ERP_ROOT = Path(os.environ.get("ERP_REPO_PATH", str(SYSTEM_ROOT / "Equity Risk Premium"))).resolve()
SHARED_DIR = Path(os.environ.get("SHARED_DIR", str(SYSTEM_ROOT / "shared"))).resolve()

ERP_MAIN = ERP_ROOT / "skills" / "equity-risk-premium" / "main.py"
RELATIVE_MAIN = CSI_ROOT / ".claude" / "skills" / "index-compare" / "scripts" / "main.py"
ERP_SIGNAL = SHARED_DIR / "erp_signal.json"
RELATIVE_SIGNAL = SHARED_DIR / "relative_signal.json"
MERGED_SIGNAL = SHARED_DIR / "merged_signal.json"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_command(command: list[str], cwd: Path, env: dict[str, str], step_name: str) -> dict[str, Any]:
    print(f"\n{'=' * 60}")
    print(step_name)
    print(f"{'=' * 60}")
    print("命令:", " ".join(command))

    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )

    if completed.stdout:
        print(completed.stdout)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr)

    if completed.returncode != 0:
        raise RuntimeError(f"{step_name} 执行失败，退出码 {completed.returncode}")

    payload = extract_json_from_stdout(completed.stdout)
    return payload if payload is not None else {"success": True}


def extract_json_from_stdout(stdout: str) -> dict[str, Any] | None:
    text = (stdout or "").strip()
    if not text:
        return None

    lines = text.splitlines()
    for start in range(len(lines) - 1, -1, -1):
        candidate = "\n".join(lines[start:]).strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"无效 JSON: {path}")
    return payload


def validate_signal(payload: dict[str, Any], expected_type: str, path: Path) -> None:
    if payload.get("version") != "1.0":
        raise ValueError(f"{path} version 非 1.0")
    if payload.get("signal_type") != expected_type:
        raise ValueError(f"{path} signal_type 非 {expected_type}")
    if "latest_date" not in payload:
        raise ValueError(f"{path} 缺少 latest_date")
    if not isinstance(payload.get("records"), list):
        raise ValueError(f"{path} records 不是列表")


def build_latest_snapshot(erp_payload: dict[str, Any], relative_payload: dict[str, Any], latest_date: str | None) -> dict[str, Any]:
    """构造统一最新快照，供下游直接消费。"""
    erp_latest = erp_payload.get("latest_signal", {})
    relative_latest = relative_payload.get("latest_signal", {})

    return {
        "date": latest_date,
        "erp": {
            "equity_premium": erp_latest.get("equity_premium"),
            "bond_yield": erp_latest.get("bond_yield"),
            "pe_ttm": erp_latest.get("pe_ttm"),
            "earnings_yield": erp_latest.get("earnings_yield"),
            "csi300_close": erp_latest.get("csi300_close"),
        },
        "relative": {
            "zz500_recommendation": relative_latest.get("zz500_recommendation"),
            "zz1000_recommendation": relative_latest.get("zz1000_recommendation"),
            "zza500_recommendation": relative_latest.get("zza500_recommendation"),
        },
    }


def build_merged_signal(erp_payload: dict[str, Any], relative_payload: dict[str, Any]) -> dict[str, Any]:
    latest_dates = [d for d in [erp_payload.get("latest_date"), relative_payload.get("latest_date")] if d]
    latest_date = min(latest_dates) if latest_dates else None
    erp_records = erp_payload.get("records", [])
    relative_records = relative_payload.get("records", [])

    return {
        "version": "1.0",
        "signal_type": "erp_relative_merged",
        "source": "CSI300 Relative Index Orchestrator",
        "generated_at": now_iso(),
        "latest_date": latest_date,
        "record_count": {
            "erp": len(erp_records),
            "relative": len(relative_records),
        },
        "components": {
            "erp": {
                "latest_date": erp_payload.get("latest_date"),
                "latest_signal": erp_payload.get("latest_signal", {}),
                "record_count": len(erp_records),
                "records": erp_records,
            },
            "relative": {
                "latest_date": relative_payload.get("latest_date"),
                "latest_signal": relative_payload.get("latest_signal", {}),
                "record_count": len(relative_records),
                "records": relative_records,
            },
        },
        "paths": {
            "erp": str(ERP_SIGNAL),
            "relative": str(RELATIVE_SIGNAL),
        },
        "latest_snapshot": build_latest_snapshot(erp_payload, relative_payload, latest_date),
    }


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统一调度 ERP + CSI300 Relative")
    parser.add_argument("--force-relative", action="store_true", help="强制 Relative 全量更新")
    parser.add_argument("--erp-start-date", help="ERP 开始日期")
    parser.add_argument("--erp-end-date", help="ERP 结束日期")
    return parser.parse_args()


def build_erp_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, str(ERP_MAIN)]
    if args.erp_start_date:
        command.append(args.erp_start_date)
    if args.erp_end_date:
        command.append(args.erp_end_date)
    return command


def build_relative_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, str(RELATIVE_MAIN)]
    if args.force_relative:
        command.append("--force")
    return command


def build_step_env(base_env: dict[str, str], target: str) -> dict[str, str]:
    """
    为不同子项目组装独立环境变量，避免共享 workflow 时飞书表写串。
    """
    env = base_env.copy()
    env["SHARED_DIR"] = str(SHARED_DIR)
    env["ERP_REPO_PATH"] = str(ERP_ROOT)

    if target == "erp":
        env["ERP_SHARED_SIGNAL_PATH"] = str(ERP_SIGNAL)
        env["EQUITY_PREMIUM_OUTPUT_PATH"] = str(ERP_ROOT / "equity_premium_enhanced.xlsx")
        env["FEISHU_WEBHOOK_URL"] = env.get("ERP_FEISHU_WEBHOOK_URL") or env.get("FEISHU_WEBHOOK_URL", "")
        env["FEISHU_APP_TOKEN"] = env.get("ERP_FEISHU_APP_TOKEN") or env.get("FEISHU_APP_TOKEN", "")
        env["FEISHU_TABLE_ID"] = env.get("ERP_FEISHU_TABLE_ID") or env.get("FEISHU_TABLE_ID", "")
    elif target == "relative":
        env["INDEX_COMPARE_SHARED_SIGNAL_PATH"] = str(RELATIVE_SIGNAL)
        env["INDEX_COMPARE_ERP_SIGNAL_PATH"] = str(ERP_SIGNAL)
        env["INDEX_COMPARE_OUTPUT_PATH"] = str(CSI_ROOT / "index_compare_enhanced.xlsx")
        env["REQUIRE_BITABLE_SYNC"] = env.get("REQUIRE_BITABLE_SYNC", "true")
        env["FEISHU_WEBHOOK_URL"] = env.get("CSI_FEISHU_WEBHOOK_URL") or env.get("FEISHU_WEBHOOK_URL", "")
        env["FEISHU_APP_TOKEN"] = env.get("CSI_FEISHU_APP_TOKEN") or env.get("FEISHU_APP_TOKEN", "")
        env["FEISHU_TABLE_ID"] = env.get("CSI_FEISHU_TABLE_ID") or env.get("FEISHU_TABLE_ID", "")
    else:
        raise ValueError(f"不支持的 target: {target}")

    return env


def main() -> None:
    args = parse_args()
    env = os.environ.copy()

    if not ERP_MAIN.exists():
        raise FileNotFoundError(f"未找到 ERP 入口: {ERP_MAIN}")
    if not RELATIVE_MAIN.exists():
        raise FileNotFoundError(f"未找到 Relative 入口: {RELATIVE_MAIN}")

    print("=" * 60)
    print("CSI300 Relative Index Master Orchestrator")
    print("=" * 60)
    print(f"执行时间: {now_iso()}")
    print(f"ERP_REPO_PATH: {ERP_ROOT}")
    print(f"SHARED_DIR: {SHARED_DIR}")

    erp_result = run_command(
        build_erp_command(args),
        ERP_ROOT,
        build_step_env(env, "erp"),
        "步骤 1/3 运行 Equity Risk Premium",
    )
    relative_result = run_command(
        build_relative_command(args),
        CSI_ROOT,
        build_step_env(env, "relative"),
        "步骤 2/3 运行 CSI300 Relative Index",
    )

    if not ERP_SIGNAL.exists():
        raise FileNotFoundError(f"未找到共享接口: {ERP_SIGNAL}")
    if not RELATIVE_SIGNAL.exists():
        raise FileNotFoundError(f"未找到共享接口: {RELATIVE_SIGNAL}")

    erp_payload = load_json(ERP_SIGNAL)
    relative_payload = load_json(RELATIVE_SIGNAL)
    validate_signal(erp_payload, "equity_risk_premium", ERP_SIGNAL)
    validate_signal(relative_payload, "csi300_relative_index", RELATIVE_SIGNAL)

    merged_payload = build_merged_signal(erp_payload, relative_payload)
    save_json(MERGED_SIGNAL, merged_payload)

    result = {
        "success": True,
        "generated_at": merged_payload["generated_at"],
        "latest_date": merged_payload["latest_date"],
        "erp": {
            "latest_date": erp_payload.get("latest_date"),
            "shared_signal_path": str(ERP_SIGNAL),
            "run_result": erp_result,
        },
        "relative": {
            "latest_date": relative_payload.get("latest_date"),
            "shared_signal_path": str(RELATIVE_SIGNAL),
            "run_result": relative_result,
        },
        "merged_signal_path": str(MERGED_SIGNAL),
    }

    print(f"\n[OK] merged signal 已生成: {MERGED_SIGNAL}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
