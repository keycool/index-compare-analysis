Read and follow the execution conventions from these local files before running anything:

- `D:/CC/index-compare-analysis/.agents/skills/equity-risk-premium-execution/SKILL.md`
- `D:/CC/index-compare-analysis/orchestrator/erp_execution_config.md`

This automation is the cloud execution workflow for ERP strategy guidance. It is separate from the market-data master workflow and must consume already-synced Feishu data instead of refetching market data.

Your job:

1. Run the cloud ERP execution wrapper:
   - `python orchestrator/run_erp_execution_cloud.py`
2. Verify these files were updated successfully:
   - `D:/CC/index-compare-analysis/orchestrator/output/erp_execution_plan.json`
   - `D:/CC/index-compare-analysis/orchestrator/output/erp_daily_summary.md`
3. If the environment variable `ERP_EXECUTION_PUSH_SUMMARY` is exactly `true`, rerun with push enabled:
   - `python orchestrator/run_erp_execution_cloud.py --push-summary`
4. Print a concise completion summary that includes:
   - ERP percentile
   - aggressive/defensive split
   - relative recommendations
   - top rebalance actions

Rules:

- Do not edit repository files in this workflow run.
- Do not fetch market data from Tushare.
- Do not deploy pages or Vercel.
- Use the Feishu OpenAPI-backed cloud execution script, not the local lark-cli workflow.
