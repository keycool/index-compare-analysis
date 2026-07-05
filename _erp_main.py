"""
股权溢价指数 Skill 主入口
"""

import os
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

# 加载 .env 文件
env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if env_file.exists():
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

from data_source import EquityPremiumData
from feishu import FeishuWebhook
from lib.feishu_bitable import FeishuBitableClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_system_root() -> Path:
    """获取 ERP Investment System 根目录。"""
    return Path(__file__).resolve().parents[3]


def get_shared_signal_path() -> Path:
    """获取 ERP 共享信号文件路径。"""
    env_path = os.environ.get("ERP_SHARED_SIGNAL_PATH")
    if env_path:
        return Path(env_path)
    return get_system_root() / "shared" / "erp_signal.json"


def _to_iso_datetime(dt: datetime) -> str:
    """统一输出上海时区风格时间戳文本。"""
    return dt.astimezone().isoformat(timespec="seconds")


def _safe_float(value: Any, digits: int | None = None) -> Optional[float]:
    """将数值安全转换为 float，非法值返回 None。"""
    try:
        if value is None:
            return None
        if hasattr(value, "item"):
            value = value.item()
        number = float(value)
    except (TypeError, ValueError):
        return None

    if digits is not None:
        return round(number, digits)
    return number


def export_shared_signal(df, output_path: Path) -> bool:
    """
    导出 ERP 标准共享接口，供其他项目稳定消费。

    Args:
        df: pandas DataFrame
        output_path: JSON 输出路径

    Returns:
        bool: 是否导出成功
    """
    if df.empty:
        logger.warning("共享接口导出跳过：数据为空")
        return False

    try:
        import pandas as pd

        payload_records = []
        normalized_df = df.copy()
        normalized_df["date"] = pd.to_datetime(normalized_df["date"], errors="coerce")
        normalized_df = normalized_df.dropna(subset=["date"]).sort_values("date")

        for _, row in normalized_df.iterrows():
            payload_records.append(
                {
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "csi300_close": _safe_float(row.get("csi300_close"), 4),
                    "pe_ttm": _safe_float(row.get("pe_ttm"), 4),
                    "bond_yield": _safe_float(row.get("bond_yield"), 4),
                    "earnings_yield": _safe_float(row.get("earnings_yield"), 4),
                    "equity_premium": _safe_float(row.get("equity_premium"), 4),
                }
            )

        latest = payload_records[-1]
        payload = {
            "version": "1.0",
            "signal_type": "equity_risk_premium",
            "source": "Equity Risk Premium",
            "generated_at": _to_iso_datetime(datetime.now().astimezone()),
            "latest_date": latest["date"],
            "record_count": len(payload_records),
            "records": payload_records,
            "latest_signal": {
                "date": latest["date"],
                "equity_premium": latest.get("equity_premium"),
                "bond_yield": latest.get("bond_yield"),
                "pe_ttm": latest.get("pe_ttm"),
                "earnings_yield": latest.get("earnings_yield"),
                "csi300_close": latest.get("csi300_close"),
            },
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"共享接口已导出: {output_path}")
        return True
    except Exception as e:
        logger.error(f"导出共享接口失败: {e}")
        return False


def parse_args(args: str) -> Tuple[Optional[str], Optional[str]]:
    """
    解析命令参数

    Args:
        args: 命令参数字符串，如 "20250101 20250213" 或 "20250213"

    Returns:
        (start_date, end_date)
    """
    if not args or not args.strip():
        return None, None

    # 匹配日期格式 YYYYMMDD 或 YYYY-MM-DD
    date_pattern = r'(\d{4}[-\.]?\d{2}[-\.]?\d{2})'
    dates = re.findall(date_pattern, args.replace('-', '').replace('.', ''))

    if not dates:
        return None, None

    # 格式化日期
    def format_date(d: str) -> str:
        if len(d) == 8:
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return d

    if len(dates) == 1:
        # 只有一个日期，作为end_date
        return None, format_date(dates[0])
    elif len(dates) >= 2:
        return format_date(dates[0]), format_date(dates[1])

    return None, None


