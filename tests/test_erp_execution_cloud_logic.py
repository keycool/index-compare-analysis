import json
import unittest
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestrator.erp_execution_cloud import (
    DEFAULT_RELATIVE_ANALYSIS_SETTINGS,
    build_data_health,
    build_reference_allocation_plan,
    build_rebalance_plan,
    build_target_weights,
    compute_hsi_erp_snapshot_from_shared_signal,
    compute_relative_snapshot,
    derive_reentry_state_from_history,
    filter_signal_rows_as_of,
    validate_execution_payload,
    _REVERSE_REC,
    apply_portfolio_deployment_layer,
    _rotate_hs300_release,
    _derive_relative_recommendation,
    _fill_derived_relative_recommendations,
)
from orchestrator.push_erp_monitor_snapshot import build_snapshot


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
        "alpha_base_weights": {"sh50": 1.0, "zz500": 0.3, "zz1000": 0.25, "cyb": 0.5, "kc50": 0.45},
        "alpha_bucket_caps": {
            "sh50": 0.18,
            "val300": 0.10,
            "gro300": 0.10,
            "zz500": 0.10,
            "zz1000": 0.08,
            "cyb": 0.10,
            "kc50": 0.08,
            "hstech": 0.08,
        },
        "alpha_group_caps": {"cyb_kc50": {"buckets": ["cyb", "kc50"], "cap": 0.14}},
        "relative_signal_policy": {
            "anchor_recommendation_keys": {
                "sh50": "sh50_300", "zz500": "zz500", "zz1000": "zz1000",
                "cyb": "cyb", "kc50": "kc50_300", "val300": "val300",
                "gro300": "gro300", "hstech": "hstech",
            },
            "anchor_eligible_recommendations": [REC["neutral"], REC["over"], REC["strong_over"]],
            "pairwise_tilt_multipliers": {
                REC["strong_over"]: {"numerator": 1.10, "denominator": 0.90},
                REC["over"]: {"numerator": 1.05, "denominator": 0.95},
                REC["neutral"]: {"numerator": 1.00, "denominator": 1.00},
                REC["under"]: {"numerator": 0.95, "denominator": 1.05},
                REC["strong_under"]: {"numerator": 0.90, "denominator": 1.10},
            },
            "pairwise_features": {
                "cyb_sh50": {"signal_key": "cyb_sh50", "numerator": "cyb", "denominator": "sh50"},
                "kc50_sh50": {"signal_key": "kc50", "numerator": "kc50", "denominator": "sh50"},
                "zz1000_500": {"signal_key": "zz1000_500", "numerator": "zz1000", "denominator": "zz500"},
            },
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


def deployment_config():
    config = base_config()
    config["portfolio_deployment"] = {
        "enabled": True,
        "ashare": {
            "enabled": True,
            "default_weight": 0.50,
            "breakpoints": [
                {"percentile": 0, "weight": 0.05},
                {"percentile": 40, "weight": 0.35},
                {"percentile": 60, "weight": 0.50},
                {"percentile": 80, "weight": 0.85},
                {"percentile": 100, "weight": 1.00},
            ],
        },
        "hkshare": {
            "enabled": True,
            "default_weight": 0.00,
            "breakpoints": [
                {"percentile": 0, "weight": 0.00},
                {"percentile": 50, "weight": 0.50},
                {"percentile": 100, "weight": 1.00},
            ],
        },
        "core_caps": {
            "hs300": {
                "enabled": True,
                "default_weight": 0.35,
                "breakpoints": [
                    {"percentile": 0, "weight": 0.08},
                    {"percentile": 40, "weight": 0.25},
                    {"percentile": 60, "weight": 0.35},
                    {"percentile": 100, "weight": 0.45},
                ],
            }
        },
    }
    return config


def base_relative_snapshot():
    return {
        "date": "2026-07-21",
        "recommendations": {
            "zz500": REC["neutral"],
            "zz1000": REC["neutral"],
            "zz1000_500": REC["neutral"],
            "cyb": REC["neutral"],
            "sh50": REC["neutral"],
            "sh50_300": REC["neutral"],
            "cyb_sh50": REC["neutral"],
            "kc50": REC["strong_over"],
            "kc50_300": REC["strong_over"],
            "val300": REC["over"],
            "gro300": REC["under"],
            "hstech": REC["neutral"],
        },
        "percentiles": {
            "zz500_percentile": 50.0,
            "zz1000_percentile": 50.0,
            "zz1000_500_percentile": 50.0,
            "cyb_percentile": 50.0,
            "sh50_percentile": 50.0,
            "sh50_300_percentile": 50.0,
            "cyb_sh50_percentile": 50.0,
            "kc50_percentile": 20.0,
            "kc50_300_percentile": 20.0,
            "val300_percentile": 10.0,
            "gro300_percentile": 90.0,
            "hstech_percentile": 50.0,
        },
        "deviations": {
            "zz500_deviation": 0.0,
            "zz1000_deviation": 0.0,
            "zz1000_500_deviation": 0.0,
            "cyb_deviation": 0.0,
            "kc50_deviation": 0.0,
            "kc50_300_deviation": 0.0,
            "val300_deviation": 0.0,
            "gro300_deviation": 0.0,
            "hstech_deviation": 0.0,
        },
        "changes": {
            "zz500_change_5d": 0.0,
            "zz1000_change_5d": 0.0,
            "zz1000_500_change_5d": 0.0,
            "cyb_change_5d": 0.0,
            "kc50_change_5d": 0.0,
            "kc50_300_change_5d": 0.0,
            "val300_change_5d": 0.0,
            "gro300_change_5d": 0.0,
            "hstech_change_5d": 0.0,
        },
    }


def health_relative_snapshot(date: str = "2026-07-21"):
    snapshot = base_relative_snapshot()
    snapshot["date"] = date
    return snapshot


class ErpExecutionCloudLogicTest(unittest.TestCase):
    def test_hsi_erp_shared_history_is_available_without_feishu_table(self):
        snapshot = compute_hsi_erp_snapshot_from_shared_signal(
            {
                "records": [
                    {"date": "2026-06-30", "hsi_erp": 2.0},
                    {"date": "2026-07-31", "hsi_erp": 4.0},
                ]
            },
            base_config()["hk_erp"],
            datetime(2026, 8, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["date"], "2026-07-31")
        self.assertEqual(snapshot["percentile"], 100.0)
        self.assertEqual(snapshot["source"], "shared_hsi_erp_history")

    def test_initial_empty_holdings_do_not_activate_reentry_gate(self):
        targets = build_target_weights(
            {"percentile": 50.0, "aggressive_weight": 0.50},
            {"available": True, "percentile": 50.0, "aggressive_weight": 0.45},
            base_relative_snapshot(),
            base_config(),
            {},
            reentry_state={},
        )

        self.assertFalse(targets["hstech"]["reentry_blocked"])
        self.assertFalse(targets["hstech"]["reentry_waiting_after"])
        self.assertGreater(targets["hstech"]["target_weight"], 0.0)

    def test_reentry_gate_starts_after_forced_exit_and_clears_at_threshold(self):
        config = base_config()
        config["aggressive_reentry_percentiles"]["hstech"] = 30.0
        forced = base_relative_snapshot()
        forced["percentiles"]["hstech_percentile"] = 96.0
        first = build_target_weights(
            {"percentile": 50.0, "aggressive_weight": 0.50},
            {"available": True, "percentile": 50.0, "aggressive_weight": 0.45},
            forced,
            config,
            {},
            reentry_state={},
        )
        self.assertTrue(first["hstech"]["forced_exit"])
        self.assertTrue(first["hstech"]["reentry_waiting_after"])

        blocked = base_relative_snapshot()
        blocked["percentiles"]["hstech_percentile"] = 50.0
        second = build_target_weights(
            {"percentile": 50.0, "aggressive_weight": 0.50},
            {"available": True, "percentile": 50.0, "aggressive_weight": 0.45},
            blocked,
            config,
            {},
            reentry_state={"hstech": True},
        )
        self.assertTrue(second["hstech"]["reentry_blocked"])
        self.assertEqual(second["hstech"]["target_weight"], 0.0)

        eligible = base_relative_snapshot()
        eligible["percentiles"]["hstech_percentile"] = 20.0
        third = build_target_weights(
            {"percentile": 50.0, "aggressive_weight": 0.50},
            {"available": True, "percentile": 50.0, "aggressive_weight": 0.45},
            eligible,
            config,
            {},
            reentry_state={"hstech": True},
        )
        self.assertFalse(third["hstech"]["reentry_blocked"])
        self.assertFalse(third["hstech"]["reentry_waiting_after"])
        self.assertGreater(third["hstech"]["target_weight"], 0.0)

    def test_reentry_state_can_be_rebuilt_from_signal_history(self):
        config = base_config()
        config["aggressive_reentry_percentiles"]["hstech"] = 30.0
        rows = [
            {"日期": "2026-01-01", "恒生科技分位": 96.0},
            {"日期": "2026-01-02", "恒生科技分位": 50.0},
        ]
        state = derive_reentry_state_from_history(rows, config)
        self.assertTrue(state["hstech"])

        rows.append({"日期": "2026-01-03", "恒生科技分位": 20.0})
        state = derive_reentry_state_from_history(rows, config)
        self.assertFalse(state["hstech"])

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

    def test_sh50_anchor_blocks_pairwise_signal_from_creating_an_allocation(self):
        relative = base_relative_snapshot()
        relative["recommendations"]["sh50_300"] = REC["under"]
        relative["recommendations"]["cyb_sh50"] = REC["under"]

        targets = self.build_targets(relative=relative)

        self.assertEqual(targets["sh50"]["anchor_signal_key"], "sh50_300")
        self.assertFalse(targets["sh50"]["anchor_eligible"])
        self.assertEqual(targets["sh50"]["target_weight"], 0.0)

    def test_kc50_anchor_blocks_pairwise_signal_from_creating_an_allocation(self):
        relative = base_relative_snapshot()
        relative["recommendations"]["kc50_300"] = REC["under"]
        relative["recommendations"]["kc50"] = REC["strong_over"]

        targets = self.build_targets(relative=relative)

        self.assertEqual(targets["kc50"]["anchor_signal_key"], "kc50_300")
        self.assertFalse(targets["kc50"]["anchor_eligible"])
        self.assertEqual(targets["kc50"]["target_weight"], 0.0)

    def test_zz1000_over_zz500_feature_only_tilts_eligible_anchor_scores(self):
        relative = base_relative_snapshot()
        relative["recommendations"]["zz1000_500"] = REC["strong_over"]

        targets = self.build_targets(relative=relative)

        self.assertEqual(targets["zz1000"]["feature_tilt_multiplier"], 1.10)
        self.assertEqual(targets["zz500"]["feature_tilt_multiplier"], 0.90)
        self.assertEqual(targets["zz1000"]["feature_tilts"][0]["feature"], "zz1000_500")

    def test_low_value_percentile_allocates_more_to_value_than_growth(self):
        targets = self.build_targets()

        self.assertGreater(targets["val300"]["target_weight"], targets["gro300"]["target_weight"])
        self.assertEqual(targets["val300"]["signal"], REC["over"])
        self.assertEqual(targets["gro300"]["signal"], REC["under"])

    def test_bucket_caps_are_hard_after_trajectory_overlay(self):
        config = base_config()
        config["alpha_bucket_caps"]["kc50"] = 0.01
        relative = base_relative_snapshot()
        relative["deviations"]["kc50_300_deviation"] = -5.0
        relative["changes"]["kc50_300_change_5d"] = 0.5

        targets = self.build_targets(relative=relative, config=config)

        self.assertLessEqual(targets["kc50"]["target_weight"], 0.01)
        self.assertEqual(targets["kc50"]["trajectory_multiplier"], 1.15)

    def test_hs300_cap_release_rotates_only_to_qualified_satellites(self):
        config = deployment_config()
        config["portfolio_deployment"]["core_caps"]["hs300"]["breakpoints"] = [
            {"percentile": 0, "weight": 0.10},
            {"percentile": 100, "weight": 0.10},
        ]
        config["portfolio_deployment"]["core_rotation"] = {
            "hs300": {
                "enabled": True,
                "default_weight": 0.05,
                "breakpoints": [{"percentile": 0, "weight": 0.05}, {"percentile": 100, "weight": 0.05}],
            }
        }
        relative = base_relative_snapshot()
        relative["recommendations"]["zz500"] = REC["under"]
        relative["recommendations"]["zz1000"] = REC["under"]
        relative["recommendations"]["cyb"] = REC["under"]
        relative["recommendations"]["kc50_300"] = REC["under"]
        targets = build_target_weights(
            {"percentile": 60.0, "aggressive_weight": 0.50},
            {"available": False, "aggressive_weight": 0.0},
            relative,
            config,
            {},
        )

        self.assertEqual(targets["hs300"]["core_cap"], 0.10)
        self.assertGreater(targets["hs300"]["cap_released_to_rotation"], 0.0)
        self.assertGreater(targets["sh50"].get("core_rotation_added", 0.0), 0.0)
        self.assertEqual(targets["zz500"].get("core_rotation_added", 0.0), 0.0)
        self.assertLessEqual(targets["sh50"]["target_weight"], config["alpha_bucket_caps"]["sh50"])
        self.assertLessEqual(
            sum(float(item.get("core_rotation_added", 0.0)) for item in targets.values()),
            0.05,
        )
        self.assertAlmostEqual(sum(item["target_weight"] for item in targets.values()), 1.0, places=3)

    def test_hs300_cap_release_stays_cash_without_qualified_satellites(self):
        config = deployment_config()
        config["portfolio_deployment"]["core_caps"]["hs300"]["breakpoints"] = [
            {"percentile": 0, "weight": 0.10},
            {"percentile": 100, "weight": 0.10},
        ]
        config["portfolio_deployment"]["core_rotation"] = {
            "hs300": {
                "enabled": True,
                "default_weight": 0.05,
                "breakpoints": [{"percentile": 0, "weight": 0.05}, {"percentile": 100, "weight": 0.05}],
            }
        }
        relative = base_relative_snapshot()
        for key in ("sh50_300", "val300", "gro300", "zz500", "zz1000", "cyb", "kc50_300"):
            relative["recommendations"][key] = REC["under"]
        targets = build_target_weights(
            {"percentile": 60.0, "aggressive_weight": 0.50},
            {"available": False, "aggressive_weight": 0.0},
            relative,
            config,
            {},
        )

        self.assertEqual(targets["hs300"]["cap_released_to_rotation"], 0.0)
        self.assertGreater(targets["hs300"]["cap_released_to_cash"], 0.0)
        self.assertGreater(targets["cash"]["target_weight"], 0.5)

    def test_deployment_scaling_reapplies_individual_bucket_caps(self):
        config = deployment_config()
        targets = {
            "hs300": {"bucket": "hs300", "pool": "ashare", "target_weight": 0.40},
            "sh50": {
                "bucket": "sh50",
                "pool": "ashare",
                "signal": REC["neutral"],
                "target_weight": 0.15,
            },
        }

        scaled = apply_portfolio_deployment_layer(
            targets,
            {"percentile": 100.0},
            {"available": False},
            config,
        )

        self.assertLessEqual(scaled["sh50"]["target_weight"], 0.18)
        self.assertGreater(scaled["sh50"]["bucket_cap_released"], 0.0)
        self.assertAlmostEqual(sum(item["target_weight"] for item in scaled.values()), 1.0, places=3)

    def test_core_rotation_rounding_never_exceeds_configured_budget(self):
        config = deployment_config()
        config["portfolio_deployment"]["core_rotation"] = {
            "hs300": {
                "enabled": True,
                "default_weight": 0.05,
                "breakpoints": [{"percentile": 0, "weight": 0.05}, {"percentile": 100, "weight": 0.05}],
            }
        }
        targets = {
            "val300": {"pool": "ashare", "signal": REC["neutral"], "target_weight": 0.0210},
            "sh50": {"pool": "ashare", "signal": REC["neutral"], "target_weight": 0.1251},
            "zz1000": {"pool": "ashare", "signal": REC["neutral"], "target_weight": 0.0161},
            "kc50": {"pool": "ashare", "signal": REC["neutral"], "target_weight": 0.0267},
        }

        allocated = _rotate_hs300_release(
            targets,
            released_weight=0.20,
            percentile=100.0,
            deployment_config=config["portfolio_deployment"],
            execution_config=config,
        )

        self.assertLessEqual(allocated, 0.05)
        self.assertLessEqual(
            round(sum(float(item.get("core_rotation_added", 0.0)) for item in targets.values()), 4),
            0.05,
        )

    def test_cyb_and_kc50_combined_cap_is_hard(self):
        config = base_config()
        config["alpha_budget_weights"] = {"low": 0.45, "neutral": 0.45, "high": 0.45}
        targets = build_target_weights(
            {"percentile": 100.0, "aggressive_weight": 0.65},
            {"available": True, "percentile": 50.0, "aggressive_weight": 0.45},
            base_relative_snapshot(),
            config,
            {"hs300": 100000.0, "hsi": 1.0, "hstech": 1.0},
        )

        combined = targets["cyb"]["target_weight"] + targets["kc50"]["target_weight"]
        self.assertLessEqual(combined, 0.14)
        self.assertEqual(targets["cyb"]["group_cap_name"], "cyb_kc50")
        self.assertEqual(targets["kc50"]["group_cap"], 0.14)

    def test_payload_validation_rejects_group_cap_breach(self):
        payload = {
            "inputs": {"execution_config": {"alpha_group_caps": {"cyb_kc50": {"buckets": ["cyb", "kc50"], "cap": 0.14}}}},
            "portfolio": {"positions": [
                {"bucket": "cyb", "target_weight": 0.10},
                {"bucket": "kc50", "target_weight": 0.08},
                {"bucket": "cash", "target_weight": 0.82},
            ]},
            "signals": {"data_health": {"errors": []}},
        }

        with self.assertRaisesRegex(RuntimeError, "group cap cyb_kc50 exceeded"):
            validate_execution_payload(payload)

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
            health_relative_snapshot("2026-07-21"),
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
            health_relative_snapshot("2026-07-21"),
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
            health_relative_snapshot("2026-07-21"),
            [{"III\u7ea7\u5206\u7c7b": ["ERP"], "_last_modified_time": "2026-07-21"}],
            config,
            datetime(2026, 7, 21, tzinfo=ZoneInfo("Asia/Shanghai")),
            require_asset_timestamp=False,
            strict_signal_dates=False,
        )

        self.assertTrue(health["ok"])
        self.assertFalse(health["errors"])
        self.assertTrue(any("ERP/relative date gap" in warning for warning in health["warnings"]))

    def test_portfolio_snapshot_as_of_satisfies_strict_asset_gate(self):
        config = {"data_quality": {"max_staleness_days": {"erp": 14, "relative": 3, "asset": 14}}}
        health = build_data_health(
            {"date": "2026-07-20"},
            {"available": False},
            health_relative_snapshot("2026-07-20"),
            [{"III\u7ea7\u5206\u7c7b": ["ERP"]}],
            config,
            datetime(2026, 7, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
            require_asset_timestamp=True,
            portfolio_snapshot_as_of=datetime(2026, 7, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        self.assertTrue(health["ok"])
        self.assertEqual(health["dates"]["asset"], "2026-07-20")
        self.assertEqual(health["portfolio_snapshot_as_of"], "2026-07-20")
        self.assertEqual(health["asset_date_source"], "operator_asserted_portfolio_snapshot_as_of")
        self.assertEqual(health["portfolio_snapshot_assertion"]["mode"], "operator_asserted")
        self.assertFalse(health["portfolio_snapshot_assertion"]["verified_by_record_timestamps"])
        self.assertFalse(any("asset record update timestamp" in error for error in health["errors"]))
        self.assertTrue(any("operator asserted" in warning for warning in health["warnings"]))

    def test_missing_relative_recommendations_block_rebalance(self):
        config = {"data_quality": {"max_staleness_days": {"erp": 14, "relative": 3, "asset": 14}}}
        health = build_data_health(
            {"date": "2026-07-20"},
            {"available": False},
            {"date": "2026-07-20", "recommendations": {"zz500": ""}},
            [{"III\u7ea7\u5206\u7c7b": ["ERP"], "_last_modified_time": "2026-07-20"}],
            config,
            datetime(2026, 7, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
            require_asset_timestamp=True,
        )

        self.assertFalse(health["ok"])
        self.assertIn("zz1000", health["relative_recommendations"]["missing"])
        self.assertTrue(any("relative recommendations missing" in error for error in health["errors"]))

    def test_missing_relative_recommendations_warn_in_research(self):
        config = {"data_quality": {"max_staleness_days": {"erp": 14, "relative": 3, "asset": 14}}}
        health = build_data_health(
            {"date": "2026-07-20"},
            {"available": False},
            {"date": "2026-07-20", "recommendations": {"zz500": ""}},
            [{"III\u7ea7\u5206\u7c7b": ["ERP"], "_last_modified_time": "2026-07-20"}],
            config,
            datetime(2026, 7, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
            require_asset_timestamp=False,
            strict_signal_dates=False,
        )

        self.assertTrue(health["ok"])
        self.assertFalse(health["errors"])
        self.assertTrue(any("relative recommendations missing" in warning for warning in health["warnings"]))

    def test_validator_blocks_legacy_rebalance_plan_with_empty_recommendations(self):
        payload = {
            "inputs": {
                "execution_mode": "rebalance",
                "execution_config": {"data_quality": {"target_weight_tolerance": 0.0015}},
            },
            "signals": {
                "data_health": {"errors": []},
                "relative": {"recommendations": {"zz500": ""}},
            },
            "portfolio": {"positions": [{"target_weight": 1.0}]},
        }

        with self.assertRaisesRegex(RuntimeError, "relative recommendations missing"):
            validate_execution_payload(payload)

    def test_filter_signal_rows_as_of_excludes_future_rows(self):
        rows = [
            {"\u65e5\u671f": "2026-07-10", "value": "old"},
            {"\u65e5\u671f": "2026-07-20", "value": "as-of"},
            {"\u65e5\u671f": "2026-07-22", "value": "future"},
        ]

        filtered = filter_signal_rows_as_of(rows, datetime(2026, 7, 20, tzinfo=ZoneInfo("Asia/Shanghai")))

        self.assertEqual([row["value"] for row in filtered], ["old", "as-of"])

    def test_relative_snapshot_derives_recommendations_for_historical_rows(self):
        rows = []
        for day in range(1, 7):
            rows.append(
                {
                    "\u65e5\u671f": f"2026-07-{day:02d}",
                    "500/300\u6bd4\u4ef7": 1.0 + day / 100,
                    "500\u5206\u4f4d": 50.0,
                    "1000/300\u6bd4\u4ef7": 1.0,
                    "1000\u5206\u4f4d": 50.0,
                    "\u521b\u4e1a\u677f/300\u6bd4\u4ef7": 1.0,
                    "\u521b\u4e1a\u677f\u5206\u4f4d": 50.0,
                    "50/\u521b\u4e1a\u677f\u6bd4\u4ef7": 1.0,
                    "50\u5206\u4f4d": 50.0,
                    "\u79d1\u521b50/\u4e0a\u8bc150\u6bd4\u4ef7": 1.0,
                    "\u79d1\u521b50\u5206\u4f4d": 50.0,
                    "300\u4ef7\u503c/\u6210\u957f\u6bd4\u4ef7": 1.0,
                    "300\u4ef7\u503c\u5206\u4f4d": 50.0,
                    "300\u6210\u957f\u5206\u4f4d": 50.0,
                    "\u6052\u751f\u79d1\u6280/\u6052\u751f\u6bd4\u4ef7": 1.0,
                    "\u6052\u751f\u79d1\u6280\u5206\u4f4d": 50.0,
                }
            )

        snapshot = compute_relative_snapshot(rows)

        self.assertEqual(snapshot["date"], "2026-07-06")
        self.assertEqual(snapshot["recommendations"]["zz500"], REC["neutral"])
        self.assertEqual(snapshot["recommendation_sources"]["zz500"], "derived_from_analyze_rules")
        self.assertFalse(
            [
                key for key in ("zz500", "zz1000", "cyb", "sh50", "kc50", "val300", "gro300", "hstech")
                if not snapshot["recommendations"].get(key)
            ]
        )

    def test_relative_snapshot_preserves_zz1000_over_zz500_feature_signal(self):
        snapshot = compute_relative_snapshot([
            {
                "日期": "2026-07-21",
                "1000/500建议": REC["over"],
                "1000/500比价": 1.2,
                "1000/500分位": 30.0,
                "创业板/上证50建议": REC["under"],
                "创业板/上证50比价": 1.0,
                "50建议": REC["over"],
            }
        ])

        self.assertEqual(snapshot["recommendations"]["zz1000_500"], REC["over"])
        self.assertEqual(snapshot["recommendation_sources"]["zz1000_500"], "table")
        self.assertEqual(snapshot["ratios"]["zz1000_500_ratio"], 1.2)

    def test_derived_recommendation_uses_5d_10d_20d_trend(self):
        levels = DEFAULT_RELATIVE_ANALYSIS_SETTINGS["percentile_levels"]

        recommendation = _derive_relative_recommendation(30.0, 0.0, [2.0, -0.2, -0.2], levels)

        self.assertEqual(recommendation, REC["over"])

    def test_derived_recommendation_uses_zscore_not_raw_deviation(self):
        levels = DEFAULT_RELATIVE_ANALYSIS_SETTINGS["percentile_levels"]

        recommendation = _derive_relative_recommendation(30.0, 2.0, [0.0, 0.0, 0.0], levels)

        self.assertEqual(recommendation, REC["neutral"])

    def test_value_recommendation_is_reverse_of_growth_for_historical_rows(self):
        rows = []
        for day in range(1, 7):
            rows.append(
                {
                    "\u65e5\u671f": f"2026-07-{day:02d}",
                    "500/300\u6bd4\u4ef7": 1.0,
                    "500\u5206\u4f4d": 50.0,
                    "1000/300\u6bd4\u4ef7": 1.0,
                    "1000\u5206\u4f4d": 50.0,
                    "\u521b\u4e1a\u677f/300\u6bd4\u4ef7": 1.0,
                    "\u521b\u4e1a\u677f\u5206\u4f4d": 50.0,
                    "50/\u521b\u4e1a\u677f\u6bd4\u4ef7": 1.0,
                    "50\u5206\u4f4d": 50.0,
                    "\u79d1\u521b50/\u4e0a\u8bc150\u6bd4\u4ef7": 1.0,
                    "\u79d1\u521b50\u5206\u4f4d": 50.0,
                    "300\u4ef7\u503c/\u6210\u957f\u6bd4\u4ef7": 1.0,
                    "300\u4ef7\u503c\u5206\u4f4d": 99.0,
                    "300\u6210\u957f\u5206\u4f4d": 50.0,
                    "\u6052\u751f\u79d1\u6280/\u6052\u751f\u6bd4\u4ef7": 1.0,
                    "\u6052\u751f\u79d1\u6280\u5206\u4f4d": 50.0,
                }
            )

        snapshot = compute_relative_snapshot(rows)

        self.assertEqual(snapshot["recommendations"]["gro300"], REC["neutral"])
        self.assertEqual(snapshot["recommendations"]["val300"], REC["neutral"])
        self.assertEqual(snapshot["recommendation_sources"]["val300"], "derived_from_growth_recommendation_reverse")

    def test_value_growth_derived_recommendations_are_always_reversed(self):
        rng = random.Random(20260722)
        for _ in range(300):
            snapshot = {
                "recommendations": {"val300": "", "gro300": ""},
                "percentiles": {
                    "val300_percentile": rng.uniform(0.0, 100.0),
                    "gro300_percentile": rng.uniform(0.0, 100.0),
                },
                "zscores": {
                    "val300_zscore": rng.uniform(-3.0, 3.0),
                    "gro300_zscore": rng.uniform(-3.0, 3.0),
                },
                "changes": {
                    "val300_change_5d": rng.uniform(-5.0, 5.0),
                    "val300_change_10d": rng.uniform(-5.0, 5.0),
                    "val300_change_20d": rng.uniform(-5.0, 5.0),
                    "gro300_change_5d": rng.uniform(-5.0, 5.0),
                    "gro300_change_10d": rng.uniform(-5.0, 5.0),
                    "gro300_change_20d": rng.uniform(-5.0, 5.0),
                },
            }

            _fill_derived_relative_recommendations(snapshot)

            self.assertEqual(snapshot["recommendations"]["val300"], _REVERSE_REC[snapshot["recommendations"]["gro300"]])

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

    def test_growth_style_deviation_is_derived_from_inverse_ratio_history(self):
        rows = []
        value_growth_ratios = [1.0] * 29 + [0.8]
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

        self.assertEqual(snapshot["deviations"]["gro300_deviation"], 23.97)

    def test_portfolio_deployment_adds_cash_when_erp_is_below_60th_percentile(self):
        targets = build_target_weights(
            {"percentile": 58.0, "aggressive_weight": 0.50},
            {"available": False, "aggressive_weight": 0.0},
            base_relative_snapshot(),
            deployment_config(),
            {"hs300": 100000.0},
        )

        total_weight = sum(float(item["target_weight"]) for item in targets.values())
        self.assertAlmostEqual(total_weight, 1.0, places=4)
        self.assertIn("cash", targets)
        self.assertGreater(targets["cash"]["target_weight"], 0.49)
        self.assertLessEqual(targets["hs300"]["target_weight"], 0.35)

    def test_rebalance_plan_uses_total_capital_for_cash_layer(self):
        targets = build_target_weights(
            {"percentile": 58.0, "aggressive_weight": 0.50},
            {"available": False, "aggressive_weight": 0.0},
            base_relative_snapshot(),
            deployment_config(),
            {"hs300": 300000.0},
        )

        portfolio = build_rebalance_plan({"hs300": 300000.0}, [], targets, total_capital=1_000_000.0)
        cash = next(item for item in portfolio["positions"] if item["bucket"] == "cash")

        self.assertEqual(portfolio["managed_amount"], 1_000_000.0)
        self.assertEqual(portfolio["current_equity_amount"], 300000.0)
        self.assertEqual(cash["current_amount"], 700000.0)
        self.assertGreater(cash["target_amount"], 490000.0)

    def test_reference_plan_uses_fixed_notional_without_live_holding_deltas(self):
        targets = build_target_weights(
            {"percentile": 58.0, "aggressive_weight": 0.50},
            {"available": False, "aggressive_weight": 0.0},
            base_relative_snapshot(),
            deployment_config(),
            {},
        )

        portfolio = build_reference_allocation_plan(
            targets,
            {"notional": 1_000_000, "currency": "CNY", "actual_allocation_owner": "external_monitor"},
        )
        cash = next(item for item in portfolio["positions"] if item["bucket"] == "cash")

        self.assertEqual(portfolio["reference_notional"], 1_000_000.0)
        self.assertEqual(portfolio["actual_allocation_owner"], "external_monitor")
        self.assertNotIn("current_equity_amount", portfolio)
        self.assertNotIn("delta_amount", cash)
        self.assertAlmostEqual(cash["reference_amount"], cash["target_weight"] * 1_000_000, places=2)

    def test_monitor_snapshot_keeps_actual_allocation_outside_strategy(self):
        plan = {
            "version": "3.1",
            "generated_at": "2026-08-05T00:00:00+08:00",
            "inputs": {"execution_mode": "research"},
            "signals": {
                "data_health": {"errors": [], "warnings": [], "dates": {}},
                "relative": {"date": "2026-07-21", "recommendations": {"kc50_300": REC["under"]}},
            },
            "strategy_state": {
                "schema_version": 1,
                "as_of": "2026-07-21",
                "source": "derived_from_relative_history",
                "bootstrap_policy": "unblocked_until_forced_exit",
                "reentry_waiting": {"kc50": True},
            },
            "portfolio": {
                "reference_notional": 1_000_000,
                "reference_currency": "CNY",
                "actual_allocation_owner": "external_monitor",
                "ashare_pool": 0.50,
                "hkshare_pool": 0.10,
                "reserve_pool": 0.40,
                "target_weight_sum": 1.0,
                "positions": [
                    {"bucket": "hs300", "label": "HS300", "target_weight": 0.5, "reference_amount": 500000},
                    {
                        "bucket": "kc50", "label": "KC50", "pool": "ashare", "sleeve": "aggressive",
                        "target_weight": 0.0, "reference_amount": 0, "anchor_signal": REC["under"],
                        "anchor_signal_key": "kc50_300", "anchor_eligible": False,
                        "feature_tilt_multiplier": 1.0, "feature_tilts": [], "allocation_score": 0.0,
                    },
                ],
            },
        }

        snapshot = build_snapshot(plan)

        self.assertEqual(snapshot["portfolio"]["strategy_reference_notional"], 1_000_000.0)
        self.assertNotIn("current_equity_amount", snapshot["portfolio"])
        self.assertNotIn("top_actions", snapshot)
        self.assertEqual(snapshot["reference_allocations"][0]["reference_amount"], 500000.0)
        self.assertEqual(snapshot["monitor_schema_version"], 3)
        self.assertEqual(len(snapshot["reference_allocations"]), 2)
        self.assertEqual(snapshot["reference_allocations"][1]["anchor_signal_key"], "kc50_300")
        self.assertFalse(snapshot["reference_allocations"][1]["anchor_eligible"])
        self.assertEqual(snapshot["signals"]["relative"]["recommendations"]["kc50_300"], REC["under"])
        self.assertTrue(snapshot["strategy_state"]["reentry_waiting"]["kc50"])
        self.assertEqual(snapshot["actual_allocation_contract"]["strategy_input"], "not_used")
        json.dumps(snapshot, ensure_ascii=False)

    def test_validation_rejects_strategy_state_mismatch(self):
        payload = {
            "inputs": {
                "execution_mode": "research",
                "execution_config": {"data_quality": {"target_weight_tolerance": 0.0015}},
            },
            "signals": {"data_health": {"errors": []}},
            "strategy_state": {
                "schema_version": 1,
                "source": "derived_from_relative_history",
                "reentry_waiting": {"hstech": False},
            },
            "portfolio": {
                "positions": [
                    {"bucket": "hstech", "target_weight": 0.0, "reentry_waiting_after": True},
                    {"bucket": "cash", "target_weight": 1.0},
                ]
            },
        }

        with self.assertRaisesRegex(RuntimeError, "strategy_state reentry_waiting mismatch for hstech"):
            validate_execution_payload(payload)



if __name__ == "__main__":
    unittest.main()
