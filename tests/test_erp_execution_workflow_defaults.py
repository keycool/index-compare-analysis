import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "erp-execution-cloud.yml"


class ErpExecutionWorkflowDefaultsTest(unittest.TestCase):
    def test_cloud_workflow_defaults_to_research_mode(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn('default: "research"', text)
        self.assertIn("ERP_EXECUTION_MODE: ${{ inputs.execution_mode || 'research' }}", text)
        self.assertNotIn("ERP_EXECUTION_MODE: ${{ inputs.execution_mode || 'rebalance' }}", text)


if __name__ == "__main__":
    unittest.main()
