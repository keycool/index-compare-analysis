import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestrator.erp_execution_cloud import build_data_health, build_target_weights, compute_relative_snapshot


REC = {
    "strong_over": "\u5f3a\u70c8\u8d85\u914d",
    "over": "\u8d85\u914d",
    "neutral": "\u6807\u914d",
    "under": "\u4f4e\u914d",
    "strong_under": "\u5f3a\u70c8\u4f4e\u914d",
}


def base_config():
    return {
        "cross_market": {"hk_pool_cap": 0.2, "hk_min_erp_percentile": 30, "hk_full_erp_percentile": 50},
        "percentile_thresholds": {"low": 40.0, "high": 60.0},
        "aggressive_weights": {"low": 0.35, "neutral": 0.50, "high": 0.65},
        "alpha_budget_weights": {"low": 0.20, "neutral": 0.28, "high": 0.35},
        "style_pair": {
            "budget_ratio": 0.30,
            "split": {"value_cheap_weight": 0.70, "neutral_weight": 0.50, "growth_cheap_weight": 0.70},
            "percentile_thresholds": {"low": 30, "high": 70},
        },
        "hk_erp": {
            "percentile_thresholds": {"low": 40.0, "high": 60.0},
            "aggressive_weights": {"low": 0.30, "neutral": 0.45, "high": 0.60},
        },
        "recommendation_multipliers": {
            REC["strong_over"]: 1.30,
            REC["over"]: 1.15,
            REC["neutral"]: 1.00,
            REC["under"]: 0.85,
            REC["strong_under"]: 0.70,
        },
        "alpha_base_weights": {"sh50": 1.0, "zz500": 0.4, "zz1000": 0.3, "cyb": 0.3, "kc50": 0.25},
        "alpha_bucket_caps": {
            "sh50": 0.18,
            "val300": 0.10,
            "gro300": 0.10,
            "zz500": 0.12,
            "zz1000": 0.08,
            "cyb": 0.08,
            "kc50": 0.06,
            "hstech": 0.08,
        },
        "forced_exit_percentiles": {
            "sh50": 95.0,
            "zz500": 95.0,
            "zz1000": 95.0,
            "cyb": 95.0,
            "kc50": 95.0,
            "hstech": 95.0,
            "val300": 95.0,
            "gro300": 95.0,
        },
        "aggressive_reentry_percentiles": {
            "zz500": 100.0,
            "zz1000": 100.0,
            "cyb": 100.0,
            "kc50": 100.0,
            "hstech": 100.0,
            "val300": 100.0,
            "gro300": 100.0,
        },
        "reentry_min_current_amount": -1.0,
        "trajectory_overlay": {
            "enabled": True,
            "hot": {"deviation_min": 4.0, "change_5d_min": 3.0, "multiplier": 0.6},
            "warm": {"deviation_min": 2.0, "change_5d_min": 1.0, "multiplier": 0.8},
            "repair_strong": {"deviation_max": -3.0, "change_5d_min": 0.0, "multiplier": 1.15},
            "repair_light": {"deviation_max": -1.0, "change_5d_min": 0.0, "multiplier": 1.05},
            "falling": {"deviation_max": 0.0, "change_5d_max": 0.0, "multiplier": 0.85},
        },
        "bucket_metadata": {
            "hs300": {"label": "hs300", "sleeve": "defensive", "pool": "ashare"},
            "sh50": {"label": "sh50", "sleeve": "defensive", "pool": "ashare"},
            "val300": {"label": "val300", "sleeve": "defensive", "pool": "ashare"},
            "gro300": {"label": "gro300", "sleeve": "defensive", "pool": "ashare"},
            "cyb": {"label": "cyb", "sleeve": "aggressive", "pool": "ashare"},
            "zz500": {"label": "zz500", "sleeve": "aggressive", "pool": "ashare"},
            "zz1000": {"label": "zz1000", "sleeve": "aggressive", "pool": "ashare"},
            "kc50": {"label": "kc50", "sleeve": "aggressive", "pool": "ashare"},
            "hsi": {"label": "hsi", "sleeve": "defensive", "pool": "hkshare"},
            "hstech": {"label": "hstech", "sleeve": "aggressive", "pool": "hkshare"},
        },
    }


