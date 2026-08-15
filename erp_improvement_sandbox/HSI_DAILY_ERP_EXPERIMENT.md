# 恒生日频 ERP 本地实验

## 目的

在不影响 ERP 主程序的前提下，验证半年日频恒生 ERP 数据能否稳定生成。

## 数据口径

- 恒生指数收盘价：Tushare `index_global`；官方 `idx` 每日报告可用时以官方收盘覆盖。
- 恒生指数 PE：官方 `idx` 每日报告可用时使用官方日 PE。
- 较早日期 PE：使用当时已经公布的恒生官方月末 PE 与恒指收盘价做因果推算。
- 美国10年期国债收益率：美国财政部 Daily Treasury Par Yield Curve Rates。
- 计算：`恒生 ERP = 100 / 恒生 PE - 美国10年期国债收益率`。
- 每个恒生交易日只使用当天或更早的月末 PE 锚点和美债数据，不使用未来数据。
- 每条记录通过 `hsi_pe_source_type` 区分 `official_daily` 与 `derived_from_official_monthly`。

## 本地运行

```powershell
.\.venv\Scripts\python.exe erp_improvement_sandbox\hsi_daily_erp_experiment.py
```

默认生成最近6个月。首次运行若缺少实验依赖：

```powershell
uv pip install --python .\.venv\Scripts\python.exe -r erp_improvement_sandbox\requirements-hsi-experiment.txt
```

可将实验窗口改为3个月：

```powershell
.\.venv\Scripts\python.exe erp_improvement_sandbox\hsi_daily_erp_experiment.py --lookback-months 3
```

输出位置：

```text
erp_improvement_sandbox/outputs/hsi_daily_erp_experiment/
```

其中 JSON 是监测接口候选格式，CSV 用于人工检查和后续误差分析。运行前需要在本机临时设置 `TUSHARE_TOKEN`。

## 生产隔离

- 输出包含 `experiment_only: true` 和 `production_consumable: false`。
- 不写入 `shared/`、飞书或任何 ERP 正式输出目录。
- 不修改或导入 `erp_execution_cloud.py`。
- 不接入 GitHub Actions、网页、机器人推送或监测端。
- 当前实验结果不得用于真实仓位配置。

推算部分不是恒生官方日 PE，不能与 `official_daily` 混淆。只有在数据连续性、过期门禁和历史验证完成后，才单独评估是否建立正式接口。
