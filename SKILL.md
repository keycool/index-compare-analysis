---
name: index-compare
description: A股指数比价分析工具，分析中证500、中证1000、中证A500相对沪深300的比价关系，计算历史分位、均值回归，生成交互式HTML报告。当用户提到"比价分析"、"指数对比"、"指数比价"、"500和1000怎么样"、"中证500分位"、"中证1000估值"、"中证A500比价"、"生成指数报告"、"查询比价"、"index compare"、"valuation analysis"时使用此技能。
---

# 指数比价分析 (Index Compare)

分析沪深300、中证500、中证1000、中证A500、上证综指的比价关系，计算历史分位和均值回归，生成 Plotly 交互式 HTML 报告。

## 环境要求

- Python 依赖：`tushare pandas numpy plotly scipy`
- 必须设置 `TUSHARE_TOKEN` 环境变量或在 skill 目录下创建 `.env` 文件

安装依赖：
```bash
pip install tushare pandas numpy plotly scipy
```

## 使用方式

### 完整分析（默认）

```bash
python scripts/main.py
```

自动执行：清理临时文件 -> 检查环境 -> 获取数据 -> 计算比价和分位 -> 生成智能分析 -> 输出 HTML 报告。

报告输出路径：`../../index_compare_YYYYMMDD_HHMMSS.html`

### 快速查询（使用已有数据）

```bash
python scripts/main.py --query           # 查询所有指数
python scripts/main.py --query ZZ500     # 只看中证500
python scripts/main.py --query ZZ1000    # 只看中证1000
python scripts/main.py --query ZZA500    # 只看中证A500
```

快速查询不重新获取数据，使用上次分析的缓存结果。

### 手动清理临时文件

```bash
python scripts/cleanup.py --force        # 强制清理所有临时文件
python scripts/cleanup.py --max 10       # 自定义阈值
```

主程序启动时会自动清理（`tmpclaude-*` 文件数量 >= 20 时触发）。

## 分析指标

详细的分析规则见 `analysis-rules.md`。核心指标概要：

- **历史分位数**：基于全部历史数据。< 20% 极度低估（超配），20-40% 相对低估，40-60% 中性（标配），60-80% 相对高估，> 80% 极度高估（低配）
- **均值回归**：偏离30日均线。> +5% 超买，< -5% 超卖，±5% 内正常
- **趋势判断**：比较当前比价与 5/10/20 日前数据，判断上升/下降/震荡
- **配置建议**：综合趋势、分位、偏离度三个维度生成超配/标配/低配建议

## 模块结构

```
scripts/
├── main.py              # 主入口
├── fetch_data.py        # 数据获取（Tushare API）
├── calculate.py         # 比价计算
├── analyze.py           # 智能分析
├── generate_report.py   # HTML 报告生成
└── cleanup.py           # 临时文件清理
config.json              # 指数配置和分析参数
analysis-rules.md        # 详细分析规则
```

## HTML 报告内容

报告包含：指标卡片（比价/分位/偏离度）、价格走势图（近1000交易日）、三个比价走势图（含分位数标注和红绿虚线标注区间极值）、智能分析结论和配置建议。深色主题，金融终端风格。