def base_relative_snapshot():
    return {
        "recommendations": {
            "zz500": REC["neutral"],
            "zz1000": REC["neutral"],
            "cyb": REC["neutral"],
            "sh50": REC["neutral"],
            "kc50": REC["strong_over"],
            "val300": REC["over"],
            "gro300": REC["under"],
            "hstech": REC["neutral"],
        },
        "percentiles": {
            "zz500_percentile": 50.0,
            "zz1000_percentile": 50.0,
            "cyb_percentile": 50.0,
            "sh50_percentile": 50.0,
            "kc50_percentile": 20.0,
            "val300_percentile": 10.0,
            "gro300_percentile": 90.0,
            "hstech_percentile": 50.0,
        },
        "deviations": {
            "zz500_deviation": 0.0,
            "zz1000_deviation": 0.0,
            "cyb_deviation": 0.0,
            "kc50_deviation": 0.0,
            "val300_deviation": 0.0,
            "gro300_deviation": 0.0,
            "hstech_deviation": 0.0,
        },
        "changes": {
            "zz500_change_5d": 0.0,
            "zz1000_change_5d": 0.0,
            "cyb_change_5d": 0.0,
            "kc50_change_5d": 0.0,
            "val300_change_5d": 0.0,
            "gro300_change_5d": 0.0,
            "hstech_change_5d": 0.0,
        },
    }