def supplement_missing_data(df):
    """
    补充缺失日期的PE_TTM等数据

    Args:
        df: pandas DataFrame

    Returns:
        DataFrame: 补充后的数据
    """
    import pandas as pd

    # 检测哪些行缺少PE_TTM数据
    if 'pe_ttm' not in df.columns:
        return df

    missing_mask = df['pe_ttm'].isna()
    if not missing_mask.any():
        logger.info("没有需要补充的缺失数据")
        return df

    # 获取缺失数据的日期范围
    missing_dates = df[missing_mask]['date'].tolist()
    if not missing_dates:
        return df

    min_date = pd.to_datetime(missing_dates).min()
    max_date = pd.to_datetime(missing_dates).max()

    logger.info(f"发现缺失PE_TTM数据 {len(missing_dates)} 条，日期范围: {min_date.strftime('%Y-%m-%d')} ~ {max_date.strftime('%Y-%m-%d')}")

    try:
        # 从tushare获取缺失日期的数据
        tushare_token = os.environ.get("TUSHARE_TOKEN")
        if not tushare_token:
            logger.warning("无法补充数据：未配置TUSHARE_TOKEN")
            return df

        import tushare as ts
        import akshare as ak

        ts.set_token(tushare_token)
        pro = ts.pro_api()

        start_str = min_date.strftime('%Y%m%d')
        end_str = max_date.strftime('%Y%m%d')

        # 获取PE_TTM和收盘价
        df_pe = pro.index_dailybasic(
            ts_code='000300.SH',
            start_date=start_str,
            end_date=end_str,
            fields='trade_date,pe_ttm'
        )

        df_close = pro.index_daily(
            ts_code='000300.SH',
            start_date=start_str,
            end_date=end_str,
            fields='trade_date,close'
        )

        df_pe = df_pe.merge(df_close, on='trade_date')
        df_pe['date'] = pd.to_datetime(df_pe['trade_date'])
        df_pe = df_pe.rename(columns={'close': 'csi300_close'})

        # 获取国债收益率
        df_bond_raw = ak.bond_gb_zh_sina(symbol="中国10年期国债")
        df_bond_raw['date'] = pd.to_datetime(df_bond_raw['date'])
        df_bond = df_bond_raw[['date', 'close']].rename(columns={'close': 'bond_yield'})

        # 合并
        df_supplement = df_pe.merge(df_bond, on='date', how='left')

        # 计算
        df_supplement['earnings_yield'] = 100 / df_supplement['pe_ttm']
        df_supplement['equity_premium'] = df_supplement['earnings_yield'] - df_supplement['bond_yield']

        # 用补充数据更新原数据
        for _, row in df_supplement.iterrows():
            date = row['date']
            mask = (pd.to_datetime(df['date']) == date) & df['pe_ttm'].isna()
            if mask.any():
                if 'csi300_close' in row and pd.notna(row['csi300_close']):
                    df.loc[mask, 'csi300_close'] = row['csi300_close']
                if pd.notna(row['pe_ttm']):
                    df.loc[mask, 'pe_ttm'] = row['pe_ttm']
                if 'bond_yield' in row and pd.notna(row['bond_yield']):
                    df.loc[mask, 'bond_yield'] = row['bond_yield']
                if 'earnings_yield' in row and pd.notna(row['earnings_yield']):
                    df.loc[mask, 'earnings_yield'] = row['earnings_yield']
                if 'equity_premium' in row and pd.notna(row['equity_premium']):
                    df.loc[mask, 'equity_premium'] = row['equity_premium']

        # 重新计算earnings_yield和equity_premium（如果有缺失）
        for idx in df[missing_mask].index:
            if pd.notna(df.loc[idx, 'pe_ttm']) and pd.notna(df.loc[idx, 'bond_yield']):
                df.loc[idx, 'earnings_yield'] = 100 / df.loc[idx, 'pe_ttm']
                df.loc[idx, 'equity_premium'] = df.loc[idx, 'earnings_yield'] - df.loc[idx, 'bond_yield']

        remaining_missing = df['pe_ttm'].isna().sum()
        logger.info(f"补充完成，剩余缺失: {remaining_missing} 条")

    except Exception as e:
        logger.error(f"补充数据失败: {e}")

    return df


