"""
飞书Webhook推送模块
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional

import requests

logger = logging.getLogger(__name__)


class FeishuWebhook:
    """飞书机器人Webhook推送类"""

    def __init__(self, webhook_url: Optional[str] = None):
        """
        初始化

        Args:
            webhook_url: 飞书Webhook地址，若未设置则从环境变量读取
        """
        self.webhook_url = webhook_url or os.environ.get("FEISHU_WEBHOOK_URL")

    def send(
        self,
        data: List[Dict[str, Any]],
        title: str = "股权溢价指数"
    ) -> bool:
        """
        发送数据到飞书

        Args:
            data: 数据列表
            title: 标题

        Returns:
            bool: 是否发送成功
        """
        if not self.webhook_url:
            logger.warning("飞书Webhook URL未配置，跳过推送")
            return False

        try:
            payload = self._build_payload(data, title)
            response = requests.post(
                self.webhook_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    logger.info("飞书推送成功")
                    return True
                else:
                    logger.error(f"飞书推送失败: {result.get('msg')}")
                    return False
            else:
                logger.error(f"飞书推送失败: HTTP {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"飞书推送异常: {e}")
            return False

    def _build_payload(
        self,
        data: List[Dict[str, Any]],
        title: str
    ) -> Dict[str, Any]:
        """构建飞书消息载荷"""
        if not data:
            return {}

        # 取最新一条数据
        latest = data[-1]

        # 构建内容
        content = []

        # 标题
        content.append([
            {"tag": "text", "text": "📊 核心指标"}
        ])

        # 沪深300 PE_TTM
        pe_ttm = latest.get('csi300_pe_ttm') or latest.get('pe_ttm')
        if pe_ttm:
            content.append([
                {"tag": "text", "text": "沪深300 PE_TTM: "},
                {"tag": "text", "text": f"{pe_ttm:.2f}", "color": "blue"}
            ])

        # 沪深300点位
        csi300_close = latest.get('csi300_close')
        if csi300_close:
            content.append([
                {"tag": "text", "text": "沪深300点位: "},
                {"tag": "text", "text": f"{csi300_close:.2f}", "color": "blue"}
            ])

        # 国债收益率
        bond_yield = latest.get('bond_yield')
        if bond_yield:
            content.append([
                {"tag": "text", "text": "10年国债收益率: "},
                {"tag": "text", "text": f"{bond_yield:.2f}%", "color": "green"}
            ])

        # 盈利收益率
        earnings_yield = latest.get('earnings_yield')
        if earnings_yield:
            content.append([
                {"tag": "text", "text": "盈利收益率: "},
                {"tag": "text", "text": f"{earnings_yield:.2f}%", "color": "blue"}
            ])

        # 分隔线（飞书post不支持div，改为纯文本）
        content.append([
            {"tag": "text", "text": "━━━━━━━━━━━━━━━━━━"}
        ])

        # 股权溢价指数（重点显示）
        equity_premium = latest.get('equity_premium')
        if equity_premium is not None:
            content.append([
                {"tag": "text", "text": "🎯 股权溢价指数: "},
                {"tag": "text", "text": f"{equity_premium:.2f}%", "color": "red"}
            ])

        # 附加日期
        date_str = latest.get('date')
        if date_str:
            if hasattr(date_str, 'strftime'):
                date_str = date_str.strftime('%Y-%m-%d')

        # 构建完整payload
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"📈 {title} ({date_str})",
                        "content": content
                    }
                }
            }
        }

        return payload


def send_to_feishu(
    data: List[Dict[str, Any]],
    title: str = "股权溢价指数",
    webhook_url: Optional[str] = None
) -> bool:
    """
    发送数据到飞书的便捷函数

    Args:
        data: 数据列表
        title: 标题
        webhook_url: Webhook地址

    Returns:
        bool: 是否发送成功
    """
    webhook = FeishuWebhook(webhook_url)
    return webhook.send(data, title)


if __name__ == "__main__":
    # 测试
    import pandas as pd

    # 模拟数据
    test_data = [
        {
            "date": "2026-02-13",
            "csi300_pe_ttm": 14.01,
            "csi300_close": 4660.41,
            "bond_yield": 1.809,
            "earnings_yield": 7.1378,
            "equity_premium": 5.33
        }
    ]

    # 测试构建payload（不实际发送）
    feishu = FeishuWebhook()
    payload = feishu._build_payload(test_data)
    print("飞书消息载荷:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

