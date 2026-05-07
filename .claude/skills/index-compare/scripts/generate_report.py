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


def create_ratio_chart(df, target, title, ma_window=30, recent_days=1000, light_theme=False, show_full_history=False):
    """
    创建比价走势图 - 深色主题

    Args:
        df: 数据DataFrame
        target: 目标指数代码
        title: 图表标题
        ma_window: 移动平均窗口
        recent_days: 显示最近多少个交易日
        show_full_history: 是否显示全历史

    Returns:
        plotly Figure
    """
    ratio_col = f'{target}_ratio'
    ma_col = f'{target}_MA{ma_window}'

    chart_df = df.copy()
    if target == 'ZZA500' and target in chart_df.columns:
        target_series = chart_df[target].dropna()
        if not target_series.empty:
            changes = target_series.ne(target_series.shift())
            change_points = target_series.index[changes]
            if len(change_points) > 1:
                chart_df = chart_df.loc[change_points[1]:].copy()

    # 获取显示范围数据
    recent_df = chart_df.copy() if show_full_history else chart_df.tail(recent_days)

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

    recent_ma120 = chart_df[ratio_col].rolling(window=120).mean().loc[recent_df.index]
    fig.add_trace(go.Scatter(
        x=recent_df.index,
        y=recent_ma120,
        mode='lines',
        name='120日均线',
        line=dict(color='#60a5fa', width=1.5, dash='dot'),
        hovertemplate='日期: %{x}<br>120日均线: %{y:.4f}<extra></extra>'
    ))

    # 添加历史分位区域（使用显示范围内的数据计算最高最低点）
    all_ratios = chart_df[ratio_col].dropna()

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
    current_value = chart_df[ratio_col].dropna().iloc[-1]
    current_percentile = percentileofscore(all_ratios, current_value)

    # 根据分位数确定颜色
    if current_percentile < 40:
        percentile_color = "#10b981"  # 绿色 - 低估
    elif current_percentile < 60:
        percentile_color = "#0ea5e9"  # 蓝色 - 中性
    else:
        percentile_color = "#f43f5e"  # 红色 - 高估

    title_color = '#334155' if light_theme else '#f1f5f9'
    legend_color = '#475569' if light_theme else '#94a3b8'
    tick_color = '#64748b'
    x_grid = 'rgba(148,163,184,0.18)' if light_theme else 'rgba(255,255,255,0.05)'
    x_line = 'rgba(148,163,184,0.35)' if light_theme else 'rgba(255,255,255,0.1)'
    paper_bg = '#eef4ff' if light_theme else 'rgba(0,0,0,0)'
    plot_bg = '#ffffff' if light_theme else 'rgba(17, 24, 39, 0.5)'
    annotation_bg = '#ffffff' if light_theme else 'rgba(17, 24, 39, 0.85)'

    fig.update_layout(
        title=dict(
            text=title,
            x=0.5,
            y=0.98,
            xanchor='center',
            yanchor='top',
            pad=dict(b=24),
            font=dict(size=14, color=title_color)
        ),
        xaxis_title='',
        yaxis_title='比价',
        hovermode='x unified',
        dragmode='pan',
        uirevision=f'ratio-chart-{target}',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.10,
            xanchor='center',
            x=0.5,
            font=dict(color=legend_color, size=9),
            itemwidth=44
        ),
        margin=dict(l=50, r=50, t=108, b=90),
        height=450,
        paper_bgcolor=paper_bg,
        plot_bgcolor=plot_bg,
        font=dict(color=legend_color),
        xaxis=dict(
            gridcolor=x_grid,
            linecolor=x_line,
            tickfont=dict(color=tick_color, size=10),
            rangeslider=dict(
                visible=True,
                thickness=0.10,
                bgcolor='rgba(191,219,254,0.18)' if light_theme else 'rgba(30,41,59,0.45)',
                bordercolor=x_line,
                borderwidth=1
            )
        ),
        yaxis=dict(
            gridcolor=x_grid,
            linecolor=x_line,
            tickfont=dict(color=tick_color, size=10)
        )
    )

    return fig


def create_price_chart(df, indices_config, recent_days=1000, light_theme=False):
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
            series = pd.to_numeric(recent_df[code], errors='coerce').copy()

            # 创业板指数 历史起始阶段存在被固定首值占住的平线，图表中直接隐藏该段。
            if code == 'ZZA500':
                valid = series.dropna()
                if not valid.empty:
                    first_value = valid.iloc[0]
                    changed_mask = (valid - first_value).abs() > 1e-9
                    if changed_mask.any():
                        first_change_label = changed_mask[changed_mask].index[0]
                        series.loc[series.index < first_change_label] = pd.NA

            fig.add_trace(go.Scatter(
                x=recent_df.index,
                y=series,
                mode='lines',
                name=info['name'],
                line=dict(color=colors.get(code, '#94a3b8'), width=1.5),
                hovertemplate=f"{info['name']}<br>日期: %{{x}}<br>点位: %{{y:.2f}}<extra></extra>"
            ))

    title_color = '#334155' if light_theme else '#f1f5f9'
    legend_color = '#475569' if light_theme else '#94a3b8'
    tick_color = '#64748b'
    x_grid = 'rgba(148,163,184,0.18)' if light_theme else 'rgba(255,255,255,0.05)'
    x_line = 'rgba(148,163,184,0.35)' if light_theme else 'rgba(255,255,255,0.1)'
    paper_bg = '#eef4ff' if light_theme else 'rgba(0,0,0,0)'
    plot_bg = '#ffffff' if light_theme else 'rgba(17, 24, 39, 0.5)'

    fig.update_layout(
        title=dict(text=f'指数价格走势（近{recent_days}交易日）', x=0.5, font=dict(size=14, color=title_color)),
        xaxis_title='日期',
        yaxis_title='点位',
        hovermode='x unified',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            font=dict(color=legend_color, size=11)
        ),
        margin=dict(l=60, r=60, t=60, b=60),
        height=450,
        paper_bgcolor=paper_bg,
        plot_bgcolor=plot_bg,
        font=dict(color=legend_color),
        xaxis=dict(
            gridcolor=x_grid,
            linecolor=x_line,
            tickfont=dict(color=tick_color)
        ),
        yaxis=dict(
            gridcolor=x_grid,
            linecolor=x_line,
            tickfont=dict(color=tick_color)
        )
    )

    return fig



