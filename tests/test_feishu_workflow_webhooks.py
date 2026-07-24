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


if __name__ == "__main__":
    unittest.main()
