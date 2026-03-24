#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
报告生成模块
生成 HTML 交互式报告
"""

import os
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import percentileofscore


def load_config():
    """加载配置文件"""
    config_path = Path(__file__).parent.parent / 'config.json'
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_ratio_chart(df, target, title, ma_window=30, recent_days=1000):
    """
    创建比价走势图 - 深色主题

    Args:
        df: 数据DataFrame
        target: 目标指数代码
        title: 图表标题
        ma_window: 移动平均窗口
        recent_days: 显示最近多少个交易日

    Returns:
        plotly Figure
    """
    ratio_col = f'{target}_ratio'
    ma_col = f'{target}_MA{ma_window}'

    # 获取最近N个交易日数据
    recent_df = df.tail(recent_days)

    fig = go.Figure()

    # 比价线
    fig.add_trace(go.Scatter(
        x=recent_df.index,
        y=recent_df[ratio_col],
        mode='lines',
        name=f'{target}/HS300 比价',
        line=dict(color='#fbbf24', width=2),
        hovertemplate='日期: %{x}<br>比价: %{y:.4f}<extra></extra>'
    ))

    # 移动平均线
    fig.add_trace(go.Scatter(
        x=recent_df.index,
        y=recent_df[ma_col],
        mode='lines',
        name=f'{ma_window}日均线',
        line=dict(color='#94a3b8', width=1.5, dash='dash'),
        hovertemplate='日期: %{x}<br>均线: %{y:.4f}<extra></extra>'
    ))

    # 添加历史分位区域（使用显示范围内的数据计算最高最低点）
    all_ratios = df[ratio_col].dropna()

    # 使用显示范围内的实际最高和最低点
    display_ratios = recent_df[ratio_col].dropna()
    p20 = display_ratios.min()  # 显示范围内的最低点
    p80 = display_ratios.max()  # 显示范围内的最高点

    # 20%分位线（绿色 - 最低点）
    fig.add_hline(y=p20, line_dash="dot", line_color="#10b981",
                  annotation_text="区间最低", annotation_position="right",
                  annotation=dict(font=dict(color="#10b981", size=11)))

    # 80%分位线（红色 - 最高点）
    fig.add_hline(y=p80, line_dash="dot", line_color="#f43f5e",
                  annotation_text="区间最高", annotation_position="right",
                  annotation=dict(font=dict(color="#f43f5e", size=11)))

    # 计算当前值的历史分位数
    current_value = df[ratio_col].iloc[-1]
    current_percentile = percentileofscore(all_ratios, current_value)

    # 根据分位数确定颜色
    if current_percentile < 40:
        percentile_color = "#10b981"  # 绿色 - 低估
    elif current_percentile < 60:
        percentile_color = "#0ea5e9"  # 蓝色 - 中性
    else:
        percentile_color = "#f43f5e"  # 红色 - 高估

    fig.update_layout(
        title=dict(text=title, x=0.5, font=dict(size=14, color='#f1f5f9')),
        xaxis_title='',
        yaxis_title='比价',
        hovermode='x unified',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            font=dict(color='#94a3b8', size=10)
        ),
        # 添加分位数显示（图表下方正中间）
        annotations=[
            dict(
                x=0.5, y=-0.15,
                xref='paper', yref='paper',
                text=f'<b>当前分位数：</b><span style="font-size:16px; color:{percentile_color}; font-weight:700">{current_percentile:.1f}%</span>',
                showarrow=False,
                font=dict(size=12, color='#94a3b8'),
                bgcolor='rgba(17, 24, 39, 0.85)',
                bordercolor=percentile_color,
                borderwidth=1,
                borderpad=10,
                xanchor='center',
                yanchor='top'
            )
        ],
        margin=dict(l=50, r=50, t=50, b=90),
        height=450,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(17, 24, 39, 0.5)',
        font=dict(color='#94a3b8'),
        xaxis=dict(
            gridcolor='rgba(255,255,255,0.05)',
            linecolor='rgba(255,255,255,0.1)',
            tickfont=dict(color='#64748b', size=10)
        ),
        yaxis=dict(
            gridcolor='rgba(255,255,255,0.05)',
            linecolor='rgba(255,255,255,0.1)',
            tickfont=dict(color='#64748b', size=10)
        )
    )

    return fig


def create_price_chart(df, indices_config, recent_days=1000):
    """
    创建价格走势图 - 深色主题

    Args:
        df: 数据DataFrame
        indices_config: 指数配置
        recent_days: 显示最近多少个交易日

    Returns:
        plotly Figure
    """
    recent_df = df.tail(recent_days)

    fig = go.Figure()

    # 深色主题配色
    colors = {
        'HS300': '#fbbf24',   # 金色 - 基准
        'ZZ500': '#10b981',   # 翠绿
        'ZZ1000': '#8b5cf6',  # 紫罗兰
        'ZZA500': '#f97316',  # 橙色
        'SHCI': '#64748b'     # 灰色
    }

    for code, info in indices_config.items():
        if code in recent_df.columns:
            fig.add_trace(go.Scatter(
                x=recent_df.index,
                y=recent_df[code],
                mode='lines',
                name=info['name'],
                line=dict(color=colors.get(code, '#94a3b8'), width=1.5),
                hovertemplate=f"{info['name']}<br>日期: %{{x}}<br>点位: %{{y:.2f}}<extra></extra>"
            ))

    fig.update_layout(
        title=dict(text=f'指数价格走势（近{recent_days}交易日）', x=0.5, font=dict(size=14, color='#f1f5f9')),
        xaxis_title='日期',
        yaxis_title='点位',
        hovermode='x unified',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            font=dict(color='#94a3b8', size=11)
        ),
        margin=dict(l=60, r=60, t=60, b=60),
        height=450,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(17, 24, 39, 0.5)',
        font=dict(color='#94a3b8'),
        xaxis=dict(
            gridcolor='rgba(255,255,255,0.05)',
            linecolor='rgba(255,255,255,0.1)',
            tickfont=dict(color='#64748b')
        ),
        yaxis=dict(
            gridcolor='rgba(255,255,255,0.05)',
            linecolor='rgba(255,255,255,0.1)',
            tickfont=dict(color='#64748b')
        )
    )

    return fig



def get_equity_premium_signal_path() -> Path:
    """获取 ERP 标准共享信号文件路径。"""
    env_path = os.environ.get('INDEX_COMPARE_ERP_SIGNAL_PATH')
    if env_path:
        return Path(env_path)

    project_root = Path(__file__).resolve().parents[5]
    return project_root / 'shared' / 'erp_signal.json'


def load_equity_premium_records() -> List[Dict[str, Any]]:
    """优先加载 ERP 标准共享接口，兼容旧 dashboard 数据文件。"""
    signal_path = get_equity_premium_signal_path()
    if signal_path.exists():
        try:
            with open(signal_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            if (
                isinstance(payload, dict)
                and payload.get('version') == '1.0'
                and payload.get('signal_type') == 'equity_risk_premium'
            ):
                records = payload.get('records', [])
                return records if isinstance(records, list) else []
        except Exception:
            return []

    legacy_env_path = os.environ.get('INDEX_COMPARE_ERP_JSON_PATH')
    if legacy_env_path:
        legacy_path = Path(legacy_env_path)
    else:
        project_root = Path(__file__).resolve().parents[5]
        legacy_path = project_root / 'Equity Risk Premium' / 'dashboard' / 'data' / 'equity_premium.json'

    if not legacy_path.exists():
        return []

    try:
        with open(legacy_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        records = payload.get('records', []) if isinstance(payload, dict) else []
        return records if isinstance(records, list) else []
    except Exception:
        return []


def create_equity_premium_chart(records, recent_days=1000):
    """
    创建股权溢价时序图（合并视图）
    """
    if not records:
        return None

    df = pd.DataFrame(records)
    required = {'date', 'equity_premium'}
    if not required.issubset(set(df.columns)):
        return None

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date')
    if df.empty:
        return None

    recent_df = df.tail(recent_days)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=recent_df['date'],
        y=recent_df['equity_premium'],
        mode='lines',
        name='股权溢价指数',
        line=dict(color='#3ec3ff', width=2.5),
        hovertemplate='日期: %{x}<br>股权溢价: %{y:.2f}%<extra></extra>'
    ))

    if 'earnings_yield' in recent_df.columns:
        fig.add_trace(go.Scatter(
            x=recent_df['date'],
            y=recent_df['earnings_yield'],
            mode='lines',
            name='盈利收益率',
            line=dict(color='#ffb85c', width=1.6),
            hovertemplate='日期: %{x}<br>盈利收益率: %{y:.2f}%<extra></extra>'
        ))

    if 'bond_yield' in recent_df.columns:
        fig.add_trace(go.Scatter(
            x=recent_df['date'],
            y=recent_df['bond_yield'],
            mode='lines',
            name='10年国债收益率',
            line=dict(color='#26c281', width=1.6),
            hovertemplate='日期: %{x}<br>10年国债收益率: %{y:.2f}%<extra></extra>'
        ))

    fig.add_hline(
        y=0,
        line_dash='dash',
        line_color='rgba(255,255,255,0.35)',
        annotation_text='0轴',
        annotation_position='right'
    )

    fig.update_layout(
        title=dict(text=f'股权溢价合并视图（近{recent_days}交易日）', x=0.5, font=dict(size=14, color='#f1f5f9')),
        xaxis_title='日期',
        yaxis_title='百分比(%)',
        hovermode='x unified',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            font=dict(color='#94a3b8', size=11)
        ),
        margin=dict(l=60, r=60, t=60, b=60),
        height=430,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(17, 24, 39, 0.5)',
        font=dict(color='#94a3b8'),
        xaxis=dict(
            gridcolor='rgba(255,255,255,0.05)',
            linecolor='rgba(255,255,255,0.1)',
            tickfont=dict(color='#64748b')
        ),
        yaxis=dict(
            gridcolor='rgba(255,255,255,0.05)',
            linecolor='rgba(255,255,255,0.1)',
            tickfont=dict(color='#64748b')
        )
    )

    return fig

def generate_html_report(df, conclusions, output_dir):
    """
    生成 HTML 报告

    Args:
        df: 处理后的数据DataFrame
        conclusions: 分析结论字典
        output_dir: 输出目录

    Returns:
        str: 报告文件路径
    """
    config = load_config()
    indices_config = config['indices']
    ma_window = config['analysis']['ma_window']
    recent_days = config['analysis']['recent_days']

    # 生成时间戳
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    latest_date = df.index[-1].strftime('%Y-%m-%d')

    # 创建价格走势图
    price_chart = create_price_chart(df, indices_config, recent_days)
    price_chart_html = price_chart.to_html(full_html=False, include_plotlyjs='cdn')

    # 加载并合并股权溢价图（来自 Equity Risk Premium）
    erp_records = load_equity_premium_records()
    erp_chart = create_equity_premium_chart(erp_records, recent_days)
    if erp_chart is not None:
        erp_chart_html = erp_chart.to_html(full_html=False, include_plotlyjs=False)
    else:
        erp_chart_html = '<div style="padding: 20px; color: #94a3b8;">未检测到 Equity Risk Premium 数据文件，跳过合并图表。</div>'

    # 创建比价走势图（分开存储，用于并排布局）
    ratio_charts_html = []
    for target in ['ZZ500', 'ZZ1000', 'ZZA500']:
        if f'{target}_ratio' in df.columns:
            name = indices_config[target]['name']
            chart = create_ratio_chart(df, target, f'{name} vs 沪深300', ma_window, recent_days)
            ratio_charts_html.append(chart.to_html(full_html=False, include_plotlyjs='cdn'))

    # 生成指标卡片HTML
    cards_html = generate_cards_html(conclusions, df)

    # 生成分析结论HTML
    analysis_html = generate_analysis_html(conclusions)

    # 组装完整HTML - 金融终端风格
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A股指数比价分析 | {report_date}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0a0e17;
            --bg-secondary: #111827;
            --bg-card: rgba(17, 24, 39, 0.8);
            --bg-glass: rgba(255, 255, 255, 0.03);
            --border-subtle: rgba(255, 255, 255, 0.06);
            --border-glow: rgba(251, 191, 36, 0.3);
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent-gold: #fbbf24;
            --accent-amber: #f59e0b;
            --accent-emerald: #10b981;
            --accent-rose: #f43f5e;
            --accent-sky: #0ea5e9;
            --accent-violet: #8b5cf6;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
            overflow-x: hidden;
        }}

        /* 背景纹理 */
        body::before {{
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background:
                radial-gradient(ellipse 80% 50% at 50% -20%, rgba(251, 191, 36, 0.08), transparent),
                radial-gradient(ellipse 60% 40% at 100% 100%, rgba(139, 92, 246, 0.05), transparent),
                linear-gradient(180deg, transparent 0%, rgba(0,0,0,0.3) 100%);
            pointer-events: none;
            z-index: -1;
        }}

        /* 网格背景 */
        body::after {{
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-image:
                linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
            background-size: 60px 60px;
            pointer-events: none;
            z-index: -1;
        }}

        .container {{
            max-width: 1600px;
            margin: 0 auto;
            padding: 40px 24px;
        }}

        /* 顶部导航栏 */
        .top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 0;
            margin-bottom: 32px;
            border-bottom: 1px solid var(--border-subtle);
        }}

        .logo {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .logo-icon {{
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, var(--accent-gold), var(--accent-amber));
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            font-weight: 700;
            color: var(--bg-primary);
            box-shadow: 0 4px 20px rgba(251, 191, 36, 0.3);
        }}

        .logo-text {{
            font-size: 20px;
            font-weight: 600;
            letter-spacing: -0.5px;
        }}

        .logo-text span {{
            color: var(--accent-gold);
        }}

        .meta-info {{
            display: flex;
            gap: 24px;
            font-size: 13px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }}

        .meta-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .meta-dot {{
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--accent-emerald);
            animation: pulse 2s ease-in-out infinite;
        }}

        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}

        /* Hero 区域 */
        .hero {{
            text-align: center;
            padding: 60px 0 80px;
            position: relative;
        }}

        .hero h1 {{
            font-size: 48px;
            font-weight: 700;
            letter-spacing: -1px;
            margin-bottom: 16px;
            background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent-gold) 50%, var(--text-primary) 100%);
            background-size: 200% auto;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            animation: shimmer 3s linear infinite;
        }}

        @keyframes shimmer {{
            0% {{ background-position: 200% center; }}
            100% {{ background-position: -200% center; }}
        }}

        .hero-subtitle {{
            font-size: 16px;
            color: var(--text-secondary);
            max-width: 600px;
            margin: 0 auto;
        }}

        /* 主要指标网格 */
        .metrics-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr 1fr;
            gap: 20px;
            margin-bottom: 40px;
        }}

        .metric-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: 16px;
            padding: 28px;
            position: relative;
            overflow: hidden;
            backdrop-filter: blur(10px);
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        }}

        .metric-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--accent-gold), transparent);
            opacity: 0;
            transition: opacity 0.4s ease;
        }}

        .metric-card:hover {{
            transform: translateY(-4px);
            border-color: var(--border-glow);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3), 0 0 60px rgba(251, 191, 36, 0.1);
        }}

        .metric-card:hover::before {{
            opacity: 1;
        }}

        .metric-card.benchmark {{
            background: linear-gradient(135deg, rgba(251, 191, 36, 0.1), rgba(245, 158, 11, 0.05));
            border-color: rgba(251, 191, 36, 0.2);
        }}

        .metric-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 20px;
        }}

        .metric-name {{
            font-size: 14px;
            font-weight: 500;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .metric-badge {{
            font-size: 11px;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 20px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .badge-benchmark {{
            background: rgba(251, 191, 36, 0.2);
            color: var(--accent-gold);
        }}

        .badge-high {{
            background: rgba(244, 63, 94, 0.2);
            color: var(--accent-rose);
        }}

        .badge-low {{
            background: rgba(16, 185, 129, 0.2);
            color: var(--accent-emerald);
        }}

        .badge-neutral {{
            background: rgba(14, 165, 233, 0.2);
            color: var(--accent-sky);
        }}

        .metric-value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 36px;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: 8px;
            letter-spacing: -1px;
        }}

        .metric-label {{
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 24px;
        }}

        .metric-stats {{
            display: flex;
            flex-direction: column;
            gap: 12px;
            padding-top: 20px;
            border-top: 1px solid var(--border-subtle);
        }}

        .stat-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .stat-label {{
            font-size: 13px;
            color: var(--text-muted);
        }}

        .stat-value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 14px;
            font-weight: 600;
            padding: 4px 12px;
            border-radius: 6px;
            background: var(--bg-glass);
        }}

        .stat-value.positive {{
            color: var(--accent-emerald);
            background: rgba(16, 185, 129, 0.1);
        }}

        .stat-value.negative {{
            color: var(--accent-rose);
            background: rgba(244, 63, 94, 0.1);
        }}

        .stat-value.neutral {{
            color: var(--accent-sky);
            background: rgba(14, 165, 233, 0.1);
        }}

        .stat-value.warning {{
            color: var(--accent-amber);
            background: rgba(245, 158, 11, 0.1);
        }}

        /* 图表区域 */
        .charts-section {{
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: 20px;
            padding: 32px;
            margin-bottom: 40px;
            backdrop-filter: blur(10px);
        }}

        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 28px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border-subtle);
        }}

        .section-title {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .section-icon {{
            width: 36px;
            height: 36px;
            background: var(--bg-glass);
            border: 1px solid var(--border-subtle);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
        }}

        .section-title h2 {{
            font-size: 20px;
            font-weight: 600;
            letter-spacing: -0.3px;
        }}

        .chart-wrapper {{
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}

        .chart-wrapper:last-child {{
            margin-bottom: 0;
        }}

        /* 三列比价图布局 */
        .ratio-charts-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 20px;
        }}

        .ratio-chart-wrapper {{
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 16px;
        }}

        @media (max-width: 1400px) {{
            .ratio-charts-grid {{
                grid-template-columns: 1fr 1fr;
            }}
        }}

        @media (max-width: 1200px) {{
            .ratio-charts-grid {{
                grid-template-columns: 1fr;
            }}
            .analysis-section {{
                grid-template-columns: 1fr 1fr;
            }}
        }}

        /* 分析区域 */
        .analysis-section {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 24px;
            margin-bottom: 40px;
        }}

        .analysis-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: 20px;
            padding: 32px;
            backdrop-filter: blur(10px);
            position: relative;
            overflow: hidden;
        }}

        .analysis-card::after {{
            content: '';
            position: absolute;
            top: -50%;
            right: -50%;
            width: 100%;
            height: 100%;
            background: radial-gradient(circle, rgba(251, 191, 36, 0.03) 0%, transparent 70%);
            pointer-events: none;
        }}

        .analysis-header {{
            display: flex;
            align-items: center;
            gap: 16px;
            margin-bottom: 24px;
        }}

        .analysis-icon {{
            width: 48px;
            height: 48px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
        }}

        .analysis-icon.zz500 {{
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.05));
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .analysis-icon.zz1000 {{
            background: linear-gradient(135deg, rgba(139, 92, 246, 0.2), rgba(139, 92, 246, 0.05));
            border: 1px solid rgba(139, 92, 246, 0.3);
        }}

        .analysis-icon.zza500 {{
            background: linear-gradient(135deg, rgba(249, 115, 22, 0.2), rgba(249, 115, 22, 0.05));
            border: 1px solid rgba(249, 115, 22, 0.3);
        }}

        .analysis-title {{
            font-size: 18px;
            font-weight: 600;
        }}

        .analysis-subtitle {{
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 2px;
        }}

        .analysis-body {{
            position: relative;
            z-index: 1;
        }}

        .analysis-item {{
            padding: 16px 0;
            border-bottom: 1px solid var(--border-subtle);
        }}

        .analysis-item:last-child {{
            border-bottom: none;
            padding-bottom: 0;
        }}

        .analysis-item-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}

        .analysis-item-title {{
            font-size: 14px;
            font-weight: 600;
            color: var(--text-secondary);
        }}

        .analysis-item-value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 14px;
            font-weight: 600;
        }}

        .analysis-item-desc {{
            font-size: 13px;
            color: var(--text-muted);
            line-height: 1.7;
        }}

        .recommendation-box {{
            margin-top: 24px;
            padding: 20px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            gap: 16px;
        }}

        .recommendation-box.overweight {{
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(16, 185, 129, 0.05));
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .recommendation-box.underweight {{
            background: linear-gradient(135deg, rgba(244, 63, 94, 0.15), rgba(244, 63, 94, 0.05));
            border: 1px solid rgba(244, 63, 94, 0.3);
        }}

        .recommendation-box.neutral {{
            background: linear-gradient(135deg, rgba(14, 165, 233, 0.15), rgba(14, 165, 233, 0.05));
            border: 1px solid rgba(14, 165, 233, 0.3);
        }}

        .recommendation-icon {{
            width: 44px;
            height: 44px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            flex-shrink: 0;
        }}

        .recommendation-box.overweight .recommendation-icon {{
            background: rgba(16, 185, 129, 0.2);
            color: var(--accent-emerald);
        }}

        .recommendation-box.underweight .recommendation-icon {{
            background: rgba(244, 63, 94, 0.2);
            color: var(--accent-rose);
        }}

        .recommendation-box.neutral .recommendation-icon {{
            background: rgba(14, 165, 233, 0.2);
            color: var(--accent-sky);
        }}

        .recommendation-content {{
            flex: 1;
        }}

        .recommendation-action {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 4px;
        }}

        .recommendation-score {{
            font-size: 12px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }}

        /* 页脚 */
        .footer {{
            text-align: center;
            padding: 40px 0;
            border-top: 1px solid var(--border-subtle);
            margin-top: 40px;
        }}

        .footer-text {{
            font-size: 13px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }}

        .footer-brand {{
            margin-top: 8px;
            font-size: 11px;
            color: var(--text-muted);
            opacity: 0.7;
        }}

        /* 响应式 */
        @media (max-width: 1400px) {{
            .metrics-grid {{
                grid-template-columns: 1fr 1fr;
            }}
        }}

        @media (max-width: 900px) {{
            .metrics-grid {{
                grid-template-columns: 1fr;
            }}
            .analysis-section {{
                grid-template-columns: 1fr;
            }}
            .ratio-charts-grid {{
                grid-template-columns: 1fr;
            }}
            .hero h1 {{
                font-size: 32px;
            }}
            .top-bar {{
                flex-direction: column;
                gap: 16px;
                text-align: center;
            }}
            .meta-info {{
                flex-wrap: wrap;
                justify-content: center;
            }}
        }}

        /* 入场动画 */
        @keyframes fadeInUp {{
            from {{
                opacity: 0;
                transform: translateY(20px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}

        .metric-card, .charts-section, .analysis-card {{
            animation: fadeInUp 0.6s ease-out backwards;
        }}

        .metric-card:nth-child(1) {{ animation-delay: 0.1s; }}
        .metric-card:nth-child(2) {{ animation-delay: 0.2s; }}
        .metric-card:nth-child(3) {{ animation-delay: 0.3s; }}
        .metric-card:nth-child(4) {{ animation-delay: 0.4s; }}
        .charts-section {{ animation-delay: 0.5s; }}
        .analysis-card:nth-child(1) {{ animation-delay: 0.6s; }}
        .analysis-card:nth-child(2) {{ animation-delay: 0.7s; }}
        .analysis-card:nth-child(3) {{ animation-delay: 0.8s; }}
    </style>
</head>
<body>
    <div class="container">
        <!-- 顶部栏 -->
        <div class="top-bar">
            <div class="logo">
                <div class="logo-icon">IC</div>
                <div class="logo-text">Index<span>Compare</span></div>
            </div>
            <div class="meta-info">
                <div class="meta-item">
                    <span class="meta-dot"></span>
                    <span>LIVE</span>
                </div>
                <div class="meta-item">数据截止 {latest_date}</div>
                <div class="meta-item">生成于 {report_date}</div>
            </div>
        </div>

        <!-- Hero -->
        <div class="hero">
            <h1>A股指数比价分析</h1>
            <p class="hero-subtitle">基于沪深300基准，分析中证500/1000相对估值水平与趋势，提供量化配置建议</p>
        </div>

        <!-- 指标卡片 -->
        {cards_html}

        <!-- 图表区域 -->
        <div class="charts-section">
            <div class="section-header">
                <div class="section-title">
                    <div class="section-icon">📈</div>
                    <h2>价格走势</h2>
                </div>
            </div>
            <div class="chart-wrapper">{price_chart_html}</div>
        </div>

        <!-- 跨系统合并图表区域 -->
        <div class="charts-section">
            <div class="section-header">
                <div class="section-title">
                    <div class="section-icon">🔗</div>
                    <h2>股权溢价合并视图（来自 Equity Risk Premium）</h2>
                </div>
            </div>
            <div class="chart-wrapper">{erp_chart_html}</div>
        </div>

        <!-- 比价图并排布局 -->
        <div class="charts-section">
            <div class="section-header">
                <div class="section-title">
                    <div class="section-icon">⚖️</div>
                    <h2>比价走势对比</h2>
                </div>
            </div>
            <div class="ratio-charts-grid">
                {''.join([f'<div class="ratio-chart-wrapper">{chart}</div>' for chart in ratio_charts_html])}
            </div>
        </div>

        <!-- 分析区域 -->
        {analysis_html}

        <!-- 页脚 -->
        <div class="footer">
            <div class="footer-text">INDEX COMPARE ANALYSIS REPORT</div>
            <div class="footer-brand">Powered by Claude Code</div>
        </div>
    </div>
</body>
</html>
"""

    # 确保输出目录存在
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 保存报告
    report_file = output_path / f'index_compare_{timestamp}.html'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return str(report_file)