def get_merged_signal_path() -> Path:
    """获取统一 merged signal 文件路径。"""
    env_path = os.environ.get('INDEX_COMPARE_MERGED_SIGNAL_PATH')
    if env_path:
        return Path(env_path)

    project_root = Path(__file__).resolve().parents[5]
    return project_root / 'shared' / 'merged_signal.json'


def get_equity_premium_signal_path() -> Path:
    """获取 ERP 标准共享信号文件路径。"""
    env_path = os.environ.get('INDEX_COMPARE_ERP_SIGNAL_PATH')
    if env_path:
        return Path(env_path)

    project_root = Path(__file__).resolve().parents[5]
    return project_root / 'shared' / 'erp_signal.json'


def load_equity_premium_records() -> List[Dict[str, Any]]:
    """优先加载 merged signal，其次 ERP signal，最后兼容旧 dashboard 文件。"""
    merged_path = get_merged_signal_path()
    if merged_path.exists():
        try:
            with open(merged_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            if (
                isinstance(payload, dict)
                and payload.get('version') == '1.0'
                and payload.get('signal_type') == 'erp_relative_merged'
            ):
                components = payload.get('components', {})
                erp_component = components.get('erp', {}) if isinstance(components, dict) else {}
                records = erp_component.get('records', [])
                return records if isinstance(records, list) else []
        except Exception:
            return []

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


def create_macro_overview_chart(erp_records, index_df, recent_days=1000, experimental=False):
    """
    创建宏观总览图：股权溢价指数与沪深300双轴同屏。
    """
    if not erp_records:
        return None

    erp_df = pd.DataFrame(erp_records)
    required = {'date', 'equity_premium'}
    if not required.issubset(set(erp_df.columns)):
        return None

    erp_df['date'] = pd.to_datetime(erp_df['date'], errors='coerce')
    erp_df = erp_df.dropna(subset=['date']).sort_values('date')
    if erp_df.empty:
        return None

    if 'csi300_close' in erp_df.columns:
        merged_df = erp_df[['date', 'equity_premium', 'csi300_close']].dropna(subset=['csi300_close']).copy()
        merged_df = merged_df.rename(columns={'csi300_close': 'HS300'})
    elif not index_df.empty and 'HS300' in index_df.columns:
        hs300_df = index_df.reset_index().rename(columns={index_df.index.name or 'index': 'date'})
        hs300_df['date'] = pd.to_datetime(hs300_df['date'], errors='coerce')
        hs300_df = hs300_df[['date', 'HS300']].dropna(subset=['date']).sort_values('date')
        merged_df = pd.merge(erp_df[['date', 'equity_premium']], hs300_df, on='date', how='inner')
    else:
        return None

    if merged_df.empty:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=merged_df['date'],
            y=merged_df['equity_premium'],
            mode='lines',
            name='股权溢价指数',
            line=dict(color='#3ec3ff', width=2.8),
            fill='tozeroy',
            fillcolor='rgba(62, 195, 255, 0.10)',
            hovertemplate='日期: %{x}<br>股权溢价: %{y:.2f}%<extra></extra>',
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=merged_df['date'],
            y=merged_df['HS300'],
            mode='lines',
            name='沪深300',
            line=dict(color='#fbbf24', width=2.2),
            hovertemplate='日期: %{x}<br>沪深300: %{y:.2f}<extra></extra>',
        ),
        secondary_y=True,
    )

    latest_erp = merged_df['equity_premium'].iloc[-1]
    latest_hs300 = merged_df['HS300'].iloc[-1]
    first_date = merged_df['date'].iloc[0]
    last_date = merged_df['date'].iloc[-1]

    lab_annotations = [
        dict(
            x=0.01,
            y=1.12,
            xref='paper',
            yref='paper',
            text=(
                f'最新股权溢价 <b style="color:#3ec3ff;">{latest_erp:.2f}%</b>'
                f' &nbsp;&nbsp;|&nbsp;&nbsp; 最新沪深300 <b style="color:#fbbf24;">{latest_hs300:,.2f}</b>'
            ),
            showarrow=False,
            xanchor='left',
            font=dict(size=12, color='#cbd5e1'),
        )
    ]

    if experimental:
        lab_annotations.append(
            dict(
                x=0.99,
                y=1.12,
                xref='paper',
                yref='paper',
                text='实验模式：框选缩放 / 滚轮缩放 / 底部滑块定位 / 双击恢复全历史',
                showarrow=False,
                xanchor='right',
                font=dict(size=11, color='#94a3b8'),
            )
        )

    fig.update_layout(
        title=dict(
            text='股权溢价指数',
            x=0.5,
            font=dict(size=15, color='#f1f5f9'),
        ),
        dragmode='zoom' if experimental else 'pan',
        hovermode='x unified',
        hoverdistance=30,
        uirevision='macro-overview-lab' if experimental else None,
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            font=dict(color='#94a3b8', size=11),
        ),
        margin=dict(l=60, r=70, t=78, b=85 if experimental else 65),
        height=560 if experimental else 480,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(17, 24, 39, 0.55)',
        font=dict(color='#94a3b8'),
        annotations=lab_annotations,
        xaxis=dict(
            title='日期',
            gridcolor='rgba(255,255,255,0.05)',
            linecolor='rgba(255,255,255,0.1)',
            tickfont=dict(color='#64748b'),
            range=[first_date, last_date],
            showspikes=experimental,
            spikemode='across',
            spikesnap='cursor',
            spikecolor='rgba(255,255,255,0.28)',
            spikethickness=1,
            rangeslider=dict(
                visible=experimental,
                thickness=0.14,
                bgcolor='rgba(255,255,255,0.04)',
                bordercolor='rgba(255,255,255,0.08)',
                borderwidth=1,
            ),
            rangeselector=dict(
                visible=experimental,
                bgcolor='rgba(17,24,39,0.88)',
                activecolor='rgba(62,195,255,0.28)',
                bordercolor='rgba(255,255,255,0.08)',
                font=dict(color='#cbd5e1', size=11),
                buttons=[
                    dict(count=6, label='6M', step='month', stepmode='backward'),
                    dict(count=1, label='1Y', step='year', stepmode='backward'),
                    dict(count=3, label='3Y', step='year', stepmode='backward'),
                    dict(count=5, label='5Y', step='year', stepmode='backward'),
                    dict(count=10, label='10Y', step='year', stepmode='backward'),
                    dict(step='all', label='ALL'),
                ],
            ),
        ),
    )

    fig.update_yaxes(
        title_text='股权溢价(%)',
        secondary_y=False,
        gridcolor='rgba(62,195,255,0.10)',
        tickfont=dict(color='#7dd3fc'),
        title_font=dict(color='#7dd3fc'),
        zerolinecolor='rgba(255,255,255,0.14)',
    )
    fig.update_yaxes(
        title_text='沪深300点位',
        secondary_y=True,
        gridcolor='rgba(255,255,255,0)',
        tickfont=dict(color='#fcd34d'),
        title_font=dict(color='#fcd34d'),
    )

    return fig


