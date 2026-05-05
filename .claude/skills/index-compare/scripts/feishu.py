"""
飞书Webhook推送模块（指数比价分析）
"""

import json
import logging
import os
from typing import Any, Dict

import requests

logger = logging.getLogger(__name__)


class FeishuWebhook:
    """飞书机器人Webhook推送类"""

    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url or os.environ.get("FEISHU_WEBHOOK_URL")

    def send(self, latest_data: Dict[str, Any], conclusions: Dict[str, Any], title: str = "指数比价分析") -> bool:
        if not self.webhook_url:
            logger.warning("飞书Webhook URL未配置，跳过推送")
            return False

        payload = self._build_payload(latest_data, conclusions, title)
        if not payload:
            logger.warning("飞书消息内容为空，跳过推送")
            return False

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
                logger.info("飞书Webhook推送成功")
                return True

            logger.error(f"飞书Webhook推送失败: {result}")
            return False
        except Exception as exc:
            logger.error(f"飞书Webhook推送异常: {exc}")
            return False

    def _build_payload(self, latest_data: Dict[str, Any], conclusions: Dict[str, Any], title: str) -> Dict[str, Any]:
        if not latest_data:
            return {}

        date_str = str(latest_data.get("日期", "未知日期"))

        def pick_recommendation(code: str) -> str:
            rec = conclusions.get(code, {}).get("recommendation", {})
            action = rec.get("action", "-")
            score = rec.get("score", 0)
            return f"{action} (score={score})"

        rows = [
            [
                {"tag": "text", "text": "📊 核心比价指标"},
            ],
            [
                {"tag": "text", "text": "500/300: "},
                {"tag": "text", "text": f"{float(latest_data.get('500/300比价', 0)):.4f}", "color": "blue"},
                {"tag": "text", "text": " | 1000/300: "},
                {"tag": "text", "text": f"{float(latest_data.get('1000/300比价', 0)):.4f}", "color": "blue"},
            ],
            [
                {"tag": "text", "text": "创业板/300: "},
                {"tag": "text", "text": f"{float(latest_data.get('创业板/300比价', 0)):.4f}", "color": "blue"},
            ],
            [
                {"tag": "text", "text": "━━━━━━━━━━━━━━━━━━"},
            ],
            [
                {"tag": "text", "text": "🎯 配置建议"},
            ],
            [
                {"tag": "text", "text": f"中证500: {pick_recommendation('ZZ500')}"},
            ],
            [
                {"tag": "text", "text": f"中证1000: {pick_recommendation('ZZ1000')}"},
            ],
            [
                {"tag": "text", "text": f"创业板指数: {pick_recommendation('ZZA500')}"},
            ],
        ]

        return {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"📈 {title} ({date_str})",
                        "content": rows,
                    }
                }
            },
        }