class ErpExecutionCloudLogicTest(unittest.TestCase):
    def build_targets(self, relative=None, config=None):
        return build_target_weights(
            {"percentile": 50.0, "aggressive_weight": 0.50},
            {"available": True, "percentile": 50.0, "aggressive_weight": 0.45},
            relative or base_relative_snapshot(),
            config or base_config(),
            {"hs300": 100000.0, "hsi": 1.0, "hstech": 1.0},
        )

    def test_kc50_signal_is_not_reversed(self):
        targets = self.build_targets()

        self.assertEqual(targets["kc50"]["signal"], REC["strong_over"])

    def test_low_value_percentile_allocates_more_to_value_than_growth(self):
        targets = self.build_targets()

        self.assertGreater(targets["val300"]["target_weight"], targets["gro300"]["target_weight"])
        self.assertEqual(targets["val300"]["signal"], REC["over"])
        self.assertEqual(targets["gro300"]["signal"], REC["under"])

    def test_bucket_caps_are_hard_after_trajectory_overlay(self):
        config = base_config()
        config["alpha_bucket_caps"]["kc50"] = 0.01
        relative = base_relative_snapshot()
        relative["deviations"]["kc50_deviation"] = -5.0
        relative["changes"]["kc50_change_5d"] = 0.5

        targets = self.build_targets(relative=relative, config=config)

        self.assertLessEqual(targets["kc50"]["target_weight"], 0.01)
        self.assertEqual(targets["kc50"]["trajectory_multiplier"], 1.15)

    def test_hstech_cap_is_hard_after_trajectory_overlay(self):
        config = base_config()
        config["alpha_bucket_caps"]["hstech"] = 0.01
        relative = base_relative_snapshot()
        relative["deviations"]["hstech_deviation"] = -5.0
        relative["changes"]["hstech_change_5d"] = 0.5

        targets = self.build_targets(relative=relative, config=config)

        self.assertLessEqual(targets["hstech"]["target_weight"], 0.01)
        self.assertEqual(targets["hstech"]["trajectory_multiplier"], 1.15)

    def test_asset_freshness_uses_oldest_erp_row_update(self):
        config = {"data_quality": {"max_staleness_days": {"erp": 14, "relative": 3, "asset": 14}}}
        health = build_data_health(
            {"date": "2026-07-20"},
            {"available": False},
            {"date": "2026-07-21"},
            [
                {"III级分类": ["ERP"], "_last_modified_time": "2026-07-01"},
                {"III级分类": ["ERP"], "_last_modified_time": "2026-07-21"},
            ],
            config,
            datetime(2026, 7, 21, tzinfo=ZoneInfo("Asia/Shanghai")),
            require_asset_timestamp=True,
        )

        self.assertFalse(health["ok"])
        self.assertEqual(health["dates"]["asset"], "2026-07-01")
        self.assertEqual(health["asset_update"]["newest"], "2026-07-21")
        self.assertTrue(any("asset data is stale" in error for error in health["errors"]))

    def test_asset_staleness_can_warn_without_blocking_cloud_run(self):
        config = {"data_quality": {"max_staleness_days": {"erp": 14, "relative": 3, "asset": 14}}}
        health = build_data_health(
            {"date": "2026-07-20"},
            {"available": False},
            {"date": "2026-07-21"},
            [
                {"III\u7ea7\u5206\u7c7b": ["ERP"], "_last_modified_time": "2026-07-01"},
                {"III\u7ea7\u5206\u7c7b": ["ERP"], "_last_modified_time": "2026-07-21"},
            ],
            config,
            datetime(2026, 7, 21, tzinfo=ZoneInfo("Asia/Shanghai")),
            require_asset_timestamp=False,
        )

        self.assertTrue(health["ok"])
        self.assertEqual(health["dates"]["asset"], "2026-07-01")
        self.assertFalse(health["errors"])
        self.assertTrue(any("asset data is stale" in warning for warning in health["warnings"]))

    def test_signal_date_gap_can_warn_in_research_mode(self):
        config = {"data_quality": {"max_signal_date_gap_days": 10, "max_staleness_days": {"erp": 30, "relative": 30, "asset": 30}}}
        health = build_data_health(
            {"date": "2026-07-09"},
            {"available": False},
            {"date": "2026-07-21"},
            [{"III\u7ea7\u5206\u7c7b": ["ERP"], "_last_modified_time": "2026-07-21"}],
            config,
            datetime(2026, 7, 21, tzinfo=ZoneInfo("Asia/Shanghai")),
            require_asset_timestamp=False,
            strict_signal_dates=False,
        )

        self.assertTrue(health["ok"])
        self.assertFalse(health["errors"])
        self.assertTrue(any("ERP/relative date gap" in warning for warning in health["warnings"]))

    def test_growth_style_change_is_derived_from_real_relative_history(self):
        rows = []
        value_growth_ratios = [1.00, 1.02, 1.01, 1.03, 1.04, 0.80]
        for day, ratio in enumerate(value_growth_ratios, start=1):
            rows.append(
                {
                    "\u65e5\u671f": f"2026-07-{day:02d}",
                    "500\u5efa\u8bae": REC["neutral"],
                    "1000\u5efa\u8bae": REC["neutral"],
                    "\u521b\u4e1a\u677f\u5efa\u8bae": REC["neutral"],
                    "50\u5efa\u8bae": REC["neutral"],
                    "\u79d1\u521b50\u5efa\u8bae": REC["neutral"],
                    "300\u4ef7\u503c\u5efa\u8bae": REC["over"],
                    "300\u6210\u957f\u5efa\u8bae": REC["under"],
                    "\u6052\u751f\u79d1\u6280\u5efa\u8bae": REC["neutral"],
                    "300\u4ef7\u503c/\u6210\u957f\u6bd4\u4ef7": ratio,
                    "300\u4ef7\u503c\u5206\u4f4d": 20.0,
                    "300\u6210\u957f\u5206\u4f4d": 80.0,
                    "300\u4ef7\u503c\u504f\u79bb(%)": -2.0,
                }
            )

        snapshot = compute_relative_snapshot(rows)

        self.assertEqual(snapshot["changes"]["val300_change_5d"], -20.0)
        self.assertEqual(snapshot["changes"]["gro300_change_5d"], 25.0)
        self.assertEqual(snapshot["deviations"]["gro300_deviation"], 2.0)


if __name__ == "__main__":
    unittest.main()