def get_excel_output_path() -> Path:
    """获取输出Excel文件路径"""
    # 优先使用环境变量，否则使用默认路径
    env_path = os.environ.get("EQUITY_PREMIUM_OUTPUT_PATH")
    if env_path:
        return Path(env_path)

    # 默认路径：项目根目录 (skills/equity-risk-premium/ -> Equity Risk Premium/)
    current = Path(__file__).resolve()
    return current.parent.parent.parent / "equity_premium_enhanced.xlsx"


def save_to_excel(df, output_path: Path) -> bool:
    """
    保存数据到Excel文件（追加模式，保留原有数据）

    Args:
        df: pandas DataFrame 新数据
        output_path: 输出文件路径

    Returns:
        bool: 是否保存成功
    """
    if df.empty:
        logger.warning("数据为空，跳过保存")
        return False

    try:
        import pandas as pd

        # 准备新数据
        df_new = df.copy()

        # 列名映射（注意：csi300_close 和 csi300_point 只能选一个）
        # 优先使用 csi300_close
        if 'csi300_close' in df_new.columns and 'csi300_point' in df_new.columns:
            df_new = df_new.drop(columns=['csi300_point'])

        column_mapping = {
            'date': '日期',
            'csi300_close': '沪深300点位',
            'pe_ttm': 'PE_TTM',
            'bond_yield': '10年国债收益率',
            'earnings_yield': '盈利收益率',
            'equity_premium': '股权溢价指数'
        }

        # 重命名列
        available_cols = [c for c in column_mapping.keys() if c in df_new.columns]
        df_new = df_new[available_cols].rename(columns={
            k: v for k, v in column_mapping.items() if k in available_cols
        })

        # 格式化日期（英文日期转中文格式）
        if '日期' in df_new.columns:
            df_new['日期'] = pd.to_datetime(df_new['日期']).dt.strftime('%Y-%m-%d')

        # 确保目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 读取原有数据（如果存在）
        df_existing = pd.DataFrame()
        if output_path.exists():
            try:
                df_existing = pd.read_excel(output_path)
                # 统一日期格式为字符串
                if '日期' in df_existing.columns:
                    df_existing['日期'] = pd.to_datetime(df_existing['日期']).dt.strftime('%Y-%m-%d')
                logger.info(f"已读取原有数据: {len(df_existing)} 条")
            except Exception as e:
                logger.warning(f"读取原有Excel失败，将创建新文件: {e}")

        # 合并数据（去重）
        if not df_existing.empty and '日期' in df_existing.columns:
            # 清理原有数据中的重复日期
            df_existing = df_existing.drop_duplicates(subset=['日期'], keep='last')

            # 合并并去重
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            df_combined = df_combined.drop_duplicates(subset=['日期'], keep='last')
            # 按日期排序
            df_combined = df_combined.sort_values(by='日期', ascending=True)

            new_records = len(df_combined) - len(df_existing)
            logger.info(f"合并后共 {len(df_combined)} 条，新增 {new_records} 条")
            df_output = df_combined
        elif not df_new.empty:
            # 没有原有数据，直接使用新数据
            df_output = df_new.sort_values(by='日期', ascending=True)
            logger.info(f"新文件，共 {len(df_output)} 条")
        else:
            df_output = df_new

        # 删除不需要的列（原始股权溢价）
        cols_to_remove = ['原始股权溢价']
        df_output = df_output.drop(columns=[c for c in cols_to_remove if c in df_output.columns], errors='ignore')

        # 添加数据源列（默认空）
        if '数据源' not in df_output.columns:
            df_output['数据源'] = ''

        # 调整列顺序与飞书表格一致
        column_order = ['日期', '沪深300点位', 'PE_TTM', '10年国债收益率', '盈利收益率', '股权溢价指数', '数据源']
        df_output = df_output[[c for c in column_order if c in df_output.columns]]

        # 保存到Excel
        df_output.to_excel(output_path, index=False)

        logger.info(f"数据已保存到: {output_path}")
        return True

    except Exception as e:
        logger.error(f"保存Excel失败: {e}")
        return False


