---
name: equity-risk-premium-execution
description: Use this skill when the user wants to run, inspect, tune, or explain the ERP execution workflow that combines ERP, CSI300 relative signals, 300价值/300成长 style tilt, Feishu Bitable holdings, and the human-readable ERP daily summary. Trigger for requests about ERP execution plans, ERP日报, ERP配置, ERP持仓映射, ERP调仓建议, or syncing the latest ERP execution outputs.
---

# Equity Risk Premium Execution

This skill is for the execution layer of the ERP strategy, not just the raw ERP signal.

Use it when the user wants to:

- generate the latest ERP execution plan
- inspect or tune the ERP execution config
- explain why the current ERP plan suggests certain buys or sells
- review ERP-tagged holdings from Feishu `β|α`
- regenerate the ERP daily summary
- sync the latest ERP execution outputs

## Core files

- Execution script: [erp_execution.py](D:/CC/index-compare-analysis/orchestrator/erp_execution.py)
- Config: [erp_execution_config.json](D:/CC/index-compare-analysis/orchestrator/erp_execution_config.json)
- Config guide: [erp_execution_config.md](D:/CC/index-compare-analysis/orchestrator/erp_execution_config.md)
- Daily summary renderer: [render_erp_daily_summary.py](D:/CC/index-compare-analysis/orchestrator/render_erp_daily_summary.py)
- Latest execution plan output: [erp_execution_plan.json](D:/CC/index-compare-analysis/orchestrator/output/erp_execution_plan.json)
- Latest daily summary output: [erp_daily_summary.md](D:/CC/index-compare-analysis/orchestrator/output/erp_daily_summary.md)

## Typical commands

Generate the latest ERP execution plan:

```powershell
py D:\CC\index-compare-analysis\orchestrator\erp_execution.py
```

Render the latest ERP daily summary from the current execution plan:

```powershell
py D:\CC\index-compare-analysis\orchestrator\render_erp_daily_summary.py
```

Sync the latest local relative data into Feishu Bitable without refetching market data:

```powershell
py D:\CC\index-compare-analysis\orchestrator\sync_existing_relative_to_bitable.py
```

Push the latest ERP daily summary to Feishu webhook:

```powershell
py D:\CC\index-compare-analysis\orchestrator\push_erp_daily_summary_to_feishu.py
```

## Workflow summary

The execution layer combines four inputs:

1. ERP base
2. CSI300 relative base
3. `β|α` holdings marked as `ERP`
4. local `300价值 / 300成长` style signal

It then produces:

- total aggressive vs defensive sleeve split from ERP percentile
- internal tilt from `500 / 1000 / 创业板 / 50` recommendations
- value-vs-growth style tilt from `300价值 / 300成长`
- target amounts, deltas, and buy/sell suggestions
- a human-readable daily summary

## Parameter tuning order

When the user wants to tune behavior, prefer this order:

1. `aggressive_weights`
2. `recommendation_multipliers`
3. `value_style_tilt`
4. `growth_style_tilt`
5. `holding_alias_map`
6. `ignored_erp_holdings`

Read the config guide before changing tuning logic:

- [erp_execution_config.md](D:/CC/index-compare-analysis/orchestrator/erp_execution_config.md)

## Feishu mapping notes

The execution layer depends on:

- ERP base
- CSI300 relative base
- asset allocation base `β|α`

If the user asks about missing holdings or wrong mapping:

1. inspect `holding_alias_map`
2. inspect `ignored_erp_holdings`
3. compare with current `β|α` rows tagged `ERP`

## Output expectations

After running the execution script, expect:

- [erp_execution_plan.json](D:/CC/index-compare-analysis/orchestrator/output/erp_execution_plan.json)
- [erp_daily_summary.md](D:/CC/index-compare-analysis/orchestrator/output/erp_daily_summary.md)

If webhook env vars are configured, you can additionally push the daily summary:

- `ERP_DAILY_FEISHU_WEBHOOK_URL`
- `ERP_DAILY_FEISHU_WEBHOOK_SECRET`

Fallbacks are:

- `ERP_FEISHU_WEBHOOK_URL`
- `ERP_FEISHU_WEBHOOK_SECRET`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_WEBHOOK_SECRET`

For a quick interpretation, summarize:

- ERP percentile
- aggressive/defensive split
- relative recommendations
- `300价值 / 300成长` status
- top rebalance actions
