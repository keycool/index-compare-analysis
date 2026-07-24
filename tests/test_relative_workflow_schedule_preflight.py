import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "erp-relative-master-scheduler.yml"


class RelativeWorkflowSchedulePreflightTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow_text = WORKFLOW.read_text(encoding="utf-8")

    def test_schedule_runs_weekdays_at_23_shanghai(self):
        self.assertIn('# 15:00 UTC = 23:00 Asia/Shanghai, Monday-Friday.', self.workflow_text)
        self.assertIn('- cron: "0 15 * * 1-5"', self.workflow_text)
        self.assertNotIn('- cron: "0 12 * * *"', self.workflow_text)

    def test_schedule_preflight_requires_trading_day_and_complete_tushare_data(self):
        self.assertIn('MIN_ALL_A_DAILY_ROWS: "5000"', self.workflow_text)
        self.assertIn('"api_name": api_name', self.workflow_text)
        self.assertIn('"trade_cal"', self.workflow_text)
        self.assertIn('"exchange": "SSE"', self.workflow_text)
        self.assertIn('"index_daily"', self.workflow_text)
        self.assertIn('"ts_code": "000300.SH"', self.workflow_text)
        self.assertIn('"daily"', self.workflow_text)
        self.assertIn('all_a_daily_rows >= min_all_a_rows', self.workflow_text)

    def test_schedule_skip_blocks_calculation_and_deploy(self):
        self.assertIn('write_output("should_run", "false")', self.workflow_text)
        self.assertIn("formal calculation, web data update, and Vercel deploy are skipped", self.workflow_text)
        self.assertIn("Deploy to Vercel", self.workflow_text)
        self.assertIn("steps.preflight.outputs.should_run == 'true'", self.workflow_text)
        self.assertIn("needs.run-master-orchestrator.outputs.should_run == 'true'", self.workflow_text)

    def test_master_orchestrator_step_has_timeout(self):
        self.assertIn("- name: Run master orchestrator", self.workflow_text)
        self.assertIn("timeout-minutes: 20", self.workflow_text)


if __name__ == "__main__":
    unittest.main()