def load_full_history_for_shared_signal(output_path: Path):
    """
    从已保存的 Excel 回读完整历史数据，用于导出全量共享接口。
    """
    if not output_path.exists():
        return None

    try:
        import pandas as pd

        df = pd.read_excel(output_path)
        if df.empty:
            return None

        column_mapping = {
            '日期': 'date',
            '沪深300点位': 'csi300_close',
            'PE_TTM': 'pe_ttm',
            '10年国债收益率': 'bond_yield',
            '盈利收益率': 'earnings_yield',
            '股权溢价指数': 'equity_premium',
        }

        available_cols = [col for col in column_mapping.keys() if col in df.columns]
        if not available_cols:
            return None

        history_df = df[available_cols].rename(columns={col: column_mapping[col] for col in available_cols})
        history_df['date'] = pd.to_datetime(history_df['date'], errors='coerce')
        history_df = history_df.dropna(subset=['date']).sort_values('date')
        return history_df
    except Exception as e:
        logger.error(f"读取完整历史数据失败: {e}")
        return None


def sync_to_feishu_bitable(df, start_date: str = None, end_date: str = None) -> dict:
    """
    同步数据到飞书多维表格

    Args:
        df: pandas DataFrame
        start_date: 开始日期（可选，用于只同步新增数据）
        end_date: 结束日期

    Returns:
        dict: 同步结果
    """
    import pandas as pd

    # 检查配置
    required_env = [
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_APP_TOKEN",
        "FEISHU_TABLE_ID",
    ]
    missing = [k for k in required_env if not os.environ.get(k)]

    if missing:
        message = f"配置不完整，缺少: {', '.join(missing)}"
        logger.warning(f"飞书多维表格{message}，跳过同步")
        return {
            "success": False,
            "message": message,
            "synced": 0,
            "failed": 0,
            "total": 0,
            "errors": [],
        }

    try:
        client = FeishuBitableClient()

        # 只同步新数据（指定日期范围内的最新记录）
        if start_date and end_date:
            df_sync = df.copy()
            df_sync['date'] = pd.to_datetime(df_sync['date'])
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df_sync = df_sync[(df_sync['date'] >= start) & (df_sync['date'] <= end)]
        else:
            # 同步所有数据
            df_sync = df.tail(10)  # 默认同步最近10条

        if df_sync.empty:
            logger.info("没有需要同步的数据")
            return {"success": True, "message": "无新数据", "synced": 0}

        # 逐条写入
        synced_count = 0
        failed_count = 0
        failed_examples = []
        total_count = len(df_sync)
        for _, row in df_sync.iterrows():
            date_str = row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date'])

            result = client.add_record(
                date=date_str,
                csi300_close=float(row.get('csi300_close', 0) or 0),
                pe_ttm=float(row.get('pe_ttm', 0) or 0),
                bond_yield=float(row.get('bond_yield', 0) or 0),
                earnings_yield=float(row.get('earnings_yield', 0) or 0),
                equity_premium=float(row.get('equity_premium', 0) or 0),
                source="tushare+akshare"
            )

            if result.get("success"):
                synced_count += 1
            else:
                failed_count += 1
                error_msg = result.get('message') or result.get('error') or 'unknown error'
                logger.warning(f"同步失败: {date_str}, {error_msg}")
                if len(failed_examples) < 5:
                    failed_examples.append({"date": date_str, "error": error_msg})

        success = failed_count == 0 and synced_count > 0
        logger.info(f"飞书多维表格同步完成: 成功 {synced_count}/{total_count}, 失败 {failed_count}")
        return {
            "success": success,
            "message": "ok" if success else f"部分或全部失败: 成功 {synced_count}/{total_count}",
            "synced": synced_count,
            "failed": failed_count,
            "total": total_count,
            "errors": failed_examples,
        }

    except Exception as e:
        logger.error(f"飞书多维表格同步失败: {e}")
        return {
            "success": False,
            "message": str(e),
            "synced": 0,
            "failed": 0,
            "total": 0,
            "errors": [{"error": str(e)}],
        }


