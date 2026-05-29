# ERP Execution Cloud Workflow

这份说明对应 GitHub Actions workflow：

- [erp-execution-cloud.yml](/D:/CC/index-compare-analysis/.github/workflows/erp-execution-cloud.yml)

## 作用

这条 workflow 是独立于 `erp-relative-master-scheduler` 的月度执行流。

它的职责只有 4 件事：

- 从飞书读取 ERP、CSI300 relative、资产配置 `β|α` 三张表
- 生成 ERP 执行计划 `erp_execution_plan.json`
- 生成人读版日报 `erp_daily_summary.md`
- 按需要把日报推送到飞书机器人

它不负责：

- 抓取 Tushare 数据
- 更新 Relative 主报告
- 部署 Vercel / Pages

## 运行时间

自动运行：

- 每月 13 号上午 09:00（Asia/Shanghai）
- 每月 28 号上午 09:00（Asia/Shanghai）

手动运行：

- 在 GitHub Actions 里打开 `erp-execution-cloud`
- 点击 `Run workflow`
- 可选勾选 `Push ERP execution summary to Feishu webhook after generation`

## 依赖的 Secrets

飞书应用：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

ERP 表：

- `ERP_EXEC_ERP_APP_TOKEN`
- `ERP_EXEC_ERP_TABLE_ID`

Relative 表：

- `ERP_EXEC_RELATIVE_APP_TOKEN`
- `ERP_EXEC_RELATIVE_TABLE_ID`

资产配置表：

- `ERP_EXEC_ASSET_APP_TOKEN`
- `ERP_EXEC_ASSET_TABLE_ID`

月度日报专用 webhook：

- `ERP_DAILY_FEISHU_WEBHOOK_URL`
- `ERP_DAILY_FEISHU_WEBHOOK_SECRET`

## 关键设计

1. 只认专用月度 webhook

这条 workflow 不再 fallback 到：

- `ERP_FEISHU_WEBHOOK_URL`
- `FEISHU_WEBHOOK_URL`

原因是要避免月度执行流误打到别的机器人。

2. 推送失败时会自动降级

推送逻辑会先发富文本 `post`。

如果飞书因为关键词校验拦截，脚本会自动回退成纯文本摘要再试一次。

3. 中文产物已经按 UTF-8 修正

artifact 里看到的：

- `erp_execution_plan.json`
- `erp_daily_summary.md`

文件本身应是正常中文。

如果终端显示乱码，通常只是控制台编码问题，不代表 artifact 文件坏了。

## 产物位置

GitHub Actions artifact 中应包含：

- `orchestrator/output/erp_execution_plan.json`
- `orchestrator/output/erp_daily_summary.md`

## 常见排障

1. `Missing Feishu webhook URL`

说明没有配置：

- `ERP_DAILY_FEISHU_WEBHOOK_URL`

2. `Key Words Not Found`

先检查：

- 飞书机器人是否真的配置了关键词
- 是否包含 `ERP执行日报`

再看日志里的 `[PUSH]` 行：

- `webhook_source=ERP_DAILY_FEISHU_WEBHOOK_URL`
- `webhook_tail=...`

确认是否打到了你期望的机器人。

3. 只有产物成功，推送失败

这通常说明：

- 读表和执行计划逻辑没问题
- 问题只在 webhook 安全设置

4. 中文显示乱码

优先用这些方式查看 artifact：

- VS Code
- 浏览器
- GitHub 下载后的本地 Markdown 查看器

不要只看 PowerShell 直接输出。

## 相关脚本

- [erp_execution_cloud.py](/D:/CC/index-compare-analysis/orchestrator/erp_execution_cloud.py)
- [run_erp_execution_cloud.py](/D:/CC/index-compare-analysis/orchestrator/run_erp_execution_cloud.py)
- [render_erp_daily_summary.py](/D:/CC/index-compare-analysis/orchestrator/render_erp_daily_summary.py)
- [push_erp_daily_summary_to_feishu.py](/D:/CC/index-compare-analysis/orchestrator/push_erp_daily_summary_to_feishu.py)
