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

## 4. A 股进攻仓金额规则

中证500、中证1000、创业板、科创50只在 A 股权益水位以内争取进攻机会预算；它们不会改变 ERP 决定的总权益仓位。

```text
进攻机会池 = 标准单位 × A股权益部署比例 × 进攻仓比例 × 进攻机会预算比例
单标的原始分数 = 基础权重 × 比价建议乘数 × 轨迹乘数 × 准入状态
单标的目标金额 = 进攻机会池 × 单标的原始分数 / 合格标的原始分数之和
```

“准入状态”包含强制退出和重入闸门；不合格标的权重为零。个别标的和组合上限在轨迹乘数之后再次执行，未被进攻仓使用的额度按现有残差逻辑回流沪深300，若沪深300也达到核心上限则进入现金/低风险层。

| 标的 | 基础权重 | 单标的硬上限 | 策略定位 |
|---|---:|---:|---|
| 中证500 | 0.30 | 10% | 宽基中盘进攻仓 |
| 中证1000 | 0.25 | 8% | 小盘补充仓 |
| 创业板 | 0.50 | 10% | 主成长进攻仓 |
| 科创50 | 0.45 | 8% | 高弹性科技进攻仓 |
| 创业板 + 科创50 | - | 14% 合计 | 防止成长科技同向拥挤 |

基础权重只决定合格进攻标的之间的相对份额，不是固定总仓位。相对比价首先决定标的是否具备进入机会池的资格；创业板/上证50、科创50/上证50、中证1000/中证500等特色比价只用于在合格标的之间作倾斜，不得单独突破 ERP 权益水位或上述硬上限。

主锚定与特色比价的职责固定如下：

| 标的 | 主锚定信号：决定是否准入 | 特色比价：只作二次倾斜 |
|---|---|---|
| 上证50 | 上证50 / 沪深300 | 创业板 / 上证50、科创50 / 上证50 |
| 创业板 | 创业板 / 沪深300 | 创业板 / 上证50 |
| 科创50 | 科创50 / 沪深300 | 科创50 / 上证50 |
| 中证500 | 中证500 / 沪深300 | 中证1000 / 中证500 |
| 中证1000 | 中证1000 / 沪深300 | 中证1000 / 中证500 |

主锚定为“低配”或“强烈低配”时，该标的不进入机会池，目标权重为零；“标配”及以上才可参与。特色比价只在一对标的都通过主锚定时生效，并以 `0.90` 至 `1.10` 的温和乘数调整分数。多个特色信号取平均，不连乘；因此它们无法单独制造配置资格，也不会双重放大风险。

## 5. 输出检查

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

## 6. 监控接口

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

监测快照使用 `monitor_schema_version = 2`。`reference_allocations[]` 会发送全部非现金策略桶，包含目标权重、标准金额、`anchor_signal_key`、`anchor_signal`、`anchor_eligible`、`feature_tilt_multiplier`、`feature_tilts`、`allocation_score`、强制退出、重入闸门和轨迹状态。目标权重为零的桶也会保留，便于监测端区分“未覆盖”与“主锚定不准入”。

`signals.relative` 仅包含策略审计所需的最新日期、建议、建议来源和分位数据；快照不包含飞书凭据、表 token、实际持仓行或实际账户金额。

外部监测端接入实际资产时，建议使用独立的实际组合消息或数据源，至少包含：

- `observed_at`：实际持仓快照时间。
- `total_amount`：实际总资产。
- `currency`：资产计价币种。
- `positions`：实际标的、金额和权重。

监测端以 `target_weight` 和 `reference_amount` 作为策略目标进行换算、偏离检测和执行控制；不得把 `total_amount` 或实际仓位回写为 ERP 策略的容量约束。

### Local ERP asset archive

Before a manual ERP workflow run, the operator may capture the current ERP-tagged Feishu holdings as a read-only local archive. The standard path is:

```text
orchestrator/output/asset-snapshots/erp-assets-<YYYY-MM-DDTHHmmss+0800>.json
```

The archive directory is ignored by Git. It is not uploaded as a GitHub artifact, posted to the monitor webhook, or used as a strategy input. Its purpose is to preserve the observed ERP holding rows before a run and make them available to a monitor that shares the same local filesystem.

The JSON contract is intentionally small: `snapshot_type`, `captured_at`, `source.table_id`, `field_map`, `selection`, and `records[]`. Every record contains `record_id`, `item`, `source`, `amount`, `tier_iii`, and `tier_i`; `selection.tier_iii` must be `ERP`. Consumers should use `captured_at` as the observation time, validate `selection.record_count` against `records.length`, and treat the data as audit evidence only.

An off-machine monitor cannot fetch this ignored local file. It must retain its own authenticated portfolio snapshot using the `observed_at`, `total_amount`, `currency`, and `positions` contract above.

监控接口是非阻断设计：

- 未配置 `ERP_MONITOR_WEBHOOK_URL` 时自动跳过。
- 推送失败只打印 warning，不影响日报生成、飞书推送或 artifacts 上传。

## 7. 故障处理顺序

1. **工作流失败**：先看 GitHub Actions 中 `Run ERP execution workflow` 的异常。
2. **数据门禁失败**：看 `signals.data_health.errors`，重点检查 ERP、Relative、持仓日期。
3. **仓位不符合预期**：看 `portfolio_deployment` 的分位水位和 `core_caps`。
4. **沪深300过高**：检查 `positions` 里 `hs300.core_cap` 和 `cap_released_to_cash`。
5. **现金层不出现**：确认 `portfolio_deployment.enabled = true`，并确认工作流使用的是最新代码。
6. **监控没有数据**：检查 `ERP_MONITOR_WEBHOOK_URL` 是否配置，接口是否接受 JSON POST。

## 8. 修改参数时的保守顺序

优先改配置，不先改算法：

1. 调整 `portfolio_deployment.ashare.breakpoints`。
2. 调整 `portfolio_deployment.core_caps.hs300.breakpoints`。
3. 调整 `cross_market.hk_pool_cap`。
4. 调整 `alpha_base_weights`、`alpha_bucket_caps` 和 `alpha_group_caps`。
5. 最后才改执行代码。

每次修改后至少运行：

```powershell
python -m unittest tests.test_erp_execution_cloud_logic
```

## 9. 外部监测端触发策略刷新

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
