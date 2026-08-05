import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "erp-execution-cloud.yml"


class ErpExecutionWorkflowDispatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow_text = WORKFLOW.read_text(encoding="utf-8")

    def test_external_monitor_can_trigger_a_dedicated_repository_dispatch_event(self):
        self.assertIn("repository_dispatch:", self.workflow_text)
        self.assertIn("types: [erp_monitor_refresh]", self.workflow_text)
        self.assertIn('github.event_name == \'repository_dispatch\' && \'research\'', self.workflow_text)
        self.assertIn("ERP_MONITOR_TRIGGER_SOURCE: ${{ github.event_name }}", self.workflow_text)
        self.assertIn("ERP_MONITOR_REQUEST_ID: ${{ github.event.client_payload.request_id || '' }}", self.workflow_text)

    def test_external_monitor_dispatch_does_not_push_feishu_summary(self):
        self.assertIn('elif [ "${{ github.event_name }}" = "workflow_dispatch" ]', self.workflow_text)
        self.assertIn('event_name in ("schedule", "repository_dispatch") or push_summary', self.workflow_text)


if __name__ == "__main__":
    unittest.main()
