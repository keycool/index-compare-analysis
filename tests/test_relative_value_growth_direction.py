import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / ".claude" / "skills" / "index-compare" / "scripts"
MAIN_PATH = SCRIPTS_DIR / "main.py"


def load_relative_main():
    skill_root = SCRIPTS_DIR.parent
    sys.path.insert(0, str(skill_root))
    spec = importlib.util.spec_from_file_location("relative_main_for_test", MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ValueGrowthDirectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.relative_main = load_relative_main()

    def build_export(self):
        dates = pd.date_range("2026-01-01", periods=30, freq="D")
        growth_over_value = [1.0] * 29 + [2.0]
        processed = pd.DataFrame(
            {
                "trade_date": dates,
                "VAL300_ratio": growth_over_value,
                "VAL300_MA30": pd.Series(growth_over_value).rolling(30).mean(),
            }
        )
        conclusions = {
            "VAL300": {"recommendation": {"action": "强烈低配"}},
        }
        return self.relative_main.build_export_dataframe(processed, conclusions)

    def test_export_fields_follow_each_asset_as_numerator(self):
        latest = self.build_export().iloc[-1]

        self.assertAlmostEqual(latest["300价值/成长比价"], 0.5)
        self.assertEqual(latest["300价值分位"], 3.3)
        self.assertEqual(latest["300成长分位"], 100.0)
        self.assertLess(latest["300价值偏离(%)"], 0)
        self.assertGreater(latest["300成长偏离(%)"], 0)
        self.assertEqual(latest["300价值建议"], "强烈超配")
        self.assertEqual(latest["300成长建议"], "强烈低配")

    def test_shared_signal_keeps_value_and_growth_direction(self):
        export = self.build_export()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "relative_signal.json"
            self.assertTrue(self.relative_main.export_shared_signal(export, output))
            payload = json.loads(output.read_text(encoding="utf-8"))

        latest_record = payload["records"][-1]
        latest_signal = payload["latest_signal"]
        self.assertAlmostEqual(latest_record["val300_ratio"], 0.5)
        self.assertEqual(latest_record["val300_percentile"], 3.3)
        self.assertEqual(latest_record["gro300_percentile"], 100.0)
        self.assertEqual(latest_signal["val300_recommendation"], "强烈超配")
        self.assertEqual(latest_signal["gro300_recommendation"], "强烈低配")

    def test_feishu_ratio_row_describes_growth_as_numerator(self):
        from scripts.feishu import FeishuWebhook

        conclusions = {
            "VAL300": {
                "current_ratio": 2.0,
                "percentile": {"value": 100.0},
                "recommendation": {"action": "强烈低配"},
            }
        }
        rows = FeishuWebhook()._build_signal_rows(
            {"VAL300_ratio": 2.0},
            conclusions,
        )
        style_row = next(row for row in rows if row["name"] == "300成长 / 300价值")

        self.assertEqual(style_row["ratio"], "2.0000")
        self.assertEqual(style_row["percentile"], "100.0%")
        self.assertEqual(style_row["recommendation"], "强烈低配")

    def test_feishu_payload_puts_equity_premium_before_relative_signals(self):
        from scripts.feishu import FeishuWebhook

        with tempfile.TemporaryDirectory() as temp_dir:
            erp_path = Path(temp_dir) / "erp_signal.json"
            hsi_path = Path(temp_dir) / "hsi_erp_signal.json"
            erp_path.write_text(
                json.dumps(
                    {
                        "latest_date": "2026-07-21",
                        "records": [
                            {"date": "2026-07-20", "equity_premium": 4.0},
                            {"date": "2026-07-21", "equity_premium": 6.0},
                        ],
                        "latest_signal": {"date": "2026-07-21", "equity_premium": 6.0},
                    }
                ),
                encoding="utf-8",
            )
            hsi_path.write_text(
                json.dumps({"date": "2026-07-21", "latest_value": 3.2, "percentile": 42.5}),
                encoding="utf-8",
            )
            env = {
                "INDEX_COMPARE_ERP_SIGNAL_PATH": str(erp_path),
                "INDEX_COMPARE_HSI_ERP_SIGNAL_PATH": str(hsi_path),
            }
            with patch.dict(os.environ, env, clear=False):
                payload = FeishuWebhook()._build_post_payload(
                    {
                        "\u65e5\u671f": "2026-07-21",
                        "500/300\u6bd4\u4ef7": 1.2,
                        "500\u5206\u4f4d": 55.0,
                        "500\u5efa\u8bae": "\u6807\u914d",
                    },
                    {},
                    "\u6307\u6570\u6bd4\u4ef7\u5206\u6790",
                )

        content = payload["content"]["post"]["zh_cn"]["content"]
        texts = [row[0]["text"] for row in content]
        self.assertLess(
            texts.index("\u80a1\u6743\u6ea2\u4ef7\u6307\u6570"),
            texts.index("\u6bd4\u4ef7\u4fe1\u53f7"),
        )
        self.assertIn("\u6caa\u6df1300\u80a1\u6743\u6ea2\u4ef7\u6307\u6570 | 6.0000 | 100.0% | 2026-07-21", texts)
        self.assertIn("\u6052\u751f\u6307\u6570\u80a1\u6743\u6ea2\u4ef7\u6307\u6570 | 3.2000 | 42.5% | 2026-07-21", texts)


if __name__ == "__main__":
    unittest.main()