def format_output(df) -> dict:
    """格式化输出"""
    if df.empty:
        return {
            "success": False,
            "message": "无数据",
            "data": []
        }

    # 转换为字典列表
    records = []
    for _, row in df.iterrows():
        record = {
            "date": row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date']),
        }

        # 添加可选字段
        for field in ['csi300_pe_ttm', 'pe_ttm', 'csi300_close', 'bond_yield', 'earnings_yield', 'equity_premium']:
            if field in row and row[field] is not None:
                if 'pe' in field.lower():
                    record[field] = round(float(row[field]), 2)
                else:
                    record[field] = round(float(row[field]), 4)

        records.append(record)

    return {
        "success": True,
        "data": records,
        "source": "excel+tushare+akshare",
        "record_count": len(records)
    }


def run(args: str = "") -> dict:
    """
    执行股权溢价指数计算

    Args:
        args: 命令参数

    Returns:
        结果字典
    """
    # 解析参数
    start_date, end_date = parse_args(args)

    logger.info(f"参数解析: start_date={start_date}, end_date={end_date}")

    # 初始化数据源
    tushare_token = os.environ.get("TUSHARE_TOKEN")
    excel_path = os.environ.get("EQUITY_PREMIUM_EXCEL_PATH")

    if excel_path:
        from pathlib import Path
        excel_path = Path(excel_path)
    else:
        excel_path = None

    data_source = EquityPremiumData(
        tushare_token=tushare_token,
        excel_path=excel_path
    )

    # 获取数据
    try:
        df = data_source.get_data(start_date=start_date, end_date=end_date)
    except Exception as e:
        logger.error(f"获取数据失败: {e}")
        return {
            "success": False,
            "message": f"获取数据失败: {str(e)}",
            "data": []
        }

    # 补充缺失日期的PE_TTM等数据（如果有缺失）
    if not df.empty:
        import pandas as pd
        df = supplement_missing_data(df)

    # Step 1: 保存到本地Excel（双保险）
    excel_saved = False
    output_path = get_excel_output_path()
    shared_signal_saved = False
    shared_signal_path = get_shared_signal_path()
    if not df.empty:
        excel_saved = save_to_excel(df, output_path)
        shared_df = load_full_history_for_shared_signal(output_path) if excel_saved else df
        if shared_df is None or shared_df.empty:
            shared_df = df
        shared_signal_saved = export_shared_signal(shared_df, shared_signal_path)

    # 格式化输出
    result = format_output(df)

    # 添加本地保存状态
    result["excel_saved"] = excel_saved
    result["excel_path"] = str(output_path) if excel_saved else None
    result["shared_signal_saved"] = shared_signal_saved
    result["shared_signal_path"] = str(shared_signal_path) if shared_signal_saved else None

    # Step 2: 发送到飞书Webhook（可选）
    feishu_sent = False
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL")
    if webhook_url and result.get("success") and result.get("data"):
        feishu = FeishuWebhook(webhook_url)
        title = "股权溢价指数"
        if start_date and end_date:
            title = f"股权溢价指数 ({start_date} ~ {end_date})"
        elif end_date:
            title = f"股权溢价指数 ({end_date})"

        feishu_sent = feishu.send(result["data"], title)

    result["feishu_sent"] = feishu_sent

    # Step 3: 同步到飞书多维表格（可选）
    bitable_synced = False
    if excel_saved and not df.empty:
        import pandas as pd
        bitable_result = sync_to_feishu_bitable(df, start_date, end_date if end_date else None)
        bitable_synced = bitable_result.get("success", False)
        result["bitable_synced"] = bitable_synced
        result["bitable_count"] = bitable_result.get("synced", 0)
        result["bitable_failed"] = bitable_result.get("failed", 0)
        result["bitable_total"] = bitable_result.get("total", 0)
        result["bitable_message"] = bitable_result.get("message", "")
        result["bitable_errors"] = bitable_result.get("errors", [])

    # 输出JSON到控制台
    print(json.dumps(result, ensure_ascii=False, indent=2))

    return result


# CLI入口
if __name__ == "__main__":
    import sys
    args = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    run(args)

