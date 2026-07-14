"""
Feishu webhook push helpers for index compare analysis.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

TITLE_INDEX_COMPARE = "\u6307\u6570\u6bd4\u4ef7\u5206\u6790"
TITLE_CORE_METRICS = "\u6838\u5fc3\u6bd4\u4ef7\u6307\u6807"
TITLE_ALLOCATION = "\u914d\u7f6e\u5efa\u8bae"
DEFAULT_REC = "\u6807\u914d"

KEY_DATE = "\u65e5\u671f"
KEY_RATIO_500 = "500/300\u6bd4\u4ef7"
KEY_RATIO_1000 = "1000/300\u6bd4\u4ef7"
KEY_RATIO_CYB = "\u521b\u4e1a\u677f/300\u6bd4\u4ef7"
KEY_RATIO_SH50 = "50/\u521b\u4e1a\u677f\u6bd4\u4ef7"
KEY_RATIO_KC50 = "\u79d1\u521b50/\u4e0a\u8bc150\u6bd4\u4ef7"
KEY_RATIO_VALGRO = "300\u4ef7\u503c/\u6210\u957f\u6bd4\u4ef7"
KEY_RATIO_HKTECH = "\u6052\u751f\u79d1\u6280/\u6052\u751f\u6bd4\u4ef7"

LABEL_CYB = "\u521b\u4e1a\u677f\u6307\u6570"
LABEL_SH50 = "\u4e0a\u8bc150\u6307\u6570"
LABEL_KC50 = "\u79d1\u521b50\u6307\u6570"
LABEL_GRO300 = "300\u6210\u957f\u6307\u6570"
LABEL_HKTECH = "\u6052\u751f\u79d1\u6280\u6307\u6570"
LABEL_ZZ500 = "\u4e2d\u8bc1500"
LABEL_ZZ1000 = "\u4e2d\u8bc11000"

_VAL300_TO_GRO300_REC = {
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

    def send(
        self,
        latest_data: dict[str, Any],
        conclusions: dict[str, Any],
        title: str = TITLE_INDEX_COMPARE,
    ) -> bool:
        if not self.webhook_url:
            logger.warning("Feishu webhook URL is missing; skip push")
            return False

        payload = self._build_post_payload(latest_data, conclusions, title)
        if not payload:
            logger.warning("Feishu payload is empty; skip push")
            return False

        try:
            result = self._post_payload(payload)
            if result.get("code") == 0:
                logger.info("Feishu webhook push succeeded")
                return True

            if result.get("code") == 19024:
                logger.warning("Feishu post payload hit keyword validation; retry with plain text")
                fallback = self._build_text_payload(latest_data, conclusions, title)
                fallback_result = self._post_payload(fallback)
                if fallback_result.get("code") == 0:
                    logger.info("Feishu webhook text fallback succeeded")
                    return True
                logger.error("Feishu webhook text fallback failed: %s", fallback_result)
                return False

            logger.error("Feishu webhook push failed: %s", result)
            return False
        except Exception as exc:
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

    def _build_post_payload(
        self,
        latest_data: dict[str, Any],
        conclusions: dict[str, Any],
        title: str,
    ) -> dict[str, Any]:
        if not latest_data:
            return {}

        date_str = str(latest_data.get(KEY_DATE, "unknown"))
        rows: list[list[dict[str, str]]] = []

        if self.webhook_keyword:
            rows.append([{"tag": "text", "text": self.webhook_keyword}])

        rows.extend(
            [
                [{"tag": "text", "text": TITLE_CORE_METRICS}],
                [
                    {"tag": "text", "text": "500/300: "},
                    {"tag": "text", "text": self._fmt_num(latest_data.get(KEY_RATIO_500)), "color": "blue"},
                    {"tag": "text", "text": " | 1000/300: "},
                    {"tag": "text", "text": self._fmt_num(latest_data.get(KEY_RATIO_1000)), "color": "blue"},
                ],
                [
                    {"tag": "text", "text": "\u521b\u4e1a\u677f/300: "},
                    {"tag": "text", "text": self._fmt_num(latest_data.get(KEY_RATIO_CYB)), "color": "blue"},
                    {"tag": "text", "text": " | 50/\u521b\u4e1a\u677f: "},
                    {"tag": "text", "text": self._fmt_num(latest_data.get(KEY_RATIO_SH50)), "color": "blue"},
                ],
                [
                    {"tag": "text", "text": "\u79d1\u521b50/\u4e0a\u8bc150: "},
                    {"tag": "text", "text": self._fmt_num(latest_data.get(KEY_RATIO_KC50)), "color": "blue"},
                    {"tag": "text", "text": " | 300\u4ef7\u503c/300\u6210\u957f: "},
                    {"tag": "text", "text": self._fmt_num(latest_data.get(KEY_RATIO_VALGRO)), "color": "blue"},
                ],
                [
                    {"tag": "text", "text": "\u6052\u751f\u79d1\u6280/\u6052\u751f: "},
                    {"tag": "text", "text": self._fmt_num(latest_data.get(KEY_RATIO_HKTECH)), "color": "blue"},
                ],
                [{"tag": "text", "text": TITLE_ALLOCATION}],
                [{"tag": "text", "text": f"{LABEL_ZZ500}: {self._pick_recommendation(conclusions, 'ZZ500')}"}],
                [{"tag": "text", "text": f"{LABEL_ZZ1000}: {self._pick_recommendation(conclusions, 'ZZ1000')}"}],
                [{"tag": "text", "text": f"{LABEL_CYB}: {self._pick_recommendation(conclusions, 'ZZA500')}"}],
                [{"tag": "text", "text": f"{LABEL_SH50}: {self._pick_recommendation(conclusions, 'SH50')}"}],
                [{"tag": "text", "text": f"{LABEL_KC50}: {self._pick_recommendation(conclusions, 'KC50')}"}],
                [{"tag": "text", "text": f"{LABEL_GRO300}: {self._pick_recommendation(conclusions, 'GRO300')}"}],
                [{"tag": "text", "text": f"{LABEL_HKTECH}: {self._pick_recommendation(conclusions, 'HKTECH')}"}],
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
        date_str = str(latest_data.get(KEY_DATE, "unknown"))
        lines: list[str] = []

        if self.webhook_keyword:
            lines.append(self.webhook_keyword)

        lines.extend(
            [
                f"{title} ({date_str})",
                f"500/300={self._fmt_num(latest_data.get(KEY_RATIO_500))} | 1000/300={self._fmt_num(latest_data.get(KEY_RATIO_1000))}",
                f"\u521b\u4e1a\u677f/300={self._fmt_num(latest_data.get(KEY_RATIO_CYB))} | 50/\u521b\u4e1a\u677f={self._fmt_num(latest_data.get(KEY_RATIO_SH50))}",
                f"\u79d1\u521b50/\u4e0a\u8bc150={self._fmt_num(latest_data.get(KEY_RATIO_KC50))} | 300\u4ef7\u503c/300\u6210\u957f={self._fmt_num(latest_data.get(KEY_RATIO_VALGRO))}",
                f"\u6052\u751f\u79d1\u6280/\u6052\u751f={self._fmt_num(latest_data.get(KEY_RATIO_HKTECH))}",
                f"{LABEL_ZZ500}={self._pick_recommendation(conclusions, 'ZZ500')}",
                f"{LABEL_ZZ1000}={self._pick_recommendation(conclusions, 'ZZ1000')}",
                f"{LABEL_CYB}={self._pick_recommendation(conclusions, 'ZZA500')}",
                f"{LABEL_SH50}={self._pick_recommendation(conclusions, 'SH50')}",
                f"{LABEL_KC50}={self._pick_recommendation(conclusions, 'KC50')}",
                f"{LABEL_GRO300}={self._pick_recommendation(conclusions, 'GRO300')}",
                f"{LABEL_HKTECH}={self._pick_recommendation(conclusions, 'HKTECH')}",
            ]
        )

        return {
            "msg_type": "text",
            "content": {"text": "\n".join(lines)},
        }

    def _pick_recommendation(self, conclusions: dict[str, Any], code: str) -> str:
        if code == "GRO300":
            val300_rec = conclusions.get("VAL300", {}).get("recommendation", {})
            action = _VAL300_TO_GRO300_REC.get(str(val300_rec.get("action", "")).strip(), DEFAULT_REC)
            score = -int(val300_rec.get("score", 0) or 0)
            return f"{action} (score={score})"

        rec = conclusions.get(code, {}).get("recommendation", {})
        action = str(rec.get("action", "-")).strip() or "-"
        score = int(rec.get("score", 0) or 0)
        return f"{action} (score={score})"

    @staticmethod
    def _fmt_num(value: Any) -> str:
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError):
            return "-"

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
