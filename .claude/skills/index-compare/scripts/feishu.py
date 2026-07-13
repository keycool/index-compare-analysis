"""
Feishu webhook push helpers for index compare analysis.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict

import requests

logger = logging.getLogger(__name__)

_VAL300_TO_GRO300_REC = {
    "强烈超配": "强烈低配",
    "超配": "低配",
    "标配": "标配",
    "低配": "超配",
    "强烈低配": "强烈超配",
}


class FeishuWebhook:
    """Feishu 机器人 webhook 推送。"""

    def __init__(self, webhook_url: str | None = None, webhook_secret: str | None = None):
        self.webhook_url = webhook_url or os.environ.get("FEISHU_WEBHOOK_URL")
        self.webhook_secret = (webhook_secret or os.environ.get("FEISHU_WEBHOOK_SECRET") or "").strip()

    def send(self, latest_data: Dict[str, Any], conclusions: Dict[str, Any], title: str = "核心比价指标") -> bool:
        if not self.webhook_url:
            logger.warning("Feishu webhook URL 未配置，跳过推送")
            return False

        payload = self._build_payload(latest_data, conclusions, title)
        if not payload:
            logger.warning("Feishu 消息内容为空，跳过推送")
            return False

        payload = self._attach_signature(payload)

        try:
            response = requests.post(
                self.webhook_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=10,
            )
            response.raise_for_status()

            result = response.json()
            if result.get("code") == 0:
                logger.info("Feishu webhook 推送成功")
                return True

            logger.error("Feishu webhook 推送失败: %s", result)
            return False
        except Exception as exc:
            logger.error("Feishu webhook 推送异常: %s", exc)
            return False

    def _build_payload(self, latest_data: Dict[str, Any], conclusions: Dict[str, Any], title: str) -> Dict[str, Any]:
        if not latest_data:
            return {}

        date_str = str(latest_data.get("日期", "未知日期"))

        def pick_recommendation(code: str) -> str:
            if code == "GRO300":
                val300_rec = conclusions.get("VAL300", {}).get("recommendation", {})
                action = _VAL300_TO_GRO300_REC.get(val300_rec.get("action", ""), "标配")
                score = -int(val300_rec.get("score", 0) or 0)
                return f"{action} (score={score})"

            rec = conclusions.get(code, {}).get("recommendation", {})
            action = rec.get("action", "-")
            score = rec.get("score", 0)
            return f"{action} (score={score})"

        rows = [
            [{"tag": "text", "text": "核心比价指标"}],
            [
                {"tag": "text", "text": "500/300: "},
                {"tag": "text", "text": f"{float(latest_data.get('500/300比价', 0)):.4f}", "color": "blue"},
                {"tag": "text", "text": " | 1000/300: "},
                {"tag": "text", "text": f"{float(latest_data.get('1000/300比价', 0)):.4f}", "color": "blue"},
            ],
            [
                {"tag": "text", "text": "创业板指数 / 沪深300: "},
                {"tag": "text", "text": f"{float(latest_data.get('创业板/300比价', 0)):.4f}", "color": "blue"},
                {"tag": "text", "text": " | 上证50指数 / 创业板指数: "},
                {"tag": "text", "text": f"{float(latest_data.get('50/创业板比价', 0)):.4f}", "color": "blue"},
            ],
            [
                {"tag": "text", "text": "科创50指数 / 上证50指数: "},
                {"tag": "text", "text": f"{float(latest_data.get('科创50/上证50比价', 0)):.4f}", "color": "blue"},
                {"tag": "text", "text": " | 300价值指数 / 300成长指数: "},
                {"tag": "text", "text": f"{float(latest_data.get('300价值/成长比价', 0)):.4f}", "color": "blue"},
            ],
            [
                {"tag": "text", "text": "恒生科技指数 / 恒生指数: "},
                {"tag": "text", "text": f"{float(latest_data.get('恒生科技/恒生比价', 0)):.4f}", "color": "blue"},
            ],
            [{"tag": "text", "text": "配置建议"}],
            [{"tag": "text", "text": f"中证500（相对沪深300）: {pick_recommendation('ZZ500')}"}],
            [{"tag": "text", "text": f"中证1000（相对沪深300）: {pick_recommendation('ZZ1000')}"}],
            [{"tag": "text", "text": f"创业板指数（相对沪深300）: {pick_recommendation('ZZA500')}"}],
            [{"tag": "text", "text": f"上证50指数（相对创业板指数）: {pick_recommendation('SH50')}"}],
            [{"tag": "text", "text": f"科创50指数（相对上证50指数）: {pick_recommendation('KC50')}"}],
            [{"tag": "text", "text": f"300成长指数（相对300价值指数）: {pick_recommendation('GRO300')}"}],
            [{"tag": "text", "text": f"恒生科技指数（相对恒生指数）: {pick_recommendation('HKTECH')}"}],
        ]

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

    def _attach_signature(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """If FEISHU_WEBHOOK_SECRET is configured, include Feishu signature fields."""
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
