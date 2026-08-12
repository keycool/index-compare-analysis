import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "erp-execution-cloud.yml"


class ErpExecutionWorkflowDefaultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_cloud_workflow_defaults_to_research_mode(self):
        text = self.workflow_text

        self.assertIn('default: "research"', text)
        self.assertIn(
            "ERP_EXECUTION_MODE: ${{ github.event_name == 'repository_dispatch' && 'research' || inputs.execution_mode || 'research' }}",
            text,
        )
        self.assertNotIn("ERP_EXECUTION_MODE: ${{ inputs.execution_mode || 'rebalance' }}", text)

    def test_monthly_schedule_avoids_top_of_hour(self):
        text = self.workflow_text

        self.assertIn("# 09:13 Asia/Shanghai on the 13th and 28th of every month.", text)
        self.assertIn('- cron: "13 1 13 * *"', text)
        self.assertIn('- cron: "13 1 28 * *"', text)
        self.assertNotIn('- cron: "0 1 13 * *"', text)
        self.assertNotIn('- cron: "0 1 28 * *"', text)

    def test_monthly_draft_requires_previous_trading_day_signal(self):
        text = self.workflow_text

        self.assertIn("https://keycool.github.io/index-compare-analysis/data/merged_signal.json", text)
        self.assertNotIn("https://index-compare-analysis.vercel.app/data/merged_signal.json", text)
        self.assertIn("TUSHARE_TOKEN: ${{ secrets.TUSHARE_TOKEN }}", text)
        self.assertIn('"trade_cal"', text)
        self.assertIn("required_signal_date", text)
        self.assertIn('strict_signal_gate = event_name in ("schedule", "repository_dispatch") or push_summary', text)
        self.assertIn("parse_signal_date", text)
        self.assertIn("max_record_date", text)
        self.assertIn("ERP record max date", text)
        self.assertIn("stale: {erp_age_days} days > 14", text)
        self.assertIn("Relative record max date", text)
        self.assertIn("must equal required previous trading day", text)
        self.assertIn("refusing to push ERP draft", text)
        self.assertIn("refusing unverified Feishu fallback", text)
        self.assertIn('strategy_state.get("schema_version") != 1', text)
        self.assertIn('derived_from_relative_history', text)


if __name__ == "__main__":
    unittest.main()