def create_macro_overview_dual_panel_chart(erp_records, index_df, focus_years=5):
    """
    创建双视图实验图：
    - 上图：全历史总览
    - 下图：固定近 N 年细节观察
    """
    if not erp_records:
        return None

    erp_df = pd.DataFrame(erp_records)
    required = {'date', 'equity_premium'}
    if not required.issubset(set(erp_df.columns)):
        return None

    erp_df['date'] = pd.to_datetime(erp_df['date'], errors='coerce')
    erp_df = erp_df.dropna(subset=['date']).sort_values('date')
    if erp_df.empty:
        return None

    if 'csi300_close' in erp_df.columns:
        merged_df = erp_df[['date', 'equity_premium', 'csi300_close']].dropna(subset=['csi300_close']).copy()
        merged_df = merged_df.rename(columns={'csi300_close': 'HS300'})
    elif not index_df.empty and 'HS300' in index_df.columns:
        hs300_df = index_df.reset_index().rename(columns={index_df.index.name or 'index': 'date'})
        hs300_df['date'] = pd.to_datetime(hs300_df['date'], errors='coerce')
        hs300_df = hs300_df[['date', 'HS300']].dropna(subset=['date']).sort_values('date')
        merged_df = pd.merge(erp_df[['date', 'equity_premium']], hs300_df, on='date', how='inner')
    else:
        return None

    if merged_df.empty:
        return None

    merged_df = merged_df.dropna(subset=['equity_premium', 'HS300']).copy()
    if merged_df.empty:
        return None

    last_date = merged_df['date'].iloc[-1]
    first_date = merged_df['date'].iloc[0]
    focus_start = max(first_date, last_date - pd.DateOffset(years=focus_years))

    focus_df = merged_df[merged_df['date'] >= focus_start].copy()
    if focus_df.empty:
        focus_df = merged_df.copy()

    fig = make_subplots(
        rows=2,
        cols=1,
        row_heights=[0.50, 0.50],
        vertical_spacing=0.10,
        specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
        subplot_titles=('全历史总览', f'近{focus_years}年细节观察'),
    )

    fig.add_trace(
        go.Scatter(
            x=merged_df['date'],
            y=merged_df['equity_premium'],
            mode='lines',
            name='股权溢价指数',
            line=dict(color='#3ec3ff', width=2.8),
            fill='tozeroy',
            fillcolor='rgba(62, 195, 255, 0.10)',
            hovertemplate='日期: %{x}<br>股权溢价: %{y:.2f}%<extra></extra>',
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=merged_df['date'],
            y=merged_df['HS300'],
            mode='lines',
            name='沪深300',
            line=dict(color='#fbbf24', width=2.2),
            hovertemplate='日期: %{x}<br>沪深300: %{y:.2f}<extra></extra>',
        ),
        row=1,
        col=1,
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=focus_df['date'],
            y=focus_df['equity_premium'],
            mode='lines',
            name=f'股权溢价指数(近{focus_years}年)',
            line=dict(color='#3ec3ff', width=2.8),
            fill='tozeroy',
            fillcolor='rgba(62, 195, 255, 0.10)',
            hovertemplate='日期: %{x}<br>股权溢价: %{y:.2f}%<extra></extra>',
        ),
        row=2,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=focus_df['date'],
            y=focus_df['HS300'],
            mode='lines',
            name=f'沪深300(近{focus_years}年)',
            line=dict(color='#fbbf24', width=2.2),
            hovertemplate='日期: %{x}<br>沪深300: %{y:.2f}<extra></extra>',
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

    fig.add_vrect(
        x0=focus_start,
        x1=last_date,
        fillcolor='rgba(62, 195, 255, 0.10)',
        line_width=0,
        row=1,
        col=1,
    )

    fig.update_layout(
        title=dict(
            text='股权溢价指数（双视图实验版）',
            x=0.5,
            font=dict(size=15, color='#f1f5f9'),
        ),
        hovermode='x unified',
        dragmode='pan',
        hoverdistance=30,
        uirevision='macro-overview-dual-view-lab',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.04,
            xanchor='right',
            x=1,
            font=dict(color='#94a3b8', size=11),
        ),
        margin=dict(l=60, r=70, t=88, b=65),
        height=780,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(17, 24, 39, 0.55)',
        font=dict(color='#94a3b8'),
        annotations=[
            dict(
                x=0.01,
                y=1.12,
                xref='paper',
                yref='paper',
                text=f'上图保留全历史，下图固定展示近{focus_years}年细节；不依赖频繁缩放也能同时看全局与局部。',
                showarrow=False,
                xanchor='left',
                font=dict(size=11, color='#94a3b8'),
            )
        ],
    )

    fig.update_xaxes(
        row=1,
        col=1,
        title='日期',
        gridcolor='rgba(255,255,255,0.05)',
        linecolor='rgba(255,255,255,0.1)',
        tickfont=dict(color='#64748b'),
        rangeslider=dict(visible=False),
    )
    fig.update_xaxes(
        row=2,
        col=1,
        title='日期',
        range=[focus_start, last_date],
        gridcolor='rgba(255,255,255,0.05)',
        linecolor='rgba(255,255,255,0.1)',
        tickfont=dict(color='#64748b', size=10),
        showspikes=True,
        spikemode='across',
        spikesnap='cursor',
        spikecolor='rgba(255,255,255,0.28)',
        spikethickness=1,
        rangeslider=dict(visible=False),
    )
    fig.update_yaxes(
        title_text='股权溢价(%)',
        row=1,
        col=1,
        secondary_y=False,
        gridcolor='rgba(62,195,255,0.10)',
        tickfont=dict(color='#7dd3fc'),
        title_font=dict(color='#7dd3fc'),
        zerolinecolor='rgba(255,255,255,0.14)',
    )
    fig.update_yaxes(
        title_text='沪深300点位',
        row=1,
        col=1,
        secondary_y=True,
        gridcolor='rgba(255,255,255,0)',
        tickfont=dict(color='#fcd34d'),
        title_font=dict(color='#fcd34d'),
    )
    fig.update_yaxes(
        title_text='股权溢价(%)',
        row=2,
        col=1,
        secondary_y=False,
        gridcolor='rgba(255,255,255,0.05)',
        tickfont=dict(color='#7dd3fc'),
        title_font=dict(color='#7dd3fc'),
        zerolinecolor='rgba(255,255,255,0.14)',
    )
    fig.update_yaxes(
        title_text='沪深300点位',
        row=2,
        col=1,
        secondary_y=True,
        gridcolor='rgba(255,255,255,0)',
        tickfont=dict(color='#fcd34d'),
        title_font=dict(color='#fcd34d'),
    )

    return fig


