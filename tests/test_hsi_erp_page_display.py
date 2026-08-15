import importlib.util
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "index-compare"
    / "scripts"
    / "generate_report.py"
)
SPEC = importlib.util.spec_from_file_location("generate_report_for_hsi_display_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class HsiErpPageDisplayTests(unittest.TestCase):
    def test_page_layout_hides_price_panel_and_unifies_analysis_cards(self):
        source = MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn(".charts-section:has([data-price-range-toolbar])", source)
        self.assertIn("{all_analysis_html}", source)
        self.assertNotIn("{core_analysis_html}", source)
        self.assertNotIn("{feature_analysis_html}", source)
        self.assertNotIn("{external_analysis_html}", source)

    def test_daily_display_uses_prior_monthly_anchor_and_daily_treasury(self):
        index_df = pd.DataFrame(
            {"HSI": [20000.0, 21000.0, 22000.0, 23000.0]},
            index=pd.to_datetime(["2026-01-30", "2026-02-16", "2026-07-31", "2026-08-14"]),
        )
        monthly_payload = (
            pd.DataFrame(),
            {
                "historical_mean": 3.0,
                "percentile": 40.0,
                "hsi_index": 23000.0,
                "hsi_pe": 12.0,
                "us10y": 4.5,
            },
        )
        official_pe = pd.DataFrame(
            {"date": pd.to_datetime(["2026-01-30", "2026-07-31"]), "hsi_pe": [10.0, 11.0]}
        )
        daily_rates = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-02-13", "2026-07-31", "2026-08-13"]),
                "us10y": [4.7, 4.6, 4.5],
            }
        )

        with patch.object(MODULE, "fetch_official_hsi_monthly_pe_recent", return_value=official_pe), \
             patch.object(MODULE, "fetch_us10y_daily_history", return_value=daily_rates):
            result = MODULE.build_hsi_erp_daily_display_history(index_df, monthly_payload)

        self.assertIsNotNone(result)
        history, summary = result
        self.assertEqual(history.iloc[0]["anchor_date"].date(), date(2026, 1, 30))
        self.assertEqual(history.iloc[-1]["anchor_date"].date(), date(2026, 7, 31))
        self.assertEqual(history.iloc[-1]["us10y"], 4.5)
        self.assertEqual(summary["display_sample_count"], 3)
        self.assertIn("display_historical_mean", summary)

    def test_page_summary_keeps_monthly_percentile(self):
        index_df = pd.DataFrame(
            {"HSI": [20000.0, 22000.0]},
            index=pd.to_datetime(["2026-07-31", "2026-08-14"]),
        )
        monthly_payload = (
            pd.DataFrame(),
            {"historical_mean": 3.0, "percentile": 41.0, "hsi_index": 20000.0, "hsi_pe": 11.0, "us10y": 4.6},
        )
        official_pe = pd.DataFrame({"date": pd.to_datetime(["2026-07-31"]), "hsi_pe": [11.0]})
        daily_rates = pd.DataFrame({"date": pd.to_datetime(["2026-08-13"]), "us10y": [4.5]})

        with patch.object(MODULE, "fetch_official_hsi_monthly_pe_recent", return_value=official_pe), \
             patch.object(MODULE, "fetch_us10y_daily_history", return_value=daily_rates):
            _, summary = MODULE.build_hsi_erp_daily_display_history(index_df, monthly_payload)

        self.assertEqual(summary["percentile"], 41.0)
        self.assertEqual(summary["historical_mean"], 3.0)


if __name__ == "__main__":
    unittest.main()
