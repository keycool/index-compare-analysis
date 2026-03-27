# A股指数比价分析工具 | Index Compare Analysis

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-1.0.2-green)](https://github.com/keycool/index-compare-analysis)

> 自动化分析 A 股主要指数的比价关系，一键生成包含智能分析结论的交互式 HTML 报告

## 📊 项目简介

本工具专注于分析中证500、中证1000、中证A500相对沪深300的估值水平，通过计算历史分位数、均值回归、趋势判断等指标，为投资者提供量化的配置建议。

### 核心功能

- 📈 **自动数据获取**：从 Tushare 获取沪深300、中证500、中证1000、中证A500的历史数据
- 📉 **比价计算**：计算各指数相对沪深300的比价关系及30日移动平均线
- 🎯 **历史分位分析**：基于全部历史数据计算当前比价的历史分位数
- 🤖 **AI 智能分析**：综合趋势、分位、偏离度三个维度生成配置建议
- 🎨 **交互式报告**：生成 Plotly 交互式 HTML 报告，支持缩放、悬停查看
- 🧹 **自动清理**：智能管理临时文件，保持项目目录整洁

### 最新优化 (v1.0.2)

- ✅ **智能增量更新**：自动检测本地数据与远程数据，只获取新增数据，大幅提升运行速度
- ✅ **强制更新选项**：支持 `--force` 参数强制完整更新所有历史数据
- ✅ **顶层 orchestrator**：新增统一入口，支持 ERP + Relative 顺序调度
- ✅ **共享接口标准化**：新增 `shared/erp_signal.json` 与 `shared/relative_signal.json`
- ✅ **主从 workflow 重构**：线上统一收敛为主调度 workflow，单项目 workflow 改为手动触发
- ✅ **统一消费入口**：`merged_signal.json` 现在可直接供报告和下游消费
- ✅ **单页合并报告布局**：首屏整合股权溢价指数与沪深300，后续延续 Relative 主体分析
- ✅ **页面结构再优化**：价格走势前置、移除冗余 ERP 补充视图、精简分析卡展示
- ✅ **全历史首屏修复**：股权溢价指数图改为依赖 ERP 全量历史共享数据
- ✅ 图表分位数标注优化：显示在图表下方中央，不遮挡内容
- ✅ 红绿虚线精准匹配：标注显示范围内的最高点和最低点
- ✅ 图表高度优化：增加底部空间，完整显示所有标注
- ✅ 自动清理功能：临时文件超过20个时自动清理

## 🚀 快速开始

### 环境要求

- Python 3.8+
- Tushare API Token（免费注册：https://tushare.pro/register）

### 安装依赖

```bash
pip install tushare pandas numpy plotly scipy
```

### 配置 API Token

**方式1：环境变量**
```bash
# Windows PowerShell
$env:TUSHARE_TOKEN = "你的Token"

# Windows CMD
set TUSHARE_TOKEN=你的Token

# Linux/Mac
export TUSHARE_TOKEN=你的Token
```

**方式2：创建 .env 文件**
```bash
# 在项目根目录创建 .env 文件
TUSHARE_TOKEN=你的Token
```

### 运行分析

**完整分析（推荐）**
```bash
cd .claude/skills/index-compare
python scripts/main.py
```
> 首次运行会获取全部历史数据，之后会自动检测增量更新，速度更快

**强制完整更新**
```bash
# 强制重新获取所有历史数据
python scripts/main.py --force
```

**快速查询（查看已有数据）**
```bash
# 查询所有指数
python scripts/main.py --query

# 查询特定指数
python scripts/main.py --query ZZ500
python scripts/main.py --query ZZ1000
python scripts/main.py --query ZZA500
```

## 📈 分析指标说明

### 历史分位数

| 分位区间 | 解读 | 建议 |
|----------|------|------|
| < 20% | 🔥 极度低估 | 强烈超配信号 |
| 20-40% | 📉 相对低估 | 可考虑超配 |
| 40-60% | ⚖️ 中性区域 | 标配 |
| 60-80% | 📈 相对高估 | 可考虑低配 |
| > 80% | 🚨 极度高估 | 强烈低配信号 |

### 均值回归（偏离30日均线）

- **> +5%**：超买，短期可能回调
- **< -5%**：超卖，短期可能反弹
- **±5%内**：正常波动范围

### 配置建议逻辑

综合 **趋势**、**分位**、**偏离度** 三个维度，AI 智能生成：
- 📈 **超配建议**：分位低 + 趋势向上 + 超卖
- ⚖️ **标配建议**：分位中性 + 趋势不明
- 📉 **低配建议**：分位高 + 趋势向下 + 超买

## 📊 输出示例

### 控制台输出

```
============================================================
         指数比价分析 (Index Compare)
============================================================
执行时间: 2026-02-12 11:35:04
============================================================

[步骤 1/5] 检查环境配置...
[OK] Token 已配置

[步骤 2/5] 获取指数数据...
[OK] 数据获取完成

[步骤 3/5] 计算比价指标...
[OK] 比价计算完成

[步骤 4/5] 生成智能分析...
[OK] 分析完成

[步骤 5/5] 生成 HTML 报告...
[OK] 报告生成完成

============================================================
         [OK] 分析完成!
============================================================

[DATA] 最新数据 (2026-02-11):
+-------------+----------+----------+----------+
| 指标        | 中证500  | 中证1000 | 沪深300  |
+-------------+----------+----------+----------+
| 收盘价      |  8325.81 |  8239.51 |  4713.82 |
| 比价        |   1.7663 |   1.7479 | (基准)   |
+-------------+----------+----------+----------+

[RECOMMEND] 配置建议:

【中证500】📉 低配
  - 历史分位80.6%，高估区域
  - 短期正常波动
  - 趋势震荡

【中证1000】📉 低配
  - 历史分位71.8%，相对高估
  - 短期正常波动
  - 趋势震荡

[REPORT] 报告文件: ../../../reports/index_compare_20260212_113516.html
```

### HTML 报告特性

- 📊 **指标卡片**：实时显示各指数的比价、分位、偏离度
- 📈 **价格走势图**：多指数价格对比，支持图例切换
- ⚖️ **比价走势图**：三个比价图表并排显示，标注清晰
- 🤖 **智能分析**：详细的分析结论和配置建议
- 🎨 **深色主题**：金融终端风格，专业美观

## 🗂️ 项目结构

```
.
├── .claude/skills/index-compare/     # Skill 主目录
│   ├── scripts/                      # Python 脚本
│   │   ├── main.py                   # 主入口
│   │   ├── fetch_data.py             # 数据获取
│   │   ├── calculate.py              # 比价计算
│   │   ├── analyze.py                # 智能分析
│   │   ├── generate_report.py        # 报告生成
│   │   └── cleanup.py                # 临时文件清理
│   ├── data/                         # 数据文件
│   ├── config.json                   # 配置文件
│   ├── SKILL.md                      # Skill 文档
│   └── analysis-rules.md             # 分析规则说明
├── reports/                          # HTML 报告输出目录
├── .gitignore                        # Git 忽略配置
└── README.md                         # 项目说明
```

## 共享接口

完整流程结束后，项目会导出标准共享文件：

```text
../shared/relative_signal.json
```

报告在需要合并 ERP 数据时，会优先读取：

```text
../shared/erp_signal.json
```

这样 `CSI300 Relative Index` 不再依赖 `Equity Risk Premium` 的内部 dashboard 文件结构，而是依赖正式发布的共享接口。

## GitHub Actions

线上调度现已收敛为：

- 主调度 workflow: `.github/workflows/erp-relative-master-scheduler.yml`
- 单项目手动 workflow: `.github/workflows/csi300-relative-index-scheduler.yml`

主调度 workflow 以当前仓库为入口，并在运行时额外 checkout `Equity Risk Premium` 仓库，然后顺序执行：

1. `Equity Risk Premium`
2. `CSI300 Relative Index`
3. 共享接口校验
4. `shared/merged_signal.json` 生成

若 `Equity Risk Premium` 仓库是私有仓库，需要在当前仓库配置：

- `CROSS_REPO_PAT`

主调度还会分别读取 ERP 和 CSI 各自的飞书配置：

- `ERP_FEISHU_WEBHOOK_URL`
- `ERP_FEISHU_APP_TOKEN`
- `ERP_FEISHU_TABLE_ID`
- `CSI_FEISHU_WEBHOOK_URL`
- `CSI_FEISHU_APP_TOKEN`
- `CSI_FEISHU_TABLE_ID`

## GitHub Pages

主调度 workflow 成功后，会自动发布 GitHub Pages 站点：

- 主页：最新合并报告 `index.html`
- 数据：`/data/merged_signal.json`
- 数据：`/data/erp_signal.json`
- 数据：`/data/relative_signal.json`

这样日常查看时可以直接访问固定 URL，而不需要每次手动下载 Actions artifact。

## 本地实验区

实验区默认只在本地使用，不进入主 workflow，也不发布到 GitHub Pages。

本地试验方式：

```bash
cd .claude/skills/index-compare
python scripts/generate_report.py --mode lab --data data/processed_data.csv --conclusions data/conclusions.json --output reports_lab
```

约定：

- 新想法先在本地 `lab` 模式验证
- 确认稳定后，再合并到正式报告与线上 workflow

## 🧹 临时文件管理

### 自动清理

主程序启动时会自动检查并清理临时文件：
- **触发条件**：`tmpclaude-*` 文件数量 ≥ 20 个
- **清理范围**：整个项目目录（包括所有子目录）

### 手动清理

```bash
# 强制清理所有临时文件
python scripts/cleanup.py --force

# 自定义阈值
python scripts/cleanup.py --max 10
```

## ⚠️ 注意事项

1. **数据来源**：数据来自 Tushare，需要有效的 API Token
2. **网络要求**：需要稳定的网络连接以获取数据和加载 Plotly CDN
3. **数据频率**：建议每日收盘后运行一次，获取最新数据
4. **历史数据**：默认获取2015年至今的全部历史数据
5. **免责声明**：本工具仅供参考，不构成投资建议

## 📝 版本历史

### v1.0.2 (2026-03-26)
- ✨ 单页合并报告继续优化：首屏聚焦股权溢价，价格走势与比价关系层次更清晰
- ✨ 首屏总览图修复为使用 ERP 全历史数据，覆盖 2006 年至今
- 🔧 页面文案更新为“大宽基指数比价系统”

### v1.0.1 (2026-03-24)
- ✨ `merged_signal.json` 升级为统一消费入口
- ✨ HTML 报告升级为单页合并布局
- 🔧 报告优先读取 merged signal，降低下游消费复杂度

### v1.0.0 (2026-03-24)
- ✨ 新增顶层 orchestrator：支持统一运行 ERP 与 CSI300 Relative
- ✨ 引入标准共享接口：降低跨项目隐式耦合
- ✨ 新增主调度 workflow：以当前仓库为线上统一入口
- 🔧 单项目 workflow 调整为手动触发：避免线上双重定时

### v0.3.0 (2026-02-24)
- ✨ 新增智能增量更新功能：自动检测本地数据与远程数据状态
- ✨ 新增 --force 参数：支持强制完整更新所有历史数据
- ✨ 优化运行速度：数据已是最新时跳过获取，直接计算
- 🔧 修复数据更新检测问题：确保获取最新交易日数据

### v0.2.0 (2026-02-12)
- ✨ 新增自动清理临时文件功能
- 🎨 优化图表分位数标注位置（下方中央）
- 🔧 修复红绿虚线位置，精准匹配显示范围
- 📏 增加图表高度和底部边距
- 🔧 修复 Plotly 图表加载问题
- 📝 添加 .gitignore 配置

### v0.1.0 (2026-01-30)
- 🎉 初始版本发布
- 📊 实现完整的指数比价分析流程
- 🤖 集成 AI 智能分析
- 🎨 生成交互式 HTML 报告

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 👤 作者

keycool

## 🔗 相关链接

- [Tushare 官网](https://tushare.pro/)
- [Plotly 文档](https://plotly.com/python/)
- [项目仓库](https://github.com/keycool/index-compare-analysis)

---

**💡 提示**：如果觉得这个项目有帮助，欢迎 Star ⭐
