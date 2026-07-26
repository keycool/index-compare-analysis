import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PUSH_SCRIPT = REPO_ROOT / "orchestrator" / "push_erp_daily_summary_to_feishu_v3.py"


class ErpPushSummaryDatesTest(unittest.TestCase):
    def test_feishu_summary_shows_data_dates_explicitly(self):
        text = PUSH_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("Data dates: ", text)
        self.assertIn("ERP={dates.get('erp')", text)
        self.assertIn("Relative={dates.get('relative')", text)
        self.assertIn("HSI_ERP={dates.get('hsi_erp')", text)
        self.assertIn("Holdings={dates.get('asset')", text)


if __name__ == "__main__":
    unittest.main()
