"""
Feishu webhook push helpers for index compare analysis.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)
RETRYABLE_ERROR_CODES = {11232}

TITLE_INDEX_COMPARE = "\u6307\u6570\u6bd4\u4ef7\u5206\u6790"
TITLE_RELATIVE_SIGNALS = "\u6bd4\u4ef7\u4fe1\u53f7"
DEFAULT_REC = "\u6807\u914d"

KEY_DATE = "\u65e5\u671f"
KEY_RATIO_500 = "500/300\u6bd4\u4ef7"
KEY_RATIO_1000 = "1000/300\u6bd4\u4ef7"
KEY_RATIO_CYB = "\u521b\u4e1a\u677f/300\u6bd4\u4ef7"
KEY_RATIO_SH50 = "50/\u521b\u4e1a\u677f\u6bd4\u4ef7"
KEY_RATIO_KC50 = "\u79d1\u521b50/\u4e0a\u8bc150\u6bd4\u4ef7"
KEY_RATIO_GROVAL = "300\u6210\u957f/\u4ef7\u503c\u6bd4\u4ef7"
KEY_RATIO_HKTECH = "\u6052\u751f\u79d1\u6280/\u6052\u751f\u6bd4\u4ef7"

RATIO_SIGNAL_ROWS = [
    ("\u4e2d\u8bc1500 / \u6caa\u6df1300", "ZZ500", (KEY_RATIO_500, "ZZ500_ratio"), ("500\u5206\u4f4d",), ("500\u5efa\u8bae",)),
    ("\u4e2d\u8bc11000 / \u6caa\u6df1300", "ZZ1000", (KEY_RATIO_1000, "ZZ1000_ratio"), ("1000\u5206\u4f4d",), ("1000\u5efa\u8bae",)),
    ("\u521b\u4e1a\u677f / \u6caa\u6df1300", "ZZA500", (KEY_RATIO_CYB, "ZZA500_ratio"), ("\u521b\u4e1a\u677f\u5206\u4f4d",), ("\u521b\u4e1a\u677f\u5efa\u8bae",)),
    ("\u4e0a\u8bc150 / \u6caa\u6df1300", "SH50_300", ("\u4e0a\u8bc150/300\u6bd4\u4ef7", "50/300\u6bd4\u4ef7", "SH50_300_ratio"), ("\u4e0a\u8bc150/300\u5206\u4f4d", "50/300\u5206\u4f4d"), ("\u4e0a\u8bc150/300\u5efa\u8bae", "50/300\u5efa\u8bae")),
    ("\u79d1\u521b50 / \u6caa\u6df1300", "KC50_300", ("\u79d1\u521b50/300\u6bd4\u4ef7", "\u79d1\u521b50/\u6caa\u6df1300\u6bd4\u4ef7", "KC50_300_ratio"), ("\u79d1\u521b50/300\u5206\u4f4d", "\u79d1\u521b50/\u6caa\u6df1300\u5206\u4f4d"), ("\u79d1\u521b50/300\u5efa\u8bae", "\u79d1\u521b50/\u6caa\u6df1300\u5efa\u8bae")),
    ("\u521b\u4e1a\u677f / \u4e0a\u8bc150", "SH50", ("\u521b\u4e1a\u677f/\u4e0a\u8bc150\u6bd4\u4ef7", KEY_RATIO_SH50, "SH50_ratio"), ("50\u5206\u4f4d",), ("\u521b\u4e1a\u677f/\u4e0a\u8bc150\u5efa\u8bae",)),
    ("\u79d1\u521b50 / \u4e0a\u8bc150", "KC50", (KEY_RATIO_KC50, "KC50_ratio"), ("\u79d1\u521b50\u5206\u4f4d",), ("\u79d1\u521b50\u5efa\u8bae",)),
    ("300\u6210\u957f / 300\u4ef7\u503c", "VAL300", (KEY_RATIO_GROVAL, "VAL300_ratio"), ("300\u6210\u957f\u5206\u4f4d",), ("300\u6210\u957f\u5efa\u8bae",)),
    ("\u6052\u751f\u79d1\u6280 / \u6052\u751f\u6307\u6570", "HKTECH", (KEY_RATIO_HKTECH, "HKTECH_ratio"), ("\u6052\u751f\u79d1\u6280\u5206\u4f4d",), ("\u6052\u751f\u79d1\u6280\u5efa\u8bae",)),
]

LABEL_CYB = "\u521b\u4e1a\u677f\u6307\u6570"
LABEL_SH50 = "\u4e0a\u8bc150\u6307\u6570"
LABEL_KC50 = "\u79d1\u521b50\u6307\u6570"
LABEL_GRO300 = "300\u6210\u957f\u6307\u6570"
LABEL_HKTECH = "\u6052\u751f\u79d1\u6280\u6307\u6570"
LABEL_ZZ500 = "\u4e2d\u8bc1500"
LABEL_ZZ1000 = "\u4e2d\u8bc11000"

_REVERSE_REC = {
    "\u5f3a\u70c8\u8d85\u914d": "\u5f3a\u70c8\u4f4e\u914d",
    "\u8d85\u914d": "\u4f4e\u914d",
    "\u6807\u914d": "\u6807\u914d",
    "\u4f4e\u914d": "\u8d85\u914d",
    "\u5f3a\u70c8\u4f4e\u914d": "\u5f3a\u70c8\u8d85\u914d",
}


class FeishuWebhook:
    """Feishu bot webhook sender for index compare analysis."""

    def __init__(
        self,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
        webhook_keyword: str | None = None,
    ) -> None:
        self.webhook_url = (webhook_url or os.environ.get("FEISHU_WEBHOOK_URL") or "").strip()
        self.webhook_secret = (webhook_secret or os.environ.get("FEISHU_WEBHOOK_SECRET") or "").strip()
        self.webhook_keyword = (webhook_keyword or os.environ.get("FEISHU_WEBHOOK_KEYWORD") or "").strip()
        self.last_result: dict[str, Any] = {}

    def send(
        self,
        latest_data: dict[str, Any],
        conclusions: dict[str, Any],
        title: str = TITLE_INDEX_COMPARE,
    ) -> bool:
        if not self.webhook_url:
            self.last_result = {"code": "missing_webhook_url", "msg": "Feishu webhook URL is missing"}
            logger.warning("Feishu webhook URL is missing; skip push")
            return False

        payload = self._build_post_payload(latest_data, conclusions, title)
        if not payload:
            self.last_result = {"code": "empty_payload", "msg": "Feishu payload is empty"}
            logger.warning("Feishu payload is empty; skip push")
            return False

        try:
            result = self._post_payload_with_retry(payload)
            self.last_result = result
            if result.get("code") == 0:
                logger.info("Feishu webhook push succeeded")
                return True

            if result.get("code") == 19024:
                logger.warning("Feishu post payload hit keyword validation; retry with plain text")
                fallback = self._build_text_payload(latest_data, conclusions, title)
                fallback_result = self._post_payload_with_retry(fallback)
                self.last_result = fallback_result
                if fallback_result.get("code") == 0:
                    logger.info("Feishu webhook text fallback succeeded")
                    return True
                logger.error("Feishu webhook text fallback failed: %s", fallback_result)
                return False

            logger.error("Feishu webhook push failed: %s", result)
            return False
        except Exception as exc:
            self.last_result = {
                "code": "exception",
                "exception_type": exc.__class__.__name__,
                "msg": str(exc),
            }
            logger.error("Feishu webhook push error: %s", exc)
            return False

    def _post_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            self.webhook_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(self._attach_signature(payload), ensure_ascii=False),
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def _post_payload_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for attempt in range(4):
            try:
                result = self._post_payload(payload)
            except requests.RequestException as exc:
                if attempt == 3:
                    raise
                wait_seconds = 15 * (attempt + 1)
                logger.warning(
                    "Feishu webhook request failed (%s); retrying in %ss",
                    exc,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                continue

            if result.get("code") not in RETRYABLE_ERROR_CODES:
                return result

            wait_seconds = 15 * (attempt + 1)
            logger.warning(
                "Feishu webhook is frequency limited (code=%s); retrying in %ss",
                result.get("code"),
                wait_seconds,
            )
            time.sleep(wait_seconds)

        return result

    def _build_post_payload(
        self,
        latest_data: dict[str, Any],
        conclusions: dict[str, Any],
        title: str,
    ) -> dict[str, Any]:
        if not latest_data:
            return {}

        date_str = str(latest_data.get(KEY_DATE) or latest_data.get("trade_date") or "unknown")
        rows: list[list[dict[str, str]]] = []

        if self.webhook_keyword:
            rows.append([{"tag": "text", "text": self.webhook_keyword}])

        rows.append([{"tag": "text", "text": TITLE_RELATIVE_SIGNALS}])
        rows.append([{"tag": "text", "text": "\u6307\u6807\u540d\u79f0 | \u6bd4\u4ef7\u503c | \u5206\u4f4d\u6570 | \u5bf9\u5206\u5b50\u5efa\u8bae"}])
        for row in self._build_signal_rows(latest_data, conclusions):
            rows.append(
                [
                    {
                        "tag": "text",
                        "text": (
                            f"{row['name']} | {row['ratio']} | "
                            f"{row['percentile']} | {row['recommendation']}"
                        ),
                    }
                ]
            )

        return {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"{title} ({date_str})",
                        "content": rows,
                    }
                }
            },
        }

    def _build_text_payload(
        self,
        latest_data: dict[str, Any],
        conclusions: dict[str, Any],
        title: str,
    ) -> dict[str, Any]:
        date_str = str(latest_data.get(KEY_DATE) or latest_data.get("trade_date") or "unknown")
        lines: list[str] = []

        if self.webhook_keyword:
            lines.append(self.webhook_keyword)

        lines.extend([f"{title} ({date_str})", "\u6307\u6807\u540d\u79f0 | \u6bd4\u4ef7\u503c | \u5206\u4f4d\u6570 | \u5bf9\u5206\u5b50\u5efa\u8bae"])
        for row in self._build_signal_rows(latest_data, conclusions):
            lines.append(
                f"{row['name']} | {row['ratio']} | {row['percentile']} | {row['recommendation']}"
            )

        return {
            "msg_type": "text",
            "content": {"text": "\n".join(lines)},
        }

    def _build_signal_rows(
        self,
        latest_data: dict[str, Any],
        conclusions: dict[str, Any],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for label, code, ratio_keys, percentile_keys, recommendation_keys in RATIO_SIGNAL_ROWS:
            conclusion = conclusions.get(code, {})
            ratio = self._first_number(latest_data, ratio_keys)
            if ratio is None:
                ratio = self._safe_float(conclusion.get("current_ratio"))

            percentile = self._first_number(latest_data, percentile_keys)
            if percentile is None:
                percentile = self._safe_float(conclusion.get("percentile", {}).get("value"))

            recommendation = self._first_text(latest_data, recommendation_keys)
            if not recommendation:
                recommendation = str(conclusion.get("recommendation", {}).get("action", "")).strip()

            rows.append(
                {
                    "name": label,
                    "ratio": self._fmt_num(ratio),
                    "percentile": self._fmt_pct(percentile),
                    "recommendation": recommendation or "-",
                }
            )
        return rows

    def _pick_recommendation(self, conclusions: dict[str, Any], code: str) -> str:
        reverse_source = {
            "GRO300": "VAL300",
            "SH50": "SH50",
        }.get(code)
        if reverse_source:
            source_rec = conclusions.get(reverse_source, {}).get("recommendation", {})
            action = _REVERSE_REC.get(str(source_rec.get("action", "")).strip(), DEFAULT_REC)
            score = -float(source_rec.get("score", 0) or 0)
            return f"{action} (score={score:.2f})"

        rec = conclusions.get(code, {}).get("recommendation", {})
        action = str(rec.get("action", "-")).strip() or "-"
        score = float(rec.get("score", 0) or 0)
        return f"{action} (score={score:.2f})"

    @staticmethod
    def _fmt_num(value: Any) -> str:
        number = FeishuWebhook._safe_float(value)
        return f"{number:.4f}" if number is not None else "-"

    @staticmethod
    def _fmt_pct(value: Any) -> str:
        number = FeishuWebhook._safe_float(value)
        return f"{number:.1f}%" if number is not None else "-"

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _first_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = FeishuWebhook._safe_float(data.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return ""

    def _attach_signature(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.webhook_secret:
            return payload

        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{self.webhook_secret}"
        sign = base64.b64encode(
            hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")

        signed_payload = dict(payload)
        signed_payload["timestamp"] = timestamp
        signed_payload["sign"] = sign
        return signed_payload
