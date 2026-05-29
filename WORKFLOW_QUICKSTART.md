# Workflow Quickstart

这是 3 分钟速读版。

如果你以后临时回来，只想快速知道“这仓库现在怎么跑”，先看这页。

## 两条主线

### 1. 主生产流

文件：

- [erp-relative-master-scheduler.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-relative-master-scheduler.yml)

作用：

- 抓 ERP / Relative 数据
- 生成共享信号
- 生成站点
- 部署 Pages / Vercel

主入口：

- [main.py](/D:/CC/index-compare-analysis/orchestrator/main.py)

一句话理解：

- 这是“生产市场数据和网页”的 workflow

---

### 2. 月度执行流

文件：

- [erp-execution-cloud.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-execution-cloud.yml)

作用：

- 读取飞书三张表
- 生成 ERP 执行计划
- 生成 ERP 日报
- 推送飞书

主入口：

- [run_erp_execution_cloud.py](/D:/CC/index-compare-analysis/orchestrator/run_erp_execution_cloud.py)

一句话理解：

- 这是“消费已有数据，给出执行建议”的 workflow

---

## 先看哪里

### 想看网站为什么坏了

先看：

- [erp-relative-master-scheduler.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-relative-master-scheduler.yml)

重点步骤：

- `Build Pages site`
- `Deploy to Vercel`

### 想看 ERP 执行建议怎么来的

先看：

- [erp_execution_cloud.py](/D:/CC/index-compare-analysis/orchestrator/erp_execution_cloud.py)
- [erp_execution_config.json](/D:/CC/index-compare-analysis/orchestrator/erp_execution_config.json)

### 想看飞书推送为什么失败

先看：

- [push_erp_daily_summary_to_feishu.py](/D:/CC/index-compare-analysis/orchestrator/push_erp_daily_summary_to_feishu.py)

重点：

- `ERP_DAILY_FEISHU_WEBHOOK_URL`
- `ERP_DAILY_FEISHU_WEBHOOK_SECRET`

---

## 核心产物

主生产流产物：

- [relative_signal.json](/D:/CC/shared/relative_signal.json)
- [erp_signal.json](/D:/CC/shared/erp_signal.json)
- [merged_signal.json](/D:/CC/shared/merged_signal.json)
- [reports](/D:/CC/index-compare-analysis/reports)

月度执行流产物：

- [erp_execution_plan.json](/D:/CC/index-compare-analysis/orchestrator/output/erp_execution_plan.json)
- [erp_daily_summary.md](/D:/CC/index-compare-analysis/orchestrator/output/erp_daily_summary.md)

---

## 进一步看

完整版入口索引在：

- [WORKFLOW_ENTRYPOINTS.md](/D:/CC/index-compare-analysis/WORKFLOW_ENTRYPOINTS.md)
