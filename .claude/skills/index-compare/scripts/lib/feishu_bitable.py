#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
飞书多维表格 (Bitable) API 集成模块
"""

import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests


class FeishuBitableClient:
    """飞书多维表格客户端"""

    BASE_URL = "https://open.feishu.cn/open-apis"
    AUTH_ENDPOINT = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    BITABLE_ENDPOINT = f"{BASE_URL}/bitable/v1"

    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID")
        self.app_secret = os.getenv("FEISHU_APP_SECRET")
        self.app_token = os.getenv("FEISHU_APP_TOKEN")
        self.table_id = os.getenv("FEISHU_TABLE_ID")

        self._tenant_token = None
        self._token_expire_time = 0

        if not all([self.app_id, self.app_secret]):
            raise ValueError("FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量必填")

    def _ensure_token(self) -> str:
        if time.time() >= self._token_expire_time:
            self._refresh_token()
        return self._tenant_token

    def _refresh_token(self):
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }
        response = requests.post(
            self.AUTH_ENDPOINT,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取token失败: {data}")

        self._tenant_token = data["tenant_access_token"]
        self._token_expire_time = time.time() + data.get("expire", 7200) - 300

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
        }

    def _validate_table(self):
        if not all([self.app_token, self.table_id]):
            raise ValueError("请配置 FEISHU_APP_TOKEN 和 FEISHU_TABLE_ID")

    @staticmethod
    def _to_ms_timestamp(date_str: str) -> int:
        return int(datetime.strptime(date_str, "%Y-%m-%d").timestamp() * 1000)

    def add_index_compare_record(self, record: Dict[str, float | str]) -> Dict[str, object]:
        """
        新增 CSI300 Relative Index 记录
        字段命名与多维表格保持一致（中文）
        """
        self._validate_table()

        fields = {
            "日期": self._to_ms_timestamp(str(record["日期"])),
            "沪深300": float(record.get("沪深300", 0) or 0),
            "中证500": float(record.get("中证500", 0) or 0),
            "中证1000": float(record.get("中证1000", 0) or 0),
            "中证A500": float(record.get("中证A500", 0) or 0),
            "上证综指": float(record.get("上证综指", 0) or 0),
            "500/300比价": float(record.get("500/300比价", 0) or 0),
            "1000/300比价": float(record.get("1000/300比价", 0) or 0),
            "A500/300比价": float(record.get("A500/300比价", 0) or 0),
            "500分位": float(record.get("500分位", 0) or 0),
            "1000分位": float(record.get("1000分位", 0) or 0),
            "A500分位": float(record.get("A500分位", 0) or 0),
            "500偏离(%)": float(record.get("500偏离(%)", 0) or 0),
            "1000偏离(%)": float(record.get("1000偏离(%)", 0) or 0),
            "A500偏离(%)": float(record.get("A500偏离(%)", 0) or 0),
            "500建议": str(record.get("500建议", "")),
            "1000建议": str(record.get("1000建议", "")),
            "A500建议": str(record.get("A500建议", "")),
            "数据源": str(record.get("数据源", "tushare")),
        }

        url = f"{self.BITABLE_ENDPOINT}/apps/{self.app_token}/tables/{self.table_id}/records"
        try:
            response = requests.post(
                url,
                json={"fields": fields},
                headers=self._get_headers(),
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != 0:
                raise RuntimeError(f"新增记录失败: {data}")
            return {
                "success": True,
                "record_id": data.get("data", {}).get("record", {}).get("record_id"),
                "message": "记录已添加到飞书多维表格",
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"添加记录失败: {exc}",
                "error": str(exc),
            }

    def query_records(self, filter_str: Optional[str] = None, limit: int = 100) -> List[Dict]:
        self._validate_table()
        url = f"{self.BITABLE_ENDPOINT}/apps/{self.app_token}/tables/{self.table_id}/records"
        params = {"page_size": min(limit, 500)}
        if filter_str:
            params["filter"] = filter_str

        response = requests.get(url, params=params, headers=self._get_headers(), timeout=20)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"查询记录失败: {data}")

        return data.get("data", {}).get("items", [])
