import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator import sync_erp_signal_to_feishu as archive


class ErpLegacyFeishuArchiveTest(unittest.TestCase):
    def test_defaults_target_khf_archive_table(self):
        self.assertEqual(archive.DEFAULT_LEGACY_APP_TOKEN, "O9VFbTbHZafm5psq6ebcGgF7neD")
        self.assertEqual(archive.DEFAULT_LEGACY_TABLE_ID, "tble1VwP4HNtMNm2")

    def test_target_config_prefers_archive_specific_secrets(self):
        env = {
            "ERP_ARCHIVE_FEISHU_APP_TOKEN": "archive_base",
            "ERP_ARCHIVE_FEISHU_TABLE_ID": "archive_table",
            "ERP_LEGACY_FEISHU_APP_TOKEN": "legacy_base",
            "ERP_LEGACY_FEISHU_TABLE_ID": "legacy_table",
            "ERP_FEISHU_APP_TOKEN": "erp_base",
            "ERP_FEISHU_TABLE_ID": "erp_table",
        }

        with patch.dict(os.environ, env, clear=True):
            target = archive.target_config()

        self.assertEqual(target["app_token"], "archive_base")
        self.assertEqual(target["table_id"], "archive_table")
        self.assertEqual(target["app_token_source"], "ERP_ARCHIVE_FEISHU_APP_TOKEN")
        self.assertEqual(target["table_id_source"], "ERP_ARCHIVE_FEISHU_TABLE_ID")

    def test_target_config_accepts_existing_erp_feishu_secret_names(self):
        env = {
            "ERP_FEISHU_APP_TOKEN": "erp_base",
            "ERP_FEISHU_TABLE_ID": "erp_table",
        }

        with patch.dict(os.environ, env, clear=True):
            target = archive.target_config()

        self.assertEqual(target["app_token"], "erp_base")
        self.assertEqual(target["table_id"], "erp_table")
        self.assertEqual(target["app_token_source"], "ERP_FEISHU_APP_TOKEN")
        self.assertEqual(target["table_id_source"], "ERP_FEISHU_TABLE_ID")

    def test_target_config_falls_back_to_khf_archive_table(self):
        with patch.dict(os.environ, {}, clear=True):
            target = archive.target_config()

        self.assertEqual(target["app_token"], "O9VFbTbHZafm5psq6ebcGgF7neD")
        self.assertEqual(target["table_id"], "tble1VwP4HNtMNm2")
        self.assertEqual(target["app_token_source"], "default_khf_archive_app_token")
        self.assertEqual(target["table_id_source"], "default_khf_archive_table_id")

    def test_record_fields_skip_non_finite_numbers(self):
        fields = archive.record_fields(
            {
                "date": "2026-07-24",
                "csi300_close": 4000,
                "pe_ttm": float("nan"),
                "bond_yield": math.inf,
                "earnings_yield": 7.5,
                "equity_premium": 5.1,
            }
        )

        self.assertIn(archive.FIELD_DATE, fields)
        self.assertEqual(fields[archive.FIELD_CSI300], 4000.0)
        self.assertNotIn(archive.FIELD_PE, fields)
        self.assertNotIn(archive.FIELD_BOND, fields)
        self.assertEqual(fields[archive.FIELD_EARNINGS], 7.5)
        self.assertEqual(fields[archive.FIELD_PREMIUM], 5.1)

    def test_select_records_defaults_to_insert_only(self):
        records = [
            {"date": "2026-07-24", "equity_premium": 5.0},
            {"date": "2026-07-25", "equity_premium": 5.1},
        ]

        with patch.dict(os.environ, {}, clear=True):
            selected = archive.select_records(records, {"2026-07-24": "rec1"})

        self.assertEqual(selected, [{"date": "2026-07-25", "equity_premium": 5.1}])

    def test_select_records_honors_archive_start_date_for_empty_table(self):
        records = [
            {"date": "2026-06-30", "equity_premium": 4.9},
            {"date": "2026-07-01", "equity_premium": 5.0},
            {"date": "2026-07-02", "equity_premium": 5.1},
        ]

        with patch.dict(os.environ, {"ERP_ARCHIVE_START_DATE": "2026-07-01"}, clear=True):
            selected = archive.select_records(records, {})

        self.assertEqual(selected, records[1:])

    def test_select_records_can_update_existing_when_opted_in(self):
        records = [
            {"date": "2026-07-24", "equity_premium": 5.0},
            {"date": "2026-07-25", "equity_premium": 5.1},
        ]
        env = {"ERP_ARCHIVE_UPDATE_EXISTING": "true", "ERP_ARCHIVE_LOOKBACK_DAYS": "10000"}

        with patch.dict(os.environ, env, clear=True):
            selected = archive.select_records(records, {"2026-07-24": "rec1"})

        self.assertEqual(selected, records)

    def test_missing_credentials_skip_without_exception(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            signal_path = Path(temp_dir) / "erp_signal.json"
            signal_path.write_text('{"records": []}', encoding="utf-8")
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"FEISHU_APP_ID", "FEISHU_APP_SECRET"}
            }
            env["ERP_ARCHIVE_SIGNAL_PATH"] = str(signal_path)
            with patch.dict(os.environ, env, clear=True):
                result = archive.sync()

        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])
        self.assertIn("missing FEISHU_APP_ID", result["message"])


if __name__ == "__main__":
    unittest.main()
