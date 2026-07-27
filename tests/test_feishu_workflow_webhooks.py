import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ERP_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "erp-execution-cloud.yml"
RELATIVE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "erp-relative-master-scheduler.yml"


class FeishuWorkflowWebhookTest(unittest.TestCase):
    def test_erp_and_relative_workflows_use_separate_webhook_secrets(self):
        erp_text = ERP_WORKFLOW.read_text(encoding="utf-8")
        relative_text = RELATIVE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("ERP_DAILY_FEISHU_WEBHOOK_URL: ${{ secrets.ERP_DAILY_FEISHU_WEBHOOK_URL }}", erp_text)
        self.assertIn("ERP_DAILY_FEISHU_WEBHOOK_SECRET: ${{ secrets.ERP_DAILY_FEISHU_WEBHOOK_SECRET }}", erp_text)

        self.assertIn("CSI_FEISHU_WEBHOOK_URL: ${{ secrets.CSI_FEISHU_WEBHOOK_URL }}", relative_text)
        self.assertIn("CSI_FEISHU_WEBHOOK_SECRET: ${{ secrets.CSI_FEISHU_WEBHOOK_SECRET }}", relative_text)
        self.assertIn("CSI_FEISHU_WEBHOOK_KEYWORD: \u6307\u6570\u6bd4\u4ef7\u5206\u6790", relative_text)
        self.assertNotIn("CSI_FEISHU_WEBHOOK_URL: ${{ secrets.ERP_DAILY_FEISHU_WEBHOOK_URL", relative_text)
        self.assertNotIn("CSI_FEISHU_WEBHOOK_SECRET: ${{ secrets.ERP_DAILY_FEISHU_WEBHOOK_SECRET", relative_text)

    def test_relative_workflow_archives_legacy_erp_table_without_blocking(self):
        relative_text = RELATIVE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('DISABLE_BITABLE_SYNC: "true"', relative_text)
        self.assertIn('REQUIRE_BITABLE_SYNC: "false"', relative_text)
        self.assertIn("Optional archive ERP signal to Feishu table", relative_text)
        self.assertIn("continue-on-error: true", relative_text)
        self.assertIn("ERP_ARCHIVE_FEISHU_APP_TOKEN: O9VFbTbHZafm5psq6ebcGgF7neD", relative_text)
        self.assertIn("ERP_ARCHIVE_FEISHU_TABLE_ID: tble1VwP4HNtMNm2", relative_text)
        self.assertNotIn("ERP_LEGACY_FEISHU_APP_TOKEN: ${{ secrets.ERP_LEGACY_FEISHU_APP_TOKEN }}", relative_text)
        self.assertNotIn("ERP_FEISHU_APP_TOKEN: ${{ secrets.ERP_FEISHU_APP_TOKEN }}", relative_text)
        self.assertIn("ERP_ARCHIVE_START_DATE: \"2026-07-01\"", relative_text)
        self.assertIn("ERP_ARCHIVE_UPDATE_EXISTING: \"false\"", relative_text)
        self.assertIn("ERP_ARCHIVE_REQUIRE_SUCCESS: \"false\"", relative_text)
        self.assertIn(
            "python csi300-relative-index/orchestrator/sync_erp_signal_to_feishu.py",
            relative_text,
        )
        self.assertNotIn("run: python orchestrator/sync_erp_signal_to_feishu.py", relative_text)


if __name__ == "__main__":
    unittest.main()
