# Workflow Entrypoints

这份文档是仓库里的固定查询入口。

以后如果你想快速回答这些问题，先看这里：

- 这两个 workflow 的主入口在哪
- 它们各自读取什么数据
- 它们怎么生成结果
- 出问题先查哪几个文件

---

## 1. 两条主 workflow

### A. 主生产流

文件：

- [erp-relative-master-scheduler.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-relative-master-scheduler.yml)

职责：

- 运行 `ERP + Relative` 主生产链路
- 生成共享信号
- 构建站点
- 部署 GitHub Pages / Vercel

你想看这些问题时，从它开始：

- 网站为什么没更新
- Relative 主报告怎么生成
- ERP 与 Relative 怎么合并
- Vercel / Pages 为什么坏了

对应主代码入口：

- [orchestrator/main.py](/D:/CC/index-compare-analysis/orchestrator/main.py)

---

### B. 月度执行流

文件：

- [erp-execution-cloud.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-execution-cloud.yml)

职责：

- 读取飞书三张表
- 生成 ERP 执行计划
- 生成 ERP 日报
- 推送月度执行摘要到飞书

你想看这些问题时，从它开始：

- ERP 执行层现在怎么配仓
- 为什么这次建议减创业板 / 加 50 / 加 500 / 加 1000
- 月中 / 月底执行日报怎么来的
- 飞书机器人推送为什么失败

对应说明文档：

- [erp_execution_cloud_workflow.md](/D:/CC/index-compare-analysis/orchestrator/erp_execution_cloud_workflow.md)

---

## 2. 主生产流代码地图

### 总调度入口

- [main.py](/D:/CC/index-compare-analysis/orchestrator/main.py)

它负责：

- 调 ERP 外部仓库主脚本
- 调 Relative 主脚本
- 合并成 `merged_signal.json`

### Relative 主入口

- [.claude/skills/index-compare/scripts/main.py](/D:/CC/index-compare-analysis/.claude/skills/index-compare/scripts/main.py)

它负责：

- 拉指数数据
- 计算比价 / 分位 / 偏离
- 生成 conclusions / shared signal
- 输出 Excel / HTML
- 同步飞书 Base

### Relative 关键逻辑

- 数据抓取：[fetch_data.py](/D:/CC/index-compare-analysis/.claude/skills/index-compare/scripts/fetch_data.py)
- 指标计算：[calculate.py](/D:/CC/index-compare-analysis/.claude/skills/index-compare/scripts/calculate.py)
- 结论生成：[analyze.py](/D:/CC/index-compare-analysis/.claude/skills/index-compare/scripts/analyze.py)
- 报告渲染：[generate_report.py](/D:/CC/index-compare-analysis/.claude/skills/index-compare/scripts/generate_report.py)

### 主生产流产物

- Relative 信号：[relative_signal.json](/D:/CC/shared/relative_signal.json)
- ERP 信号：[erp_signal.json](/D:/CC/shared/erp_signal.json)
- 合并信号：[merged_signal.json](/D:/CC/shared/merged_signal.json)
- Relative Excel：[index_compare_enhanced.xlsx](/D:/CC/index-compare-analysis/index_compare_enhanced.xlsx)
- Relative HTML 报告目录：[reports](/D:/CC/index-compare-analysis/reports)

---

## 3. 月度执行流代码地图

### 云端执行入口

- [run_erp_execution_cloud.py](/D:/CC/index-compare-analysis/orchestrator/run_erp_execution_cloud.py)

它负责：

- 跑云端执行计划脚本
- 按需要调用飞书推送

### 云端执行主逻辑

- [erp_execution_cloud.py](/D:/CC/index-compare-analysis/orchestrator/erp_execution_cloud.py)

它负责：

- 用 Feishu OpenAPI 读取三张表
- 计算 ERP 百分位
- 结合 Relative 建议
- 结合 300价值 / 成长信号
- 生成目标权重 / 调仓计划

### 执行层配置

- 配置文件：[erp_execution_config.json](/D:/CC/index-compare-analysis/orchestrator/erp_execution_config.json)
- 配置说明：[erp_execution_config.md](/D:/CC/index-compare-analysis/orchestrator/erp_execution_config.md)

### 日报与推送

- 日报渲染：[render_erp_daily_summary.py](/D:/CC/index-compare-analysis/orchestrator/render_erp_daily_summary.py)
- 飞书推送：[push_erp_daily_summary_to_feishu.py](/D:/CC/index-compare-analysis/orchestrator/push_erp_daily_summary_to_feishu.py)

### 月度执行流产物

- 执行计划：[erp_execution_plan.json](/D:/CC/index-compare-analysis/orchestrator/output/erp_execution_plan.json)
- 日报摘要：[erp_daily_summary.md](/D:/CC/index-compare-analysis/orchestrator/output/erp_daily_summary.md)

---

## 4. 数据来源总表

### 主生产流

- Tushare
- 飞书 Base
- 外部 ERP 仓库

### 月度执行流

- ERP Base
- CSI300 relative Base
- 资产配置 Base `β|α`

注意：

- 月度执行流不抓 Tushare
- 月度执行流只消费飞书里已经同步好的数据

---

## 5. 快速排障入口

### 网站 404 / 页面没更新

先看：

- [erp-relative-master-scheduler.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-relative-master-scheduler.yml)

重点步骤：

- `Build Pages site`
- `Deploy to Vercel`

### 月度执行日报没生成

先看：

- [erp-execution-cloud.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-execution-cloud.yml)
- [run_erp_execution_cloud.py](/D:/CC/index-compare-analysis/orchestrator/run_erp_execution_cloud.py)

### 飞书推送失败

先看：

- [push_erp_daily_summary_to_feishu.py](/D:/CC/index-compare-analysis/orchestrator/push_erp_daily_summary_to_feishu.py)

重点检查：

- `ERP_DAILY_FEISHU_WEBHOOK_URL`
- `ERP_DAILY_FEISHU_WEBHOOK_SECRET`
- Actions 日志里的 `[PUSH]` 行

### 执行建议看起来不合理

先看：

- [erp_execution_cloud.py](/D:/CC/index-compare-analysis/orchestrator/erp_execution_cloud.py)
- [erp_execution_config.json](/D:/CC/index-compare-analysis/orchestrator/erp_execution_config.json)

重点检查：

- `aggressive_weights`
- `alpha_budget_weights`
- `aggressive_reentry_percentiles`
- `recommendation_multipliers`
- `alpha_base_weights`
- `alpha_bucket_caps`

---

## 6. 推荐阅读顺序

如果你只是想快速恢复上下文，建议这样看：

1. [WORKFLOW_ENTRYPOINTS.md](/D:/CC/index-compare-analysis/WORKFLOW_ENTRYPOINTS.md)
2. [erp-relative-master-scheduler.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-relative-master-scheduler.yml)
3. [main.py](/D:/CC/index-compare-analysis/orchestrator/main.py)
4. [erp-execution-cloud.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-execution-cloud.yml)
5. [erp_execution_cloud_workflow.md](/D:/CC/index-compare-analysis/orchestrator/erp_execution_cloud_workflow.md)
6. [erp_execution_config.md](/D:/CC/index-compare-analysis/orchestrator/erp_execution_config.md)

---

## 7. 一句话区分

主生产流：

- “生成市场数据、报告、站点、共享信号”

月度执行流：

- “消费现成数据，生成 ERP 执行建议和日报”