def generate_cards_html(conclusions, df):
    """生成指标卡片HTML - 金融终端风格"""
    cards = []

    # 沪深300卡片（基准）
    hs300_latest = df['HS300'].iloc[-1]
    cards.append(f"""
        <div class="metric-card benchmark">
            <div class="metric-header">
                <div class="metric-name">沪深300</div>
                <span class="metric-badge badge-benchmark">基准</span>
            </div>
            <div class="metric-value">{hs300_latest:,.2f}</div>
            <div class="metric-label">最新收盘点位</div>
            <div class="metric-stats">
                <div class="stat-row">
                    <span class="stat-label">角色定位</span>
                    <span class="stat-value neutral">比价基准</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">代表市场</span>
                    <span class="stat-value">大盘蓝筹</span>
                </div>
            </div>
        </div>
    """)

    # 目标指数卡片
    for code, data in conclusions.items():
        percentile = data['percentile']['value']
        deviation = data['deviation']['value']
        trend_changes = data['trend']['changes']

        # 确定分位标签
        if percentile < 40:
            p_badge = 'badge-low'
            p_class = 'positive'
        elif percentile > 60:
            p_badge = 'badge-high'
            p_class = 'negative'
        else:
            p_badge = 'badge-neutral'
            p_class = 'neutral'

        # 确定偏离标签
        if deviation < -5:
            d_class = 'positive'
        elif deviation > 5:
            d_class = 'negative'
        else:
            d_class = 'neutral'

        # 趋势显示
        trend_5d = trend_changes['5d']
        if trend_5d > 0:
            trend_class = 'positive'
            trend_arrow = '↑'
        elif trend_5d < 0:
            trend_class = 'negative'
            trend_arrow = '↓'
        else:
            trend_class = 'neutral'
            trend_arrow = '→'

        cards.append(f"""
            <div class="metric-card">
                <div class="metric-header">
                    <div class="metric-name">{data['name']}</div>
                    <span class="metric-badge {p_badge}">{data['percentile']['status']}</span>
                </div>
                <div class="metric-value">{data['current_ratio']:.4f}</div>
                <div class="metric-label">相对沪深300比价</div>
                <div class="metric-stats">
                    <div class="stat-row">
                        <span class="stat-label">历史分位</span>
                        <span class="stat-value {p_class}">{percentile:.1f}%</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">均线偏离</span>
                        <span class="stat-value {d_class}">{deviation:+.2f}%</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">5日变化</span>
                        <span class="stat-value {trend_class}">{trend_arrow} {trend_5d:+.2f}%</span>
                    </div>
                </div>
            </div>
        """)

    return f'<div class="metrics-grid">{"".join(cards)}</div>'


