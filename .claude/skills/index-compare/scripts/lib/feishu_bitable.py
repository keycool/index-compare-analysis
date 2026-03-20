#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
飞书多维表格 (Bitable) API 集成模块
- 按日期做记录索引
- 支持按日期 upsert（存在则更新，不存在则新增）
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

        self._tenant_token: Optional[str] = None
        self._token_expire_time = 0

        if not all([self.app_id, self.app_secret]):
            raise ValueError("FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量必填")

    def _ensure_token(self) -> str:
        if time.time() >= self._token_expire_time:
            self._refresh_token()
        return self._tenant_token or ""

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

    def _records_url(self, record_id: Optional[str] = None) -> str:
        base = f"{self.BITABLE_ENDPOINT}/apps/{self.app_token}/tables/{self.table_id}/records"
        return f"{base}/{record_id}" if record_id else base

    @staticmethod
    def _to_ms_timestamp(date_str: str) -> int:
        return int(datetime.strptime(date_str, "%Y-%m-%d").timestamp() * 1000)

    @staticmethod
    def _normalize_date_value(value) -> Optional[int]:
        """将飞书字段里的日期值归一化为毫秒时间戳。"""
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return int(value)

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.isdigit():
                return int(text)
            try:
                return int(datetime.strptime(text, "%Y-%m-%d").timestamp() * 1000)
            except Exception:
                return None

        if isinstance(value, dict):
            # 兼容可能的结构化日期字段
            for k in ("value", "timestamp", "time", "date"):
                if k in value:
                    return FeishuBitableClient._normalize_date_value(value[k])

        if isinstance(value, list) and value:
            return FeishuBitableClient._normalize_date_value(value[0])

        return None

    def get_date_record_index(self) -> Dict[int, str]:
        """获取当前表中 日期 -> record_id 索引。"""
        self._validate_table()

        index: Dict[int, str] = {}
        page_token = None

        while True:
            params = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token

            response = requests.get(
                self._records_url(),
                params=params,
                headers=self._get_headers(),
                timeout=20,
            )
            response.raise_for_status()

            payload = response.json()
            if payload.get("code") != 0:
                raise RuntimeError(f"查询记录失败: {payload}")

            data = payload.get("data", {})
            items = data.get("items", [])

            for item in items:
                record_id = item.get("record_id")
                fields = item.get("fields", {})
                date_val = self._normalize_date_value(fields.get("日期"))
                if record_id and date_val is not None:
                    index[date_val] = record_id

            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break

        return index

    @staticmethod
    def _build_csi_fields(record: Dict[str, float | str]) -> Dict[str, object]:
        """
        仅构造 CSI 相关字段，不覆盖 ERP 既有字段。
        日期作为对齐主键，仍会一并写入。
        """
        date_ts = FeishuBitableClient._to_ms_timestamp(str(record["日期"]))

        return {
            "日期": date_ts,
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
        }

    def _create_record(self, fields: Dict[str, object]) -> Dict[str, object]:
        response = requests.post(
            self._records_url(),
            json={"fields": fields},
            headers=self._get_headers(),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"新增记录失败: {data}")
        return data

    def _update_record(self, record_id: str, fields: Dict[str, object]) -> Dict[str, object]:
        response = requests.put(
            self._records_url(record_id),
            json={"fields": fields},
            headers=self._get_headers(),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"更新记录失败: {data}")
        return data

    def upsert_index_compare_record(
        self,
        record: Dict[str, float | str],
        date_index: Optional[Dict[int, str]] = None,
    ) -> Dict[str, object]:
        """
        按日期 upsert：存在则更新，不存在则新增。
        """
        self._validate_table()

        try:
            fields = self._build_csi_fields(record)
            date_ts = int(fields["日期"])

            if date_index is None:
                date_index = self.get_date_record_index()

            existing_record_id = date_index.get(date_ts)

            if existing_record_id:
                data = self._update_record(existing_record_id, fields)
                return {
                    "success": True,
                    "operation": "updated",
                    "record_id": existing_record_id,
                    "message": "已按日期更新飞书记录",
                }

            data = self._create_record(fields)
            new_id = data.get("data", {}).get("record", {}).get("record_id")
            if new_id:
                date_index[date_ts] = new_id
            return {
                "success": True,
                "operation": "created",
                "record_id": new_id,
                "message": "已新增飞书记录",
            }
        except Exception as exc:
            return {
                "success": False,
                "operation": "failed",
                "message": f"upsert失败: {exc}",
                "error": str(exc),
            }

    def query_records(self, filter_str: Optional[str] = None, limit: int = 100) -> List[Dict]:
        self._validate_table()
        params = {"page_size": min(limit, 500)}
        if filter_str:
            params["filter"] = filter_str

        response = requests.get(
            self._records_url(),
            params=params,
            headers=self._get_headers(),
            timeout=20,
        )
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"查询记录失败: {data}")

        return data.get("data", {}).get("items", [])

