import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "erp-relative-master-scheduler.yml"


class RelativeWorkflowSchedulePreflightTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow_text = WORKFLOW.read_text(encoding="utf-8")

    def test_schedule_runs_weekdays_at_2318_shanghai(self):
        self.assertIn('# 15:18 UTC = 23:18 Asia/Shanghai, Monday-Friday.', self.workflow_text)
        self.assertIn('- cron: "18 15 * * 1-5"', self.workflow_text)
        self.assertNotIn('- cron: "0 12 * * *"', self.workflow_text)
        self.assertNotIn('- cron: "0 15 * * 1-5"', self.workflow_text)

    def test_production_workflow_does_not_run_on_push_or_cancel_schedule(self):
        self.assertNotIn("push:", self.workflow_text)
        self.assertIn("cancel-in-progress: false", self.workflow_text)

    def test_schedule_preflight_requires_trading_day_and_complete_tushare_data(self):
        self.assertIn("LATEST_SIGNAL_URL: https://keycool.github.io/index-compare-analysis/data/merged_signal.json", self.workflow_text)
        self.assertNotIn("LATEST_SIGNAL_URL: https://index-compare-analysis.vercel.app/data/merged_signal.json", self.workflow_text)
        self.assertIn('MIN_ALL_A_DAILY_ROWS: "5000"', self.workflow_text)
        self.assertIn('REQUIRED_INDEX_DAILY_CODES: "000300.SH,000905.SH,000852.SH,399006.SZ,000016.SH,000688.SH,000919.CSI,000918.CSI"', self.workflow_text)
        self.assertIn('REQUIRED_GLOBAL_INDEX_CODES: "HSI,HKTECH"', self.workflow_text)
        self.assertIn('"api_name": api_name', self.workflow_text)
        self.assertIn('"trade_cal"', self.workflow_text)
        self.assertIn('"exchange": "SSE"', self.workflow_text)
        self.assertIn('"index_daily"', self.workflow_text)
        self.assertIn('"index_global"', self.workflow_text)
        self.assertIn('"ts_code": ts_code', self.workflow_text)
        self.assertIn("missing_index_codes", self.workflow_text)
        self.assertIn("missing_global_codes", self.workflow_text)
        self.assertIn('"daily"', self.workflow_text)
        self.assertIn('all_a_daily_rows >= min_all_a_rows', self.workflow_text)
        self.assertNotIn('reason", "non_schedule_event"', self.workflow_text)

    def test_manual_dispatch_can_redeploy_latest_complete_trading_day(self):
        self.assertIn('is_manual = event_name == "workflow_dispatch"', self.workflow_text)
        self.assertIn('"start_date": preflight_window_start', self.workflow_text)
        self.assertIn("target_trade_date = latest_index_dates[-1]", self.workflow_text)
        self.assertIn('reason = "manual_redeploy_existing_data"', self.workflow_text)
        self.assertIn('f"- Target trade date: `{target_trade_date_text}`"', self.workflow_text)

    def test_schedule_preflight_retries_when_data_is_not_ready(self):
        self.assertIn('PREFLIGHT_RETRY_ATTEMPTS: "3"', self.workflow_text)
        self.assertIn('PREFLIGHT_RETRY_SLEEP_SECONDS: "600"', self.workflow_text)
        self.assertIn("attempts = 1 if is_manual else max(1, retry_attempts)", self.workflow_text)
        self.assertIn("time.sleep(retry_sleep_seconds)", self.workflow_text)
        self.assertIn("no_new_tushare_data", self.workflow_text)

    def test_schedule_skip_blocks_calculation_and_deploy(self):
        self.assertIn('write_output("should_run", "false")', self.workflow_text)
        self.assertIn("formal calculation, web data update, and Vercel deploy are skipped", self.workflow_text)
        self.assertIn("Deploy to Vercel", self.workflow_text)
        self.assertIn("steps.preflight.outputs.should_run == 'true'", self.workflow_text)
        self.assertIn("needs.run-master-orchestrator.outputs.should_run == 'true'", self.workflow_text)

    def test_vercel_deploy_verifies_canonical_domain(self):
        self.assertIn("VERCEL_CANONICAL_HOST: index-compare-analysis.vercel.app", self.workflow_text)
        self.assertIn("VERCEL_CANONICAL_URL: https://index-compare-analysis.vercel.app", self.workflow_text)
        self.assertIn("npm install --global vercel@50.28.0", self.workflow_text)
        self.assertIn('vercel alias set "$DEPLOY_URL" "$VERCEL_CANONICAL_HOST"', self.workflow_text)
        self.assertIn('curl -sS -o /tmp/vercel-index.html -w "%{http_code}" "$VERCEL_CANONICAL_URL/"', self.workflow_text)
        self.assertIn('curl -fsS "$VERCEL_CANONICAL_URL/data/merged_signal.json"', self.workflow_text)

    def test_master_orchestrator_step_has_timeout(self):
        self.assertIn("- name: Run master orchestrator", self.workflow_text)
        self.assertIn("timeout-minutes: 20", self.workflow_text)


if __name__ == "__main__":
    unittest.main()