def generate_analysis_html(conclusions):
    """生成分析结论HTML - 金融终端风格"""
    blocks = []

    icon_map = {
        'ZZ500': ('zz500', '500'),
        'ZZ1000': ('zz1000', '1000'),
        'ZZA500': ('zza500', 'A500')
    }

    for code, data in conclusions.items():
        rec = data['recommendation']
        icon_class, icon_text = icon_map.get(code, ('', ''))

        # 确定建议类型
        if rec['score'] > 0.5:
            rec_class = 'overweight'
            rec_icon = '↑'
        elif rec['score'] < -0.5:
            rec_class = 'underweight'
            rec_icon = '↓'
        else:
            rec_class = 'neutral'
            rec_icon = '='

        # 分位数值颜色
        p_value = data['percentile']['value']
        if p_value < 40:
            p_color = 'color: var(--accent-emerald);'
        elif p_value > 60:
            p_color = 'color: var(--accent-rose);'
        else:
            p_color = 'color: var(--accent-sky);'

        # 偏离度颜色
        d_value = data['deviation']['value']
        if d_value < -5:
            d_color = 'color: var(--accent-emerald);'
        elif d_value > 5:
            d_color = 'color: var(--accent-rose);'
        else:
            d_color = 'color: var(--accent-sky);'

        blocks.append(f"""
        <div class="analysis-card">
            <div class="analysis-header">
                <div class="analysis-icon {icon_class}">{icon_text}</div>
                <div>
                    <div class="analysis-title">{data['name']} 分析</div>
                    <div class="analysis-subtitle">vs 沪深300 比价</div>
                </div>
            </div>
            <div class="analysis-body">
                <div class="analysis-item">
                    <div class="analysis-item-header">
                        <span class="analysis-item-title">历史分位</span>
                        <span class="analysis-item-value" style="{p_color}">{data['percentile']['value']:.1f}% ({data['percentile']['status']})</span>
                    </div>
                    <div class="analysis-item-desc">{data['percentile']['description']}</div>
                </div>
                <div class="analysis-item">
                    <div class="analysis-item-header">
                        <span class="analysis-item-title">趋势判断</span>
                        <span class="analysis-item-value">{data['trend']['status']}</span>
                    </div>
                    <div class="analysis-item-desc">
                        {data['trend']['description']}
                        <br>
                        <span style="font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted);">
                            5D: {data['trend']['changes']['5d']:+.2f}% |
                            10D: {data['trend']['changes']['10d']:+.2f}% |
                            20D: {data['trend']['changes']['20d']:+.2f}%
                        </span>
                    </div>
                </div>
                <div class="analysis-item">
                    <div class="analysis-item-header">
                        <span class="analysis-item-title">均值回归</span>
                        <span class="analysis-item-value" style="{d_color}">{data['deviation']['value']:+.2f}% ({data['deviation']['status']})</span>
                    </div>
                    <div class="analysis-item-desc">{data['deviation']['description']}</div>
                </div>
                <div class="recommendation-box {rec_class}">
                    <div class="recommendation-icon">{rec_icon}</div>
                    <div class="recommendation-content">
                        <div class="recommendation-action">配置建议：{rec['action']}</div>
                        <div class="recommendation-score">综合得分: {rec['score']}</div>
                    </div>
                </div>
            </div>
        </div>
        """)

    return f'<div class="analysis-section">{"".join(blocks)}</div>'