def create_macro_overview_reference_chart(erp_records, index_df):
    """
    创建参考版股权溢价图：
    - 主线：股权溢价指数
    - 参考线：机会值(70分位) / 中位值(50分位) / 危险值(30分位)
    - 对照线：沪深300
    """
    if not erp_records:
        return None, None

    erp_df = pd.DataFrame(erp_records)
    required = {'date', 'equity_premium'}
    if not required.issubset(set(erp_df.columns)):
        return None, None

    erp_df['date'] = pd.to_datetime(erp_df['date'], errors='coerce')
    erp_df = erp_df.dropna(subset=['date']).sort_values('date')
    if erp_df.empty:
        return None, None

    if 'csi300_close' in erp_df.columns:
        merged_df = erp_df[['date', 'equity_premium', 'csi300_close']].dropna(subset=['csi300_close']).copy()
        merged_df = merged_df.rename(columns={'csi300_close': 'HS300'})
    elif not index_df.empty and 'HS300' in index_df.columns:
        hs300_df = index_df.reset_index().rename(columns={index_df.index.name or 'index': 'date'})
        hs300_df['date'] = pd.to_datetime(hs300_df['date'], errors='coerce')
        hs300_df = hs300_df[['date', 'HS300']].dropna(subset=['date']).sort_values('date')
        merged_df = pd.merge(erp_df[['date', 'equity_premium']], hs300_df, on='date', how='inner')
    else:
        return None, None

    if merged_df.empty:
        return None, None

    merged_df = merged_df.dropna(subset=['equity_premium', 'HS300']).copy()
    if merged_df.empty:
        return None, None

    premium_series = merged_df['equity_premium']

    def expanding_quantile(series: pd.Series, q: float) -> pd.Series:
        return series.expanding(min_periods=30).quantile(q)

    merged_df['opportunity_line'] = expanding_quantile(premium_series, 0.70)
    merged_df['median_line'] = expanding_quantile(premium_series, 0.50)
    merged_df['danger_line'] = expanding_quantile(premium_series, 0.30)

    latest_row = merged_df.iloc[-1]
    latest_value = float(latest_row['equity_premium'])
    historical_mean = float(premium_series.mean())
    percentile = float(percentileofscore(premium_series.dropna(), latest_value))

    summary = {
        'date': latest_row['date'].strftime('%Y.%m.%d'),
        'latest_value': latest_value,
        'historical_mean': historical_mean,
        'percentile': percentile,
    }

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=merged_df['date'],
            y=merged_df['equity_premium'],
            mode='lines',
            name='股权溢价指数',
            line=dict(color='#4b4b4b', width=2.4),
            hovertemplate='日期: %{x}<br>股权溢价指数: %{y:.2f}<extra></extra>',
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=merged_df['date'],
            y=merged_df['opportunity_line'],
            mode='lines',
            name='机会值(70分位)',
            line=dict(color='#324d94', width=1.4),
            hovertemplate='日期: %{x}<br>机会值: %{y:.2f}<extra></extra>',
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=merged_df['date'],
            y=merged_df['median_line'],
            mode='lines',
            name='中位值(50分位)',
            line=dict(color='#0d7fd1', width=1.4),
            hovertemplate='日期: %{x}<br>中位值: %{y:.2f}<extra></extra>',
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=merged_df['date'],
            y=merged_df['danger_line'],
            mode='lines',
            name='危险值(30分位)',
            line=dict(color='#6f97e7', width=1.4),
            hovertemplate='日期: %{x}<br>危险值: %{y:.2f}<extra></extra>',
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=merged_df['date'],
            y=merged_df['HS300'],
            mode='lines',
            name='沪深300',
            line=dict(color='#1e90ff', width=1.2),
            opacity=0.9,
            hovertemplate='日期: %{x}<br>沪深300: %{y:.2f}<extra></extra>',
        ),
        secondary_y=True,
    )

    fig.add_hline(
        y=historical_mean,
        line_dash='dash',
        line_color='rgba(75,75,75,0.55)',
        annotation_text=f'历史均值: {historical_mean:.2f}',
        annotation_position='right',
    )

    fig.update_layout(
        title=dict(
            text='股权溢价指数参考版',
            x=0.5,
            font=dict(size=15, color='#334155'),
        ),
        hovermode='x unified',
        dragmode='pan',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='center',
            x=0.5,
            font=dict(color='#475569', size=11),
        ),
        margin=dict(l=50, r=55, t=55, b=55),
        height=540,
        paper_bgcolor='#eef4ff',
        plot_bgcolor='#ffffff',
        font=dict(color='#334155'),
        xaxis=dict(
            title='',
            gridcolor='rgba(148,163,184,0.18)',
            linecolor='rgba(148,163,184,0.35)',
            tickfont=dict(color='#64748b'),
            rangeslider=dict(
                visible=True,
                thickness=0.10,
                bgcolor='rgba(191,219,254,0.18)',
                bordercolor='rgba(148,163,184,0.20)',
                borderwidth=1,
            ),
        ),
    )
    fig.update_yaxes(
        title_text='股权溢价指数',
        secondary_y=False,
        gridcolor='rgba(148,163,184,0.18)',
        tickfont=dict(color='#64748b'),
        title_font=dict(color='#475569'),
        zerolinecolor='rgba(148,163,184,0.25)',
    )
    fig.update_yaxes(
        title_text='沪深300点位',
        secondary_y=True,
        gridcolor='rgba(0,0,0,0)',
        tickfont=dict(color='#1d4ed8'),
        title_font=dict(color='#1d4ed8'),
    )

    return fig, summary

