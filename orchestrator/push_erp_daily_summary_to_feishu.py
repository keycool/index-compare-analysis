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


def build_payload(plan: dict, summary_text: str) -> dict:
    erp = plan["signals"]["erp"]
    relative = plan["signals"]["relative"]
    style = plan["signals"].get("val300_style", {})
    positions = sorted(
        plan["portfolio"]["positions"],
        key=lambda item: abs(float(item.get("delta_amount", 0.0))),
        reverse=True,
    )[:5]

    content: list[list[dict[str, str]]] = []
    content.append([{"tag": "text", "text": "ERP执行日报"}])
    content.append(
        [
            {"tag": "text", "text": f"ERP {erp['date']} | 分位 {erp['percentile']:.2f}% | "},
            {
                "tag": "text",
                "text": f"进攻 {erp['aggressive_weight'] * 100:.2f}% / 防守 {erp['defensive_weight'] * 100:.2f}%",
                "color": "blue",
            },
        ]
    )
    content.append(
        [
            {
                "tag": "text",
                "text": (
                    f"Relative {relative['date']} | 500={relative['recommendations']['zz500'] or '标配'} | "
                    f"1000={relative['recommendations']['zz1000'] or '标配'} | "
                    f"创业板={relative['recommendations']['cyb'] or '标配'} | "
                    f"50={relative['recommendations']['sh50'] or '标配'}"
                ),
            }
        ]
    )
    if style.get("available"):
        content.append(
            [
                {
                    "tag": "text",
                    "text": (
                        f"300价值/成长 {style['date']} | 比价 {style['ratio']:.4f} | "
                        f"分位 {style['percentile']:.2f}% | 建议 {style['recommendation']}"
                    ),
                }
            ]
        )

    content.append([{"tag": "text", "text": "Top 调仓动作"}])
    for item in positions:
        direction = "加仓" if item["delta_amount"] > 0 else "减仓" if item["delta_amount"] < 0 else "保持"
        content.append(
            [
                {
                    "tag": "text",
                    "text": (
                        f"{item['label']} | 当前 {item['current_amount']:,.0f} | "
                        f"目标 {item['target_amount']:,.0f} | {direction} {abs(item['delta_amount']):,.0f}"
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
    erp = plan["signals"]["erp"]
    relative = plan["signals"]["relative"]
    style = plan["signals"].get("val300_style", {})
    positions = sorted(
        plan["portfolio"]["positions"],
        key=lambda item: abs(float(item.get("delta_amount", 0.0))),
        reverse=True,
    )[:5]

    lines = [
        "ERP执行日报",
        f"日期: {relative['date']}",
        f"ERP分位: {erp['percentile']:.2f}%",
        f"进攻/防守: {erp['aggressive_weight'] * 100:.2f}% / {erp['defensive_weight'] * 100:.2f}%",
        (
            f"Relative: 500={relative['recommendations']['zz500'] or '标配'}; "
            f"1000={relative['recommendations']['zz1000'] or '标配'}; "
            f"创业板={relative['recommendations']['cyb'] or '标配'}; "
            f"50={relative['recommendations']['sh50'] or '标配'}"
        ),
    ]
    if style.get("available"):
        lines.append(
            f"300价值/成长: 比价 {style['ratio']:.4f}; 分位 {style['percentile']:.2f}%; 建议 {style['recommendation']}"
        )
    lines.append("Top调仓:")
    for item in positions:
        direction = "加仓" if item["delta_amount"] > 0 else "减仓" if item["delta_amount"] < 0 else "保持"
        lines.append(
            f"{item['label']}: 当前 {item['current_amount']:,.0f}, 目标 {item['target_amount']:,.0f}, {direction} {abs(item['delta_amount']):,.0f}"
        )
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
    payload = build_payload(plan, summary_text)
    payload = attach_signature(payload, resolve_webhook_secret())

    secret = resolve_webhook_secret()
    print(f"[PUSH] {describe_webhook(webhook_url)}")
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