def generate_report(data_path, conclusions_path, output_dir):
    """
    生成完整报告

    Args:
        data_path: 处理后数据文件路径
        conclusions_path: 分析结论文件路径
        output_dir: 输出目录
    """
    print("=" * 50)
    print("       报告生成")
    print("=" * 50)

    # 读取数据
    print(f"\n读取数据: {data_path}")
    df = pd.read_csv(data_path, index_col=0, parse_dates=True)

    print(f"读取分析结论: {conclusions_path}")
    with open(conclusions_path, 'r', encoding='utf-8') as f:
        conclusions = json.load(f)

    # 生成报告
    print("\n生成 HTML 报告...")
    report_file = generate_html_report(df, conclusions, output_dir)

    print(f"\n[OK] 报告已生成: {report_file}")

    return report_file


def main():
    parser = argparse.ArgumentParser(description='生成 HTML 报告')
    parser.add_argument('--data', '-d',
                        default='data/processed_data.csv',
                        help='处理后数据文件路径')
    parser.add_argument('--conclusions', '-c',
                        default='data/conclusions.json',
                        help='分析结论文件路径')
    parser.add_argument('--output', '-o',
                        default='reports',
                        help='输出目录 (默认: reports)')

    args = parser.parse_args()

    # 切换到 skill 目录
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)

    generate_report(args.data, args.conclusions, args.output)


if __name__ == '__main__':
    main()



