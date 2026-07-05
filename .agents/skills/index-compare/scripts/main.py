#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
指数比价分析 - 主入口脚本
一键执行完整分析流程，并输出结构化 JSON 结果。
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

# 添加 skill 根目录到 Python 路径以支持模块导入
SCRIPT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_ROOT))

from scripts.feishu import FeishuWebhook
from scripts.lib.feishu_bitable import FeishuBitableClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def load_env_file() -> None:
    """加载 .env 文件中的环境变量（若存在）。"""
    env_path = SCRIPT_ROOT / ".env"
    if not env_path.exists():
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            os.environ[key.strip()] = value.strip()


def get_project_root() -> Path:
    """项目根目录：CSI300 Relative Index。"""
    return Path(__file__).resolve().parents[4]


def get_excel_output_path() -> Path:
    """获取输出 Excel 路径。"""
    env_path = os.environ.get("INDEX_COMPARE_OUTPUT_PATH")
    if env_path:
        return Path(env_path)

    return get_project_root() / "index_compare_enhanced.xlsx"


def get_shared_signal_path() -> Path:
    """获取 Relative 共享信号文件路径。"""
    env_path = os.environ.get("INDEX_COMPARE_SHARED_SIGNAL_PATH")
    if env_path:
        return Path(env_path)

    return get_project_root().parent / "shared" / "relative_signal.json"


