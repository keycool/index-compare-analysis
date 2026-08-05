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

策略固定以 `strategy_reference.notional = 1000000`（CNY）作为标准容量，输出目标权重及对应的标准金额。该 100 万只是统一标尺，不是实际可投资金额，也不会由 GitHub Actions 输入或实际持仓金额覆盖。

```powershell
python orchestrator/run_erp_execution_cloud.py --execution-mode research
```

实际总资产、实际仓位、实际买卖差额和账户级风控由外部监测端负责。ERP 策略不生成可直接执行的真实金额调仓单。

## 4. 输出检查

主要产物：

- `orchestrator/output/erp_execution_plan.json`
- `orchestrator/output/erp_daily_summary.md`

重点字段：

- `portfolio.ashare_pool`：A 股权益目标占总资金比例。
- `portfolio.hkshare_pool`：港股权益目标占总资金比例。
- `portfolio.reserve_pool`：现金/低风险目标占总资金比例。
- `portfolio.reference_notional`：固定的策略标准容量，默认 1,000,000 CNY。
- `positions[].reference_amount`：按标准容量折算的参考金额。
- `portfolio.actual_allocation_owner`：实际资产配置责任方，默认 `external_monitor`。
- `positions[].bucket == "cash"`：现金/低风险目标权重。
- `signals.data_health.errors`：正式调仓阻断项。
- `signals.data_health.warnings`：研究模式或非阻断警告。

策略结果使用前必须确认：

- `target_weight_sum` 接近 1.0。
- `data_health.errors` 为空。
- 现金层权重符合总权益水位预期。
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
- `portfolio.strategy_reference_notional`
- `portfolio.ashare_pool`
- `portfolio.hkshare_pool`
- `portfolio.reserve_pool`
- `reference_allocations`
- `actual_allocation_contract`

外部监测端接入实际资产时，建议使用独立的实际组合消息或数据源，至少包含：

- `observed_at`：实际持仓快照时间。
- `total_amount`：实际总资产。
- `currency`：资产计价币种。
- `positions`：实际标的、金额和权重。

监测端以 `target_weight` 和 `reference_amount` 作为策略目标进行换算、偏离检测和执行控制；不得把 `total_amount` 或实际仓位回写为 ERP 策略的容量约束。

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

## 8. 外部监测端触发策略刷新

外部监测端可以调用 GitHub `repository_dispatch` 事件 `erp_monitor_refresh`，触发一次 ERP 标准配置刷新。该入口固定使用 `research` 模式、严格校验最新市场信号，并且不会推送飞书摘要；它只会生成标准容量计划并回传监控快照。

外部端需要一个仅授权给 `keycool/index-compare-analysis` 的 fine-grained PAT，权限为 `Contents: write`。令牌只保存在监测端，不写入仓库或 workflow。

```bash
curl -L -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${ERP_GITHUB_DISPATCH_TOKEN}" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  https://api.github.com/repos/keycool/index-compare-analysis/dispatches \
  -d '{"event_type":"erp_monitor_refresh","client_payload":{"request_id":"monitor-20260805-001"}}'
```

成功时 GitHub 返回 `204 No Content`。监测端随后通过既有 `ERP_MONITOR_WEBHOOK_URL` 接收快照；快照中的 `trigger.request_id` 与请求中的 `request_id` 一致，便于关联本次请求。实际资产金额仍只由监测端控制，不会传入 ERP 策略。
