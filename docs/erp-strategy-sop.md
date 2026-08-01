# ERP 策略执行 SOP

本文档说明 ERP 策略在 `erp-execution-cloud` 工作流中的运行口径、手动运行方式、监控接口配置和故障处理顺序。

## 1. 策略定位

ERP 策略分两层：

1. **总权益水位**：由沪深300 ERP 和恒生指数 ERP 决定 A 股、港股权益仓位上限。
2. **权益内部分配**：在权益水位之内，再用比价系统决定沪深300、上证50、300价值/成长、中证500、中证1000、创业板、科创50、恒生科技等标的的相对配置。

关键原则：

- ERP 决定能不能提高权益总仓位。
- 比价决定权益仓位流向哪里。
- 当 ERP 下行时，所有权益标的的总水位都要下降，资金进入现金/低风险层。
- 比价信号不能单独抬高总权益仓位。
- 沪深300是核心锚，但不是无限残差桶；超过核心上限的资金进入现金/低风险层。

## 2. 默认仓位水位

配置位于 `orchestrator/erp_execution_config.json` 的 `portfolio_deployment`。

A 股默认水位：

| 沪深300 ERP 分位 | A 股权益水位 |
|---:|---:|
| 0% | 5% |
| 20% | 15% |
| 40% | 35% |
| 60% | 50% |
| 70% | 65% |
| 80% | 85% |
| 100% | 100% |

沪深300核心上限：

| 沪深300 ERP 分位 | 沪深300上限 |
|---:|---:|
| 0% | 8% |
| 20% | 12% |
| 40% | 25% |
| 60% | 35% |
| 80% | 40% |
| 100% | 45% |

港股由恒生指数 ERP 单独控制，并受 `cross_market.hk_pool_cap` 约束。当前默认港股总上限为 20%。如果恒生 ERP 不可用，不新增港股敞口，只保留或压缩已有港股敞口。

## 3. 手动运行

本地生成 ERP 执行计划：

```powershell
python orchestrator/run_erp_execution_cloud.py --execution-mode research
```

按总可投资资金运行，例如 100 万：

```powershell
python orchestrator/run_erp_execution_cloud.py --execution-mode research --total-capital 1000000
```

正式调仓模式：

```powershell
python orchestrator/run_erp_execution_cloud.py --execution-mode rebalance --total-capital 1000000 --push-summary
```

GitHub Actions 手动运行时，可以填写 `total_capital`。如果不填写，系统使用当前 ERP 映射持仓金额作为容量。

## 4. 输出检查

主要产物：

- `orchestrator/output/erp_execution_plan.json`
- `orchestrator/output/erp_daily_summary.md`

重点字段：

- `portfolio.ashare_pool`：A 股权益目标占总资金比例。
- `portfolio.hkshare_pool`：港股权益目标占总资金比例。
- `portfolio.reserve_pool`：现金/低风险目标占总资金比例。
- `portfolio.current_equity_amount`：当前已识别 ERP 权益持仓。
- `portfolio.current_cash_amount`：总资金减去当前权益持仓后的现金/低风险估算。
- `positions[].bucket == "cash"`：现金/低风险目标仓。
- `signals.data_health.errors`：正式调仓阻断项。
- `signals.data_health.warnings`：研究模式或非阻断警告。

正式调仓前必须确认：

- `target_weight_sum` 接近 1.0。
- `data_health.errors` 为空。
- 现金层存在且金额符合总权益水位预期。
- 沪深300目标没有超过 `core_caps.hs300` 对应上限。

## 5. 监控接口

工作流会在生成执行计划后尝试推送一份轻量监控快照。

配置 GitHub Secrets：

- `ERP_MONITOR_WEBHOOK_URL`：监控接口 URL。
- `ERP_MONITOR_WEBHOOK_TOKEN`：可选。如果配置，会作为 `Authorization: Bearer <token>` 发送。

监控请求为 `POST application/json`，核心字段包括：

- `signal_type = erp_execution_monitor`
- `generated_at`
- `execution_mode`
- `as_of`
- `ok`
- `errors`
- `warnings`
- `dates`
- `portfolio.ashare_pool`
- `portfolio.hkshare_pool`
- `portfolio.reserve_pool`
- `top_actions`

监控接口是非阻断设计：

- 未配置 `ERP_MONITOR_WEBHOOK_URL` 时自动跳过。
- 推送失败只打印 warning，不影响日报生成、飞书推送或 artifacts 上传。

## 6. 故障处理顺序

1. **工作流失败**：先看 GitHub Actions 中 `Run ERP execution workflow` 的异常。
2. **数据门禁失败**：看 `signals.data_health.errors`，重点检查 ERP、Relative、持仓日期。
3. **仓位不符合预期**：看 `portfolio_deployment` 的分位水位和 `core_caps`。
4. **沪深300过高**：检查 `positions` 里 `hs300.core_cap` 和 `cap_released_to_cash`。
5. **现金层不出现**：确认 `portfolio_deployment.enabled = true`，并确认工作流使用的是最新代码。
6. **监控没有数据**：检查 `ERP_MONITOR_WEBHOOK_URL` 是否配置，接口是否接受 JSON POST。

## 7. 修改参数时的保守顺序

优先改配置，不先改算法：

1. 调整 `portfolio_deployment.ashare.breakpoints`。
2. 调整 `portfolio_deployment.core_caps.hs300.breakpoints`。
3. 调整 `cross_market.hk_pool_cap`。
4. 调整 `alpha_bucket_caps`。
5. 最后才改执行代码。

每次修改后至少运行：

```powershell
python -m unittest tests.test_erp_execution_cloud_logic
```