def get_generated_at() -> str:
    """统一共享接口的生成时间格式。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_date_str(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")


def calc_expanding_percentile(series: Optional[pd.Series], index: pd.Index) -> pd.Series:
    """计算逐行历史分位（截至当日）。"""
    if series is None:
        return pd.Series([float("nan")] * len(index), index=index)

    s = pd.to_numeric(series, errors="coerce")

    def _percentile_last(window: pd.Series) -> float:
        valid = window.dropna()
        if valid.empty:
            return float("nan")
        return float((valid <= valid.iloc[-1]).mean() * 100)

    return s.expanding(min_periods=1).apply(_percentile_last, raw=False)


def calc_deviation_series(ratio_series: Optional[pd.Series], ma_series: Optional[pd.Series], index: pd.Index) -> pd.Series:
    """计算逐行偏离度(%)。"""
    if ratio_series is None or ma_series is None:
        return pd.Series([float("nan")] * len(index), index=index)

    ratio = pd.to_numeric(ratio_series, errors="coerce")
    ma = pd.to_numeric(ma_series, errors="coerce")
    deviation = (ratio - ma) / ma * 100
    return deviation.where(ma.notna())

def build_export_dataframe(processed_df: pd.DataFrame, conclusions: Dict[str, Any]) -> pd.DataFrame:
    """
    将处理后数据转换为统一导出结构（用于 Excel + 飞书多维表格）。
    """
    if processed_df.empty:
        return pd.DataFrame()

    df = processed_df.copy()
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"])
    else:
        df = df.reset_index().rename(columns={df.index.name or "index": "trade_date"})
        df["trade_date"] = pd.to_datetime(df["trade_date"])

    p500_series = calc_expanding_percentile(df.get("ZZ500_ratio"), df.index).round(1)
    p1000_series = calc_expanding_percentile(df.get("ZZ1000_ratio"), df.index).round(1)
    pa500_series = calc_expanding_percentile(df.get("ZZA500_ratio"), df.index).round(1)

    d500_series = calc_deviation_series(df.get("ZZ500_ratio"), df.get("ZZ500_MA30"), df.index).round(2)
    d1000_series = calc_deviation_series(df.get("ZZ1000_ratio"), df.get("ZZ1000_MA30"), df.index).round(2)
    da500_series = calc_deviation_series(df.get("ZZA500_ratio"), df.get("ZZA500_MA30"), df.index).round(2)
    export_df = pd.DataFrame(
        {
            "日期": df["trade_date"].dt.strftime("%Y-%m-%d"),
            "沪深300": df.get("HS300"),
            "中证500": df.get("ZZ500"),
            "中证1000": df.get("ZZ1000"),
            "中证A500": df.get("ZZA500"),
            "上证综指": df.get("SHCI"),
            "500/300比价": df.get("ZZ500_ratio"),
            "1000/300比价": df.get("ZZ1000_ratio"),
            "A500/300比价": df.get("ZZA500_ratio"),
            "500分位": p500_series,
            "1000分位": p1000_series,
            "A500分位": pa500_series,
            "500偏离(%)": d500_series,
            "1000偏离(%)": d1000_series,
            "A500偏离(%)": da500_series,
        }
    )

    export_df["500建议"] = ""
    export_df["1000建议"] = ""
    export_df["A500建议"] = ""

    if not export_df.empty:
        latest_idx = export_df.index[-1]
        export_df.loc[latest_idx, "500建议"] = conclusions.get("ZZ500", {}).get("recommendation", {}).get("action", "")
        export_df.loc[latest_idx, "1000建议"] = conclusions.get("ZZ1000", {}).get("recommendation", {}).get("action", "")
        export_df.loc[latest_idx, "A500建议"] = conclusions.get("ZZA500", {}).get("recommendation", {}).get("action", "")

    export_df["数据源"] = "tushare"

    number_cols = [
        "沪深300",
        "中证500",
        "中证1000",
        "中证A500",
        "上证综指",
        "500/300比价",
        "1000/300比价",
        "A500/300比价",
        "500分位",
        "1000分位",
        "A500分位",
        "500偏离(%)",
        "1000偏离(%)",
        "A500偏离(%)",
    ]
    for col in number_cols:
        if col in export_df.columns:
            export_df[col] = pd.to_numeric(export_df[col], errors="coerce")

    export_df = export_df.sort_values("日期").drop_duplicates(subset=["日期"], keep="last")

    ordered_cols = [
        "日期",
        "沪深300",
        "中证500",
        "中证1000",
        "中证A500",
        "上证综指",
        "500/300比价",
        "1000/300比价",
        "A500/300比价",
        "500分位",
        "1000分位",
        "A500分位",
        "500偏离(%)",
        "1000偏离(%)",
        "A500偏离(%)",
        "500建议",
        "1000建议",
        "A500建议",
        "数据源",
    ]
    return export_df[ordered_cols]


def _safe_float(value: Any, digits: int | None = None) -> Optional[float]:
    """将表格值安全转换为 float。"""
    try:
        if value is None:
            return None
        if pd.isna(value):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None

    if digits is not None:
        return round(number, digits)
    return number


def export_shared_signal(export_df: pd.DataFrame, output_path: Path) -> bool:
    """
    导出 Relative 标准共享接口，避免其他项目依赖内部文件结构。
    """
    if export_df.empty:
        logger.warning("共享接口导出跳过：导出数据为空")
        return False

    try:
        normalized_df = export_df.copy()
        normalized_df["日期"] = normalize_date_str(normalized_df["日期"])
        normalized_df = normalized_df.dropna(subset=["日期"]).sort_values("日期")

        records: list[Dict[str, Any]] = []
        for _, row in normalized_df.iterrows():
            records.append(
                {
                    "date": str(row["日期"]),
                    "hs300": _safe_float(row.get("沪深300"), 4),
                    "zz500": _safe_float(row.get("中证500"), 4),
                    "zz1000": _safe_float(row.get("中证1000"), 4),
                    "zza500": _safe_float(row.get("中证A500"), 4),
                    "shci": _safe_float(row.get("上证综指"), 4),
                    "zz500_ratio": _safe_float(row.get("500/300比价"), 6),
                    "zz1000_ratio": _safe_float(row.get("1000/300比价"), 6),
                    "zza500_ratio": _safe_float(row.get("A500/300比价"), 6),
                    "zz500_percentile": _safe_float(row.get("500分位"), 1),
                    "zz1000_percentile": _safe_float(row.get("1000分位"), 1),
                    "zza500_percentile": _safe_float(row.get("A500分位"), 1),
                    "zz500_deviation": _safe_float(row.get("500偏离(%)"), 2),
                    "zz1000_deviation": _safe_float(row.get("1000偏离(%)"), 2),
                    "zza500_deviation": _safe_float(row.get("A500偏离(%)"), 2),
                }
            )

        latest_row = normalized_df.iloc[-1]
        payload = {
            "version": "1.0",
            "signal_type": "csi300_relative_index",
            "source": "CSI300 Relative Index",
            "generated_at": get_generated_at(),
            "latest_date": str(latest_row["日期"]),
            "record_count": len(records),
            "records": records,
            "latest_signal": {
                "date": str(latest_row["日期"]),
                "zz500_recommendation": str(latest_row.get("500建议", "")),
                "zz1000_recommendation": str(latest_row.get("1000建议", "")),
                "zza500_recommendation": str(latest_row.get("A500建议", "")),
            },
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("共享接口已导出: %s", output_path)
        return True
    except Exception as exc:
        logger.error("导出共享接口失败: %s", exc)
        return False


def save_to_excel(df_new: pd.DataFrame, output_path: Path) -> tuple[bool, pd.DataFrame, pd.DataFrame]:
    """
    追加模式保存，按日期去重，返回新增行用于飞书同步。
    """
    if df_new.empty:
        logger.warning("导出数据为空，跳过 Excel 保存")
        return False, pd.DataFrame(), pd.DataFrame()

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df_existing = pd.DataFrame()
        existing_dates: set[str] = set()

        if output_path.exists():
            try:
                df_existing = pd.read_excel(output_path)
                if "日期" in df_existing.columns:
                    df_existing["日期"] = normalize_date_str(df_existing["日期"])
                    existing_dates = set(df_existing["日期"].dropna().astype(str).tolist())
                df_existing = df_existing.drop_duplicates(subset=["日期"], keep="last")
                logger.info(f"已读取原有 Excel 数据: {len(df_existing)} 条")
            except Exception as exc:
                logger.warning(f"读取原有 Excel 失败，将创建新文件: {exc}")

        df_new_local = df_new.copy()
        df_new_local["日期"] = normalize_date_str(df_new_local["日期"])
        df_new_records = df_new_local[~df_new_local["日期"].isin(existing_dates)].copy()

        if not df_existing.empty:
            df_merged = pd.concat([df_existing, df_new_local], ignore_index=True)
            df_merged = df_merged.drop_duplicates(subset=["日期"], keep="last").sort_values("日期")
        else:
            df_merged = df_new_local.sort_values("日期")

        df_merged.to_excel(output_path, index=False)

        logger.info(
            "Excel 保存成功: %s，合并后 %s 条，新增 %s 条",
            output_path,
            len(df_merged),
            len(df_new_records),
        )
        return True, df_merged, df_new_records
    except Exception as exc:
        logger.error(f"保存 Excel 失败: {exc}")
        return False, pd.DataFrame(), pd.DataFrame()


def sync_to_feishu_bitable(df_sync: pd.DataFrame) -> Dict[str, Any]:
    """同步记录到飞书多维表格（按日期 upsert）。"""
    required_env = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN", "FEISHU_TABLE_ID"]
    missing = [key for key in required_env if not os.environ.get(key)]
    if missing:
        message = f"配置不完整，缺少: {', '.join(missing)}"
        logger.warning(f"飞书多维表格{message}，跳过同步")
        return {
            "success": False,
            "message": message,
            "synced": 0,
            "failed": 0,
            "total": 0,
            "created": 0,
            "updated": 0,
            "errors": [],
        }

    if df_sync.empty:
        return {
            "success": True,
            "message": "无可同步数据",
            "synced": 0,
            "failed": 0,
            "total": 0,
            "created": 0,
            "updated": 0,
            "errors": [],
        }

    try:
        client = FeishuBitableClient()
        payloads = [row.to_dict() for _, row in df_sync.iterrows()]
        return client.upsert_index_compare_records(payloads)
    except Exception as exc:
        logger.error(f"飞书多维表格同步异常: {exc}")
        return {
            "success": False,
            "message": str(exc),
            "synced": 0,
            "failed": 0,
            "total": len(df_sync),
            "created": 0,
            "updated": 0,
            "errors": [{"error": str(exc)}],
        }


def print_terminal_summary(latest_row: Dict[str, Any], conclusions: Dict[str, Any], report_file: str) -> None:
    """打印简要结果摘要（保留原有终端体验）。"""
    print("\n" + "=" * 60)
    print("         [OK] 分析完成!")
    print("=" * 60)

    latest_date = latest_row.get("日期", "未知")
    print(f"\n[DATA] 最新数据 ({latest_date}):")
    print("+-------------+----------+----------+----------+")
    print("| 指标        | 中证500  | 中证1000 | 中证A500 |")
    print("+-------------+----------+----------+----------+")
    print(
        f"| 当前比价    | {float(latest_row.get('500/300比价', 0)):>8.4f} | "
        f"{float(latest_row.get('1000/300比价', 0)):>8.4f} | "
        f"{float(latest_row.get('A500/300比价', 0)):>8.4f} |"
    )
    print(
        f"| 历史分位    | {float(latest_row.get('500分位', 0)):>7.1f}% | "
        f"{float(latest_row.get('1000分位', 0)):>7.1f}% | "
        f"{float(latest_row.get('A500分位', 0)):>7.1f}% |"
    )
    print(
        f"| 30日偏离    | {float(latest_row.get('500偏离(%)', 0)):>+7.1f}% | "
        f"{float(latest_row.get('1000偏离(%)', 0)):>+7.1f}% | "
        f"{float(latest_row.get('A500偏离(%)', 0)):>+7.1f}% |"
    )
    print("+-------------+----------+----------+----------+")

    print("\n[RECOMMEND] 配置建议:")
    for code, name in [("ZZ500", "中证500"), ("ZZ1000", "中证1000"), ("ZZA500", "中证A500")]:
        recommendation = conclusions.get(code, {}).get("recommendation", {})
        action = recommendation.get("action", "-")
        icon = recommendation.get("icon", "")
        reasons = recommendation.get("reasons", [])
        print(f"\n【{name}】{icon} {action}")
        for reason in reasons:
            print(f"  - {reason}")

    print(f"\n[REPORT] 报告文件: {report_file}")


def quick_query(index_code: Optional[str] = None) -> None:
    """快速查询模式：读取已有数据并显示。"""
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)

    conclusions_file = Path("data/conclusions.json")
    processed_file = Path("data/processed_data.csv")

    if not conclusions_file.exists() or not processed_file.exists():
        print("[错误] 数据文件不存在")
        print("\n请先运行完整分析生成数据:")
        print("  python scripts/main.py")
        sys.exit(1)

    with open(conclusions_file, "r", encoding="utf-8") as f:
        conclusions = json.load(f)

    df = pd.read_csv(processed_file, parse_dates=["trade_date"])
    latest_date = df.iloc[-1]["trade_date"].strftime("%Y-%m-%d")

    valid_codes = ["ZZ500", "ZZ1000", "ZZA500"]
    if index_code and index_code not in valid_codes:
        print(f"[错误] 指数代码 {index_code} 不存在")
        print(f"\n支持的代码: {', '.join(valid_codes)}")
        sys.exit(1)

    print("=" * 60)
    print("         指数比价快速查询")
    print("=" * 60)
    print(f"数据更新时间: {latest_date}")
    print()

    display_codes = [index_code] if index_code else valid_codes

    if len(display_codes) > 1:
        print("最新数据:")
        print("┌─────────────┬──────────┬──────────┬──────────┐")
        print("│ 指标        │ 中证500  │ 中证1000 │ 中证A500 │")
        print("├─────────────┼──────────┼──────────┼──────────┤")

        zz500 = conclusions.get("ZZ500", {})
        zz1000 = conclusions.get("ZZ1000", {})
        zza500 = conclusions.get("ZZA500", {})

        print(
            f"│ 当前比价    │ {zz500.get('current_ratio', 0):>8.4f} │ "
            f"{zz1000.get('current_ratio', 0):>8.4f} │ {zza500.get('current_ratio', 0):>8.4f} │"
        )
        print(
            f"│ 历史分位    │ {zz500.get('percentile', {}).get('value', 0):>7.1f}% │ "
            f"{zz1000.get('percentile', {}).get('value', 0):>7.1f}% │ "
            f"{zza500.get('percentile', {}).get('value', 0):>7.1f}% │"
        )
        print(
            f"│ 30日偏离    │ {zz500.get('deviation', {}).get('value', 0):>+7.1f}% │ "
            f"{zz1000.get('deviation', {}).get('value', 0):>+7.1f}% │ "
            f"{zza500.get('deviation', {}).get('value', 0):>+7.1f}% │"
        )

        zz500_text = f"{zz500.get('recommendation', {}).get('icon', '')} {zz500.get('recommendation', {}).get('action', '')}"
        zz1000_text = f"{zz1000.get('recommendation', {}).get('icon', '')} {zz1000.get('recommendation', {}).get('action', '')}"
        zza500_text = f"{zza500.get('recommendation', {}).get('icon', '')} {zza500.get('recommendation', {}).get('action', '')}"
        print(f"│ 配置建议    │ {zz500_text:^8} │ {zz1000_text:^8} │ {zza500_text:^8} │")
        print("└─────────────┴──────────┴──────────┴──────────┘")
        print()

    for code in display_codes:
        print(conclusions.get(code, {}).get("summary", ""))
        print()
        print("-" * 60)
        print()


def run_pipeline(force_update: bool = False) -> Dict[str, Any]:
    """运行完整分析流程并返回结构化结果。"""
    os.chdir(SCRIPT_ROOT)

    load_env_file()

    # 自动清理临时文件
    try:
        from scripts.cleanup import cleanup_temp_files

        deleted_count, triggered = cleanup_temp_files(max_files=20)
        if triggered:
            print(f"[清理] 已清理 {deleted_count} 个临时文件")
    except Exception:
        pass

    print("=" * 60)
    print("         指数比价分析 (Index Compare)")
    print("=" * 60)
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    print("\n[步骤 1/7] 检查环境配置...")
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN 环境变量")
        print("\n请按以下方式设置:")
        print("  Windows PowerShell: $env:TUSHARE_TOKEN = '你的Token'")
        print("  Windows CMD: set TUSHARE_TOKEN=你的Token")
        print("  Linux/Mac: export TUSHARE_TOKEN=你的Token")
        print("  或在 skill 目录下创建 .env 文件并添加: TUSHARE_TOKEN=你的Token")
        print("\n获取Token: https://tushare.pro/register")
        sys.exit(1)
    print("[OK] Token 已配置")

    try:
        from scripts.fetch_data import fetch_all_data
        from scripts.calculate import process_data
        from scripts.analyze import analyze
        from scripts.generate_report import generate_report
    except ImportError as exc:
        print(f"[ERROR] 导入模块失败: {exc}")
        print("请确保已安装所有依赖: pip install tushare pandas numpy plotly scipy requests")
        sys.exit(1)

    with open(SCRIPT_ROOT / "config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    report_dir = config["output"]["report_dir"]

    print("\n[步骤 2/7] 获取指数数据...")
    try:
        fetch_all_data("data/raw_data.csv", force_update=force_update)
    except Exception as exc:
        print(f"[ERROR] 数据获取失败: {exc}")
        sys.exit(1)

    print("\n[步骤 3/7] 计算比价指标...")
    try:
        process_data("data/raw_data.csv", "data/processed_data.csv")
    except Exception as exc:
        print(f"[ERROR] 比价计算失败: {exc}")
        sys.exit(1)

    print("\n[步骤 4/7] 生成智能分析...")
    try:
        analyze("data/analysis_results.json", "data/conclusions.json")
    except Exception as exc:
        print(f"[ERROR] 智能分析失败: {exc}")
        sys.exit(1)

    print("\n[步骤 5/7] 生成 HTML 报告...")
    try:
        report_file = generate_report("data/processed_data.csv", "data/conclusions.json", report_dir, mode="production")
    except Exception as exc:
        print(f"[ERROR] 报告生成失败: {exc}")
        sys.exit(1)

    processed_df = pd.read_csv("data/processed_data.csv", parse_dates=["trade_date"])
    with open("data/conclusions.json", "r", encoding="utf-8") as f:
        conclusions = json.load(f)

    print("\n[步骤 6/7] 保存 Excel（追加去重）...")
    export_df = build_export_dataframe(processed_df, conclusions)
    excel_output_path = get_excel_output_path()
    excel_saved, _, new_rows_df = save_to_excel(export_df, excel_output_path)
    shared_signal_path = get_shared_signal_path()
    shared_signal_saved = export_shared_signal(export_df, shared_signal_path)

    print("\n[步骤 7/7] 同步飞书（Webhook + 多维表格）...")

    latest_row: Dict[str, Any] = export_df.iloc[-1].to_dict() if not export_df.empty else {}

    feishu_sent = False
    if os.environ.get("FEISHU_WEBHOOK_URL") and latest_row:
        feishu = FeishuWebhook()
        feishu_sent = feishu.send(latest_row, conclusions, title="指数比价分析")

    bitable_result = {
        "success": False,
        "message": "未执行",
        "synced": 0,
        "failed": 0,
        "total": 0,
        "created": 0,
        "updated": 0,
        "errors": [],
    }

    if excel_saved:
        bitable_result = sync_to_feishu_bitable(new_rows_df)

    print_terminal_summary(latest_row, conclusions, report_file)

    core_success = not export_df.empty

    result = {
        "success": core_success,
        "source": "tushare",
        "record_count": int(len(export_df)),
        "new_record_count": int(len(new_rows_df)),
        "latest_date": latest_row.get("日期"),
        "latest": latest_row,
        "report_file": report_file,
        "excel_saved": excel_saved,
        "excel_path": str(excel_output_path) if excel_saved else None,
        "shared_signal_saved": shared_signal_saved,
        "shared_signal_path": str(shared_signal_path) if shared_signal_saved else None,
        "feishu_sent": feishu_sent,
        "bitable_synced": bitable_result.get("success", False),
        "bitable_count": bitable_result.get("synced", 0),
        "bitable_failed": bitable_result.get("failed", 0),
        "bitable_total": bitable_result.get("total", 0),
        "bitable_created": bitable_result.get("created", 0),
        "bitable_updated": bitable_result.get("updated", 0),
        "bitable_message": bitable_result.get("message", ""),
        "bitable_errors": bitable_result.get("errors", []),
    }

    require_bitable_sync = str(os.environ.get("REQUIRE_BITABLE_SYNC", "false")).lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }

    if require_bitable_sync:
        has_new_rows = int(len(new_rows_df)) > 0
        sync_ok = bool(bitable_result.get("success", False))
        synced_count = int(bitable_result.get("synced", 0) or 0)

        if has_new_rows and (not sync_ok or synced_count < int(len(new_rows_df))):
            result["success"] = False
            result["error"] = (
                f"要求飞书多维表格同步成功，但本次新增 {len(new_rows_df)} 条，仅成功 {synced_count} 条"
            )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="指数比价分析工具 - 一体化流程（本地存储 + 飞书同步 + HTML报告）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                 # 完整流程（自动增量更新）
  python main.py --force         # 强制完整更新
  python main.py --query         # 快速查询已有数据（所有指数）
  python main.py --query ZZ500   # 快速查询中证500
""",
    )

    parser.add_argument(
        "--query",
        nargs="?",
        const="all",
        help="快速查询模式：查看已有数据（可选指定 ZZ500/ZZ1000/ZZA500）",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="强制完整更新所有历史数据（忽略增量检查）",
    )

    args = parser.parse_args()

    if args.query is not None:
        query_target = None if args.query == "all" else args.query
        quick_query(query_target)
        return

    result = run_pipeline(force_update=args.force)

    if not result.get("success", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