def generate_html_report(df, conclusions, output_dir, mode='production'):
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

    is_lab = mode == 'lab'
    use_reference_chart_style = True

    # 创建价格走势图
    price_chart = create_price_chart(df, indices_config, recent_days, light_theme=use_reference_chart_style)
    price_chart_html = price_chart.to_html(full_html=False, include_plotlyjs='cdn')
    price_summary_items = []
    for code in ['HS300', 'ZZ500', 'ZZ1000', 'ZZA500']:
        if code in df.columns:
            latest_value = df[code].dropna().iloc[-1]
            display_name = indices_config.get(code, {}).get('name', code)
            price_summary_items.append(f'{display_name} {latest_value:,.2f}')
    price_summary_html = (
        f'{latest_date}，' + '，'.join(price_summary_items)
        if price_summary_items
        else f'{latest_date}，暂无指数点位摘要。'
    )

    # 加载并合并股权溢价图（来自 Equity Risk Premium）
    erp_records = load_equity_premium_records()
    macro_config = {
        'displaylogo': False,
        'responsive': True,
        'scrollZoom': is_lab,
        'doubleClick': 'reset+autosize',
    }
    macro_overview_chart = create_macro_overview_chart(erp_records, df, recent_days, experimental=is_lab)
    if macro_overview_chart is not None:
        macro_overview_html = macro_overview_chart.to_html(
            full_html=False,
            include_plotlyjs='cdn',
            config=macro_config,
        )
    else:
        macro_overview_html = '<div style="padding: 24px; color: #94a3b8;">未检测到可用于合并展示的股权溢价数据，跳过宏观总览。</div>'

    macro_dual_panel_html = ''
    if is_lab:
        macro_dual_panel_chart = create_macro_overview_dual_panel_chart(erp_records, df)
        if macro_dual_panel_chart is not None:
            macro_dual_panel_html = macro_dual_panel_chart.to_html(
                full_html=False,
                include_plotlyjs=False,
                config=macro_config,
            )
        else:
            macro_dual_panel_html = '<div style="padding: 24px; color: #94a3b8;">未检测到可用于生成双层实验图的数据。</div>'

    macro_reference_html = ''
    macro_reference_summary_html = ''
    macro_reference_chart, macro_reference_summary = create_macro_overview_reference_chart(erp_records, df)
    if macro_reference_chart is not None and macro_reference_summary is not None:
        reference_chart_id = 'macro-reference-chart'
        reference_chart_body = macro_reference_chart.to_html(
            full_html=False,
            include_plotlyjs=False,
            div_id=reference_chart_id,
            config={
                'displaylogo': False,
                'responsive': True,
                'scrollZoom': False,
                'doubleClick': 'reset+autosize',
            },
        )
        macro_reference_html = (
            '<div style="display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap;'
            'margin:0 0 12px 0;">'
            '<button type="button" class="macro-ref-toggle is-on" '
            'data-target="70" style="border:1px solid #324d94;background:#e8efff;color:#324d94;'
            'padding:6px 12px;border-radius:999px;font-size:12px;cursor:pointer;">70</button>'
            '<button type="button" class="macro-ref-toggle is-on" '
            'data-target="50" style="border:1px solid #0d7fd1;background:#e0f2fe;color:#0d7fd1;'
            'padding:6px 12px;border-radius:999px;font-size:12px;cursor:pointer;">50</button>'
            '<button type="button" class="macro-ref-toggle is-on" '
            'data-target="30" style="border:1px solid #6f97e7;background:#eef4ff;color:#6f97e7;'
            'padding:6px 12px;border-radius:999px;font-size:12px;cursor:pointer;">30</button>'
            '</div>'
            + reference_chart_body +
            f"""
<script>
(function() {{
    const chartId = "{reference_chart_id}";
    const traceIndexMap = {{ "70": 1, "50": 2, "30": 3 }};

    function bindReferenceToggles() {{
        const chart = document.getElementById(chartId);
        if (!chart || !chart.data) return;

        document.querySelectorAll('.macro-ref-toggle').forEach((button) => {{
            if (button.dataset.bound === 'true') return;
            button.dataset.bound = 'true';

            button.addEventListener('click', () => {{
                const target = button.dataset.target;
                const traceIndex = traceIndexMap[target];
                const currentVisible = chart.data[traceIndex] && chart.data[traceIndex].visible;
                const nextVisible = currentVisible === 'legendonly' ? true : 'legendonly';

                Plotly.restyle(chart, {{ visible: nextVisible }}, [traceIndex]);

                if (nextVisible === 'legendonly') {{
                    button.classList.remove('is-on');
                    button.style.opacity = '0.45';
                    button.style.filter = 'grayscale(0.15)';
                }} else {{
                    button.classList.add('is-on');
                    button.style.opacity = '1';
                    button.style.filter = 'none';
                }}
            }});
        }});
    }}

    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', bindReferenceToggles);
    }} else {{
        bindReferenceToggles();
    }}
}})();
</script>
"""
        )
        macro_reference_summary_html = (
            f"{macro_reference_summary['date']}，股权溢价指数最新值 "
            f"{macro_reference_summary['latest_value']:.2f}，历史平均 "
            f"{macro_reference_summary['historical_mean']:.2f}，当前值高于历史上 "
            f"{macro_reference_summary['percentile']:.2f}% 的时期"
        )
    else:
        macro_reference_html = '<div style="padding: 24px; color: #94a3b8;">未检测到可用于生成参考版图表的数据。</div>'

    # 创建比价走势图（全历史 + 单列满宽布局）
    ratio_charts_html = []
    for target in ['ZZ500', 'ZZ1000', 'ZZA500']:
        if f'{target}_ratio' in df.columns:
            name = indices_config[target]['name']
            show_full_history = True
            chart = create_ratio_chart(
                df,
                target,
                f'{name} vs 沪深300',
                ma_window,
                recent_days,
                light_theme=use_reference_chart_style,
                show_full_history=show_full_history,
            )
            ratio_charts_html.append(chart.to_html(full_html=False, include_plotlyjs='cdn'))

    # 生成指标卡片HTML
    cards_html = generate_cards_html(conclusions, df)

    # 生成分析结论HTML
    analysis_html = generate_analysis_html(conclusions)

    # 组装完整HTML - 金融终端风格
    page_label = 'LAB' if is_lab else 'LIVE'
    page_title = '大宽基指数比价系统 Lab' if is_lab else '大宽基指数比价系统'
    hero_note = (
        'Lab 试验区：当前用于验证更强的图表缩放、时间滑窗和交互方式。'
        if is_lab
        else '基于性价比原则，分析大宽基的估值水平与趋势，提供配置参考'
    )

    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title} | {report_date}</title>
    <script charset="utf-8" src="https://cdn.plot.ly/plotly-3.0.0.min.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Noto+Sans+SC:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0a0e17;
            --bg-secondary: #0f172a;
            --bg-card: rgba(15, 23, 42, 0.75);
            --bg-glass: rgba(255, 255, 255, 0.03);
            --bg-surface: rgba(30, 41, 59, 0.5);
            --border-subtle: rgba(255, 255, 255, 0.08);
            --border-glow: rgba(251, 191, 36, 0.4);
            --text-primary: #f8fafc;
            --text-secondary: #cbd5e1;
            --text-muted: #94a3b8;
            --accent-gold: #fbbf24;
            --accent-amber: #f59e0b;
            --accent-emerald: #10b981;
            --accent-rose: #f43f5e;
            --accent-sky: #0ea5e9;
            --accent-indigo: #6366f1;
            --accent-violet: #8b5cf6;
            --card-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.4);
            --glass-blur: blur(14px);
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-font-smoothing: antialiased;
        }}

        body {{
            font-family: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
            overflow-x: hidden;
            font-variant-numeric: tabular-nums;
        }}

        /* 动态背景 */
        body::before {{
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background:
                radial-gradient(circle at 20% 30%, rgba(62, 195, 255, 0.05), transparent 40%),
                radial-gradient(circle at 80% 70%, rgba(139, 92, 246, 0.05), transparent 40%),
                radial-gradient(circle at 50% 50%, rgba(251, 191, 36, 0.02), transparent 60%);
            pointer-events: none;
            z-index: -1;
        }}

        /* 极细网格 */
        body::after {{
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-image:
                linear-gradient(rgba(255,255,255,0.01) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.01) 1px, transparent 1px);
            background-size: 40px 40px;
            pointer-events: none;
            z-index: -1;
        }}

        .container {{
            max-width: 1680px;
            margin: 0 auto;
            padding: 32px 40px;
        }}

        /* 顶部导航 */
        .top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 24px;
            margin-bottom: 32px;
            border-bottom: 1px solid var(--border-subtle);
        }}

        .logo {{
            display: flex;
            align-items: center;
            gap: 16px;
            text-decoration: none;
        }}

        .logo-icon {{
            width: 44px;
            height: 44px;
            background: linear-gradient(135deg, var(--accent-gold), var(--accent-amber));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            font-weight: 800;
            color: #000;
            box-shadow: 0 0 20px rgba(251, 191, 36, 0.4);
            transition: transform 0.3s ease;
        }}

        .logo:hover .logo-icon {{
            transform: rotate(5deg) scale(1.05);
        }}

        .logo-text {{
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.8px;
            background: linear-gradient(to bottom, #fff, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .logo-text span {{
            color: var(--accent-gold);
            -webkit-text-fill-color: var(--accent-gold);
        }}

        .meta-info {{
            display: flex;
            gap: 32px;
            font-size: 13px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }}

        .meta-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            background: var(--bg-glass);
            padding: 6px 16px;
            border-radius: 99px;
            border: 1px solid var(--border-subtle);
        }}

        .meta-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--accent-emerald);
            box-shadow: 0 0 10px var(--accent-emerald);
            animation: pulse 2s ease-in-out infinite;
        }}

        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.4; transform: scale(0.8); }}
        }}

        /* Hero */
        .hero {{
            text-align: center;
            padding: 40px 0 60px;
        }}

        .hero h1 {{
            font-size: 56px;
            font-weight: 800;
            letter-spacing: -1.5px;
            margin-bottom: 12px;
            background: linear-gradient(135deg, #fff 0%, var(--accent-gold) 50%, #fff 100%);
            background-size: 200% auto;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: shimmer 5s linear infinite;
        }}

        .hero-subtitle {{
            font-size: 18px;
            color: var(--text-secondary);
            max-width: 700px;
            margin: 0 auto;
            opacity: 0.8;
            font-weight: 300;
        }}

        .risk-banner {{
            display: flex;
            align-items: flex-start;
            gap: 14px;
            margin: 0 auto 28px;
            padding: 18px 22px;
            max-width: 1080px;
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.16), rgba(239, 68, 68, 0.12));
            border: 1px solid rgba(251, 191, 36, 0.35);
            border-radius: 18px;
            box-shadow: 0 12px 28px rgba(0, 0, 0, 0.22);
            backdrop-filter: var(--glass-blur);
        }}

        .risk-icon {{
            width: 34px;
            height: 34px;
            flex-shrink: 0;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(255, 255, 255, 0.12);
            color: #fde68a;
            font-size: 18px;
            font-weight: 700;
        }}

        .risk-title {{
            font-size: 14px;
            font-weight: 700;
            color: #fef3c7;
            margin-bottom: 4px;
            letter-spacing: 0.5px;
        }}

        .risk-text {{
            font-size: 13px;
            color: #fde68a;
            line-height: 1.75;
        }}

        /* 指标卡片 */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 24px;
            margin-bottom: 40px;
        }}

        .metric-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: 20px;
            padding: 24px;
            backdrop-filter: var(--glass-blur);
            transition: all 0.4s cubic-bezier(0.23, 1, 0.32, 1);
            position: relative;
            overflow: hidden;
            box-shadow: var(--card-shadow);
        }}

        .metric-card::after {{
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(225deg, rgba(255,255,255,0.03) 0%, transparent 50%);
            pointer-events: none;
        }}

        .metric-card:hover {{
            transform: translateY(-6px);
            border-color: var(--border-glow);
            background: rgba(30, 41, 59, 0.8);
        }}

        .metric-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}

        .metric-name {{
            font-size: 13px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1.5px;
        }}

        .metric-badge {{
            font-size: 10px;
            font-weight: 700;
            padding: 4px 12px;
            border-radius: 99px;
            text-transform: uppercase;
        }}

        .badge-benchmark {{ background: rgba(251, 191, 36, 0.15); color: var(--accent-gold); border: 1px solid rgba(251, 191, 36, 0.2); }}
        .badge-high {{ background: rgba(244, 63, 94, 0.15); color: var(--accent-rose); border: 1px solid rgba(244, 63, 94, 0.2); }}
        .badge-low {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald); border: 1px solid rgba(16, 185, 129, 0.2); }}
        .badge-neutral {{ background: rgba(14, 165, 233, 0.15); color: var(--accent-sky); border: 1px solid rgba(14, 165, 233, 0.2); }}

        .metric-value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 32px;
            font-weight: 700;
            color: #fff;
            margin-bottom: 4px;
        }}

        .metric-label {{
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 20px;
        }}

        .metric-stats {{
            display: flex;
            flex-direction: column;
            gap: 10px;
            padding-top: 16px;
            border-top: 1px solid var(--border-subtle);
        }}

        .stat-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .stat-label {{
            font-size: 12px;
            color: var(--text-muted);
        }}

        .stat-value {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
            font-weight: 600;
            padding: 2px 10px;
            border-radius: 6px;
        }}

        .stat-value.positive {{ color: var(--accent-emerald); background: rgba(16, 185, 129, 0.1); }}
        .stat-value.negative {{ color: var(--accent-rose); background: rgba(244, 63, 94, 0.1); }}
        .stat-value.neutral {{ color: var(--accent-sky); background: rgba(14, 165, 233, 0.1); }}

        /* 图表容器 */
        .charts-section {{
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: 24px;
            padding: 32px;
            margin-bottom: 32px;
            backdrop-filter: var(--glass-blur);
            box-shadow: var(--card-shadow);
        }}

        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border-subtle);
        }}

        .section-title {{
            display: flex;
            align-items: center;
            gap: 16px;
        }}

        .section-icon {{
            width: 40px;
            height: 40px;
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
        }}

        .section-title h2 {{
            font-size: 22px;
            font-weight: 700;
            color: #fff;
        }}

        .chart-wrapper {{
            background: rgba(0, 0, 0, 0.2);
            border-radius: 16px;
            padding: 12px;
            border: 1px solid rgba(255,255,255,0.03);
        }}

        .ratio-charts-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
        }}

        .ratio-chart-wrapper {{
            background: rgba(0, 0, 0, 0.1);
            border-radius: 12px;
            padding: 8px;
        }}

        /* 分析卡片 */
        .analysis-section {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 24px;
            margin-bottom: 32px;
        }}

        .analysis-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: 24px;
            padding: 32px;
            backdrop-filter: var(--glass-blur);
            transition: all 0.3s ease;
        }}

        .analysis-card:hover {{
            border-color: rgba(255,255,255,0.15);
            background: rgba(30, 41, 59, 0.8);
        }}

        .analysis-header {{
            display: flex;
            align-items: center;
            gap: 20px;
            margin-bottom: 24px;
        }}

        .analysis-icon {{
            width: 52px;
            height: 52px;
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            font-weight: 700;
            color: #fff;
        }}

        .analysis-icon.zz500 {{ background: linear-gradient(135deg, #10b981 0%, #059669 100%); box-shadow: 0 8px 20px rgba(16, 185, 129, 0.2); }}
        .analysis-icon.zz1000 {{ background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%); box-shadow: 0 8px 20px rgba(139, 92, 246, 0.2); }}
        .analysis-icon.zza500 {{ background: linear-gradient(135deg, #f97316 0%, #ea580c 100%); box-shadow: 0 8px 20px rgba(249, 115, 22, 0.2); }}

        .analysis-title {{ font-size: 20px; font-weight: 700; color: #fff; }}
        .analysis-subtitle {{ font-size: 13px; color: var(--text-muted); }}

        .analysis-item {{
            padding: 16px 0;
            border-bottom: 1px solid var(--border-subtle);
        }}

        .analysis-item:last-child {{ border-bottom: none; }}

        .analysis-item-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}

        .analysis-item-title {{ font-size: 14px; font-weight: 600; color: var(--text-secondary); }}
        .analysis-item-value {{ font-family: 'JetBrains Mono', monospace; font-size: 15px; font-weight: 700; }}
        .analysis-item-desc {{ font-size: 13px; color: var(--text-muted); line-height: 1.6; }}

        /* 页脚 */
        .footer {{
            text-align: center;
            padding: 60px 0 40px;
            border-top: 1px solid var(--border-subtle);
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }}

        .footer-brand {{
            margin-top: 12px;
            font-size: 11px;
            letter-spacing: 2px;
            text-transform: uppercase;
            opacity: 0.5;
        }}

        /* 动画 */
        @keyframes shimmer {{
            0% {{ background-position: 200% center; }}
            100% {{ background-position: -200% center; }}
        }}

        @keyframes fadeInUp {{
            from {{ opacity: 0; transform: translateY(30px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .metric-card, .charts-section, .analysis-card {{
            animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) backwards;
        }}

        .metric-card:nth-child(1) {{ animation-delay: 0.1s; }}
        .metric-card:nth-child(2) {{ animation-delay: 0.2s; }}
        .metric-card:nth-child(3) {{ animation-delay: 0.3s; }}
        .metric-card:nth-child(4) {{ animation-delay: 0.4s; }}

        /* 滚动条 */
        ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
        ::-webkit-scrollbar-track {{ background: var(--bg-primary); }}
        ::-webkit-scrollbar-thumb {{ background: var(--bg-surface); border-radius: 4px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: var(--text-muted); }}

        @media (max-width: 1400px) {{
            .metrics-grid, .analysis-section {{ grid-template-columns: repeat(2, 1fr); }}
            .ratio-charts-grid {{ grid-template-columns: 1fr; }}
        }}

        @media (max-width: 900px) {{
            .metrics-grid, .analysis-section, .ratio-charts-grid {{ grid-template-columns: 1fr; }}
            .hero h1 {{ font-size: 36px; }}
            .container {{ padding: 20px; }}
        }}
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
                    <span>{page_label}</span>
                </div>
                <div class="meta-item">数据截止 {latest_date}</div>
                <div class="meta-item">生成于 {report_date}</div>
            </div>
        </div>

        <!-- Hero -->
        <div class="hero">
            <h1>{page_title}</h1>
            <p class="hero-subtitle">{hero_note}</p>
        </div>

        <!-- 第一排：股权溢价指数 -->
        <div class="charts-section overview-section"><div class="section-header"><div class="section-title"><div class="section-icon">◎</div><div><h2>股权溢价指数</h2><div class="overview-subtitle">{macro_reference_summary_html if macro_reference_summary_html else '溢价指数值=300指数盈利收益率-10年国债收益率；值越大代表投资价值越大。'}</div></div></div></div><div class="overview-subtitle" style="margin:-4px 0 16px 42px;color:#64748b;">值越大代表投资价值越大；参考线采用截至当日的历史分位估算：机会值(70分位)、中位值(50分位)、危险值(30分位)。</div><div class="chart-wrapper">{macro_reference_html}</div></div>

        <!-- 第二排开始：原 Index Report 主体 -->
        <div class="charts-section">
            <div class="section-header">
                <div class="section-title">
                    <div class="section-icon">📈</div>
                    <div>
                        <h2>指数价格走势</h2>
                        <div class="overview-subtitle">{price_summary_html}</div>
                    </div>
                </div>
            </div>
            <div class="chart-wrapper">{price_chart_html}</div>
        </div>

        {cards_html}

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

        <div class="risk-banner">
            <div class="risk-icon">!</div>
            <div>
                <div class="risk-title">风险提示 / 免责声明</div>
                <div class="risk-text">本页面内容仅基于公开市场数据进行量化整理与历史分析，不构成任何投资建议、收益承诺或买卖依据。市场有风险，投资需谨慎；使用者应结合自身风险承受能力独立判断，并自行承担相关决策责任。</div>
            </div>
        </div>

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
    file_prefix = 'index_compare_lab' if is_lab else 'index_compare'
    report_file = output_path / f'{file_prefix}_{timestamp}.html'
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
        'ZZA500': ('zza500', '创业板')
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
                    <div class="analysis-item-desc">{data['percentile']['description']}<br><span style="font-size:12px;color:var(--text-muted);">基于全部有效历史样本计算</span></div>
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
            </div>
        </div>
        """)

    return f'<div class="analysis-section">{"".join(blocks)}</div>'


def generate_report(data_path, conclusions_path, output_dir, mode='production'):
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
    report_file = generate_html_report(df, conclusions, output_dir, mode=mode)

    print(f"\n[OK] 报告已生成: {report_file}")

    return report_file


def resolve_output_dir(output_dir: str, mode: str) -> Path:
    """解析输出目录，lab 模式默认落在系统根目录，便于隔离试验产物。"""
    path = Path(output_dir)
    if path.is_absolute():
        return path

    if mode == 'lab':
        system_root = Path(__file__).resolve().parents[5]
        if output_dir == 'reports':
            return system_root / 'reports_lab'
        return system_root / path

    return path


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
    parser.add_argument('--mode',
                        default='production',
                        choices=['production', 'lab'],
                        help='报告模式：production 或 lab')

    args = parser.parse_args()

    # 切换到 skill 目录
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)

    output_dir = resolve_output_dir(args.output, args.mode)
    generate_report(args.data, args.conclusions, str(output_dir), mode=args.mode)


if __name__ == '__main__':
    main()
