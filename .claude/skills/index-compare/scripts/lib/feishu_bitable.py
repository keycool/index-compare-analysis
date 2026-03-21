#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
飞书多维表格 (Bitable) API 集成模块
- 按日期做记录索引
- 支持按日期 upsert（存在则更新，不存在则新增）
"""

import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests


class FeishuBitableClient:
    """飞书多维表格客户端"""

    BASE_URL = "https://open.feishu.cn/open-apis"
    AUTH_ENDPOINT = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    BITABLE_ENDPOINT = f"{BASE_URL}/bitable/v1"
    SH_TZ = timezone(timedelta(hours=8))

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
    def _safe_float(value, default: float = 0.0) -> float:
        """将任意输入安全转换为有限浮点数，避免 NaN/Inf 导致 JSON 序列化失败。"""
        if value is None:
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(number):
            return default
        return number

    @staticmethod
    def _safe_text(value) -> str:
        if value is None:
            return ""
        return str(value)

    @classmethod
    def _parse_date_key(cls, text: str) -> Optional[str]:
        s = text.strip()
        if not s:
            return None

        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    @classmethod
    def _timestamp_to_date_key(cls, timestamp_value: int) -> Optional[str]:
        """将秒/毫秒时间戳统一转换为日期键（YYYY-MM-DD，上海时区）。"""
        try:
            ts = int(timestamp_value)
        except Exception:
            return None

        # 10位按秒处理，13位按毫秒处理
        if abs(ts) < 10_000_000_000:
            ts_ms = ts * 1000
        else:
            ts_ms = ts

        try:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(cls.SH_TZ)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    @classmethod
    def _to_date_key(cls, value) -> Optional[str]:
        """把飞书日期字段或输入日期统一归一化为 YYYY-MM-DD。"""
        if value is None:
            return None

        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                return None
            return cls._timestamp_to_date_key(int(value))

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None

            # 优先按日期字符串解析，兼容 YYYYMMDD / YYYY-MM-DD / YYYY/MM/DD
            parsed = cls._parse_date_key(text)
            if parsed:
                return parsed

            # 再回退到时间戳解析（秒/毫秒）
            if text.isdigit():
                return cls._timestamp_to_date_key(int(text))
            return None

        if isinstance(value, dict):
            for k in ("value", "timestamp", "time", "date"):
                if k in value:
                    return cls._to_date_key(value[k])

        if isinstance(value, list) and value:
            return cls._to_date_key(value[0])

        return None

    @classmethod
    def _to_ms_timestamp(cls, date_str: str) -> int:
        """将日期字符串统一转换为上海时区零点的毫秒时间戳（跨环境稳定）。"""
        date_key = cls._to_date_key(date_str)
        if not date_key:
            raise ValueError(f"无效日期: {date_str}")

        dt = datetime.strptime(date_key, "%Y-%m-%d").replace(tzinfo=cls.SH_TZ)
        return int(dt.timestamp() * 1000)

    def get_date_record_index(self) -> Dict[str, str]:
        """获取当前表中 日期(YYYY-MM-DD) -> record_id 索引。"""
        self._validate_table()

        index: Dict[str, str] = {}
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
                date_key = self._to_date_key(fields.get("日期"))
                if record_id and date_key:
                    index[date_key] = record_id

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
            "中证500": FeishuBitableClient._safe_float(record.get("中证500"), 0.0),
            "中证1000": FeishuBitableClient._safe_float(record.get("中证1000"), 0.0),
            "中证A500": FeishuBitableClient._safe_float(record.get("中证A500"), 0.0),
            "上证综指": FeishuBitableClient._safe_float(record.get("上证综指"), 0.0),
            "500/300比价": FeishuBitableClient._safe_float(record.get("500/300比价"), 0.0),
            "1000/300比价": FeishuBitableClient._safe_float(record.get("1000/300比价"), 0.0),
            "A500/300比价": FeishuBitableClient._safe_float(record.get("A500/300比价"), 0.0),
            "500分位": FeishuBitableClient._safe_float(record.get("500分位"), 0.0),
            "1000分位": FeishuBitableClient._safe_float(record.get("1000分位"), 0.0),
            "A500分位": FeishuBitableClient._safe_float(record.get("A500分位"), 0.0),
            "500偏离(%)": FeishuBitableClient._safe_float(record.get("500偏离(%)"), 0.0),
            "1000偏离(%)": FeishuBitableClient._safe_float(record.get("1000偏离(%)"), 0.0),
            "A500偏离(%)": FeishuBitableClient._safe_float(record.get("A500偏离(%)"), 0.0),
            "500建议": FeishuBitableClient._safe_text(record.get("500建议")),
            "1000建议": FeishuBitableClient._safe_text(record.get("1000建议")),
            "A500建议": FeishuBitableClient._safe_text(record.get("A500建议")),
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
        date_index: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        """
        按日期 upsert：存在则更新，不存在则新增。
        """
        self._validate_table()

        try:
            date_key = self._to_date_key(record.get("日期"))
            if not date_key:
                raise ValueError(f"无效日期: {record.get('日期')}")

            fields = self._build_csi_fields(record)

            if date_index is None:
                date_index = self.get_date_record_index()

            existing_record_id = date_index.get(date_key)

            if existing_record_id:
                self._update_record(existing_record_id, fields)
                return {
                    "success": True,
                    "operation": "updated",
                    "record_id": existing_record_id,
                    "message": "已按日期更新飞书记录",
                }

            data = self._create_record(fields)
            new_id = data.get("data", {}).get("record", {}).get("record_id")
            if new_id:
                date_index[date_key] = new_id
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

