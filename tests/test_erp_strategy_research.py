import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "orchestrator" / "erp_strategy_research.py"


def load_module():
    spec = importlib.util.spec_from_file_location("erp_strategy_research_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ErpStrategyResearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.research = load_module()

    def test_causal_percentile_requires_minimum_history(self):
        values = [1.0] * 59
        self.assertIsNone(self.research.causal_percentile(values))

    def test_causal_percentile_uses_only_passed_values(self):
        values = [float(index) for index in range(1, 61)]
        self.assertEqual(self.research.causal_percentile(values), 100.0)
        self.assertEqual(self.research.causal_percentile(values, invert=True), round(1 / 60 * 100, 1))

    def test_set_config_value_changes_one_leaf_without_mutating_source(self):
        config = {"top": {"items": [{"weight": 0.5}]}}
        updated = self.research.set_config_value(config, "top.items.0.weight", 0.4)
        self.assertEqual(updated["top"]["items"][0]["weight"], 0.4)
        self.assertEqual(config["top"]["items"][0]["weight"], 0.5)

    def test_configured_erp_snapshot_uses_tested_regime_values(self):
        snapshot = {"percentile": 80.0}
        config = {
            "percentile_thresholds": {"low": 40.0, "high": 60.0},
            "aggressive_weights": {"low": 0.35, "neutral": 0.50, "high": 0.60},
        }
        configured = self.research.configured_erp_snapshot(snapshot, config)
        self.assertEqual(configured["aggressive_weight"], 0.60)
        self.assertEqual(configured["defensive_weight"], 0.40)

    def test_cash_yield_proxy_uses_calendar_days(self):
        result = self.research._cash_yield_proxy(
            {"date": "2026-01-01", "bond_yield": 3.65},
            {"date": "2026-01-11"},
        )
        self.assertAlmostEqual(result, 0.001)

    def test_reconstructs_hsi_price_from_hstech_ratio(self):
        row = self.research._raw_to_execution_row({"date": "2026-01-01", "hstech": 4800.0, "hstech_ratio": 0.2})
        self.assertEqual(row["恒生指数"], 24000.0)

    def test_high_utilization_episodes_only_counts_entries(self):
        episodes = self.research._high_utilization_episodes([0.5, 0.66, 0.67, 0.4, 0.7], 0.65)
        self.assertEqual(episodes, [1, 4])

    def test_forward_summary_requires_complete_horizon(self):
        summary = self.research._forward_summary([0.01, -0.02], [0, 1], 2)
        self.assertEqual(summary["eligible_episodes"], 1)
        self.assertAlmostEqual(summary["worst_path_drawdown"], -0.02)

    def test_pearson_correlation_reports_linear_direction(self):
        self.assertAlmostEqual(self.research._pearson_correlation([1, 2, 3], [2, 4, 6]), 1.0)
        self.assertAlmostEqual(self.research._pearson_correlation([1, 2, 3], [6, 4, 2]), -1.0)

    def test_history_coverage_marks_short_series(self):
        records = [
            {"date": "2020-01-01", "kc50": 1.0, "hs300": 1.0, "sh50": 1.0, "hstech_ratio": 1.0, "zz500_ratio": 1.0, "zz1000_ratio": 1.0},
            {"date": "2020-01-02", "kc50": 1.1, "hs300": 1.0, "sh50": 1.0, "hstech_ratio": 1.1, "zz500_ratio": 1.1, "zz1000_ratio": 1.1},
        ]
        coverage = self.research.history_coverage({"records": records}, long_history_minimum=3)
        kc50 = next(item for item in coverage if item["signal"] == "KC50 / HS300")
        self.assertEqual(kc50["status"], "short_history_warning")


if __name__ == "__main__":
    unittest.main()
