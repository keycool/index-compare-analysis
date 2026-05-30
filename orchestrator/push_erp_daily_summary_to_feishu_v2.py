#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Push the latest ERP daily summary to Feishu webhook.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent
PLAN_PATH = ROOT / "output" / "erp_execution_plan.json"
SUMMARY_PATH = ROOT / "output" / "erp_daily_summary.md"
BUCKET_ORDER = {
    "hs300": 0,
    "sh50": 1,
    "cyb": 2,
    "zz500": 3,
    "zz1000": 4,
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_webhook_url() -> str:
    return (os.environ.get("ERP_DAILY_FEISHU_WEBHOOK_URL") or "").strip()


def resolve_webhook_secret() -> str:
    return (os.environ.get("ERP_DAILY_FEISHU_WEBHOOK_SECRET") or "").strip()


def describe_webhook(url: str) -> str:
    if not url:
        return "webhook_source=ERP_DAILY_FEISHU_WEBHOOK_URL webhook_tail=<missing>"
    tail = url.rstrip("/").split("/")[-1]
    return f"webhook_source=ERP_DAILY_FEISHU_WEBHOOK_URL webhook_tail={tail[-8:]}"


def ordered_positions(plan: dict) -> list[dict]:
    return sorted(
        plan["portfolio"]["positions"],
        key=lambda item: BUCKET_ORDER.get(item.get("bucket", ""), 99),
    )


def reentry_text(item: dict) -> str:
    if not item.get("reentry_blocked"):
        return ""
    percentile = item.get("current_percentile")
    threshold = item.get("reentry_threshold")
    if percentile is None or threshold is None:
        return " | 暂不回补"
    return f" | 暂不回补（分位 {percentile:.1f}% > 阈值 {threshold:.1f}%）"


def build_payload(plan: dict, summary_text: str) -> dict:
    relative = plan["signals"]["relative"]
    positions = ordered_positions(plan)

    content: list[list[dict[str, str]]] = []
    content.append([{"tag": "text", "text": "ERP执行日报"}])
    content.append([{"tag": "text", "text": f"调仓建议（{relative['date']}）"}])
    for item in positions:
        if item["delta_amount"] > 0:
            direction = "加仓"
        elif item["delta_amount"] < 0:
            direction = "减仓"
        else:
            direction = "保持"
        content.append(
            [
                {
                    "tag": "text",
                    "text": (
                        f"{item['label']} | 当前 {item['current_amount']:,.0f} | "
                        f"目标 {item['target_amount']:,.0f} | {direction} {abs(item['delta_amount']):,.0f}"
                        f"{reentry_text(item)}"
                    ),
                }
            ]
        )

    if summary_text.strip():
        content.append([{"tag": "text", "text": "完整 Markdown 日报已生成。"}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"ERP执行日报 ({relative['date']})",
                    "content": content,
                }
            }
        },
    }


def build_fallback_text_payload(plan: dict) -> dict:
    relative = plan["signals"]["relative"]
    positions = ordered_positions(plan)

    lines = [
        "ERP执行日报",
        f"日期: {relative['date']}",
        "调仓建议:",
    ]
    for item in positions:
        if item["delta_amount"] > 0:
            direction = "加仓"
        elif item["delta_amount"] < 0:
            direction = "减仓"
        else:
            direction = "保持"
        line = (
            f"{item['label']}: 当前 {item['current_amount']:,.0f}, "
            f"目标 {item['target_amount']:,.0f}, {direction} {abs(item['delta_amount']):,.0f}"
        )
        if item.get("reentry_blocked"):
            percentile = item.get("current_percentile")
            threshold = item.get("reentry_threshold")
            if percentile is not None and threshold is not None:
                line += f", 暂不回补（分位 {percentile:.1f}% > 阈值 {threshold:.1f}%）"
        lines.append(line)
    return {
        "msg_type": "text",
        "content": {"text": "\n".join(lines)},
    }


def attach_signature(payload: dict, secret: str) -> dict:
    if not secret:
        return payload

    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    sign = base64.b64encode(
        hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    signed = dict(payload)
    signed["timestamp"] = timestamp
    signed["sign"] = sign
    return signed


def main() -> None:
    webhook_url = resolve_webhook_url()
    if not webhook_url:
        raise RuntimeError(
            "Missing Feishu webhook URL. Set ERP_DAILY_FEISHU_WEBHOOK_URL."
        )

    if not PLAN_PATH.exists():
        raise FileNotFoundError(f"Missing execution plan: {PLAN_PATH}")
    if not SUMMARY_PATH.exists():
        raise FileNotFoundError(f"Missing daily summary: {SUMMARY_PATH}")

    plan = load_json(PLAN_PATH)
    summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
    secret = resolve_webhook_secret()

    print(f"[PUSH] {describe_webhook(webhook_url)}")
    payload = build_payload(plan, summary_text)
    response = requests.post(
        webhook_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(attach_signature(payload, secret), ensure_ascii=False),
        timeout=15,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code") == 19024:
        print("[PUSH] keyword check blocked post payload, retrying with plain text fallback")
        fallback = build_fallback_text_payload(plan)
        retry = requests.post(
            webhook_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(attach_signature(fallback, secret), ensure_ascii=False),
            timeout=15,
        )
        retry.raise_for_status()
        result = retry.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu push failed: {result}")

    print(
        json.dumps(
            {"success": True, "message": "pushed", "date": plan["signals"]["relative"]["date"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
