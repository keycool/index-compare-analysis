import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "orchestrator" / "sync_production_signals.py"


def load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_production_signals_for_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_payload(erp_date="2026-08-07", relative_date="2026-08-07"):
    return {
        "version": "1.0",
        "signal_type": "erp_relative_merged",
        "generated_at": "2026-08-09T01:47:14+00:00",
        "latest_date": min(erp_date, relative_date),
        "components": {
            "erp": {
                "latest_date": erp_date,
                "record_count": 2,
                "records": [
                    {"date": "2026-08-06", "equity_premium": 5.2},
                    {"date": erp_date, "equity_premium": 5.21},
                ],
                "latest_signal": {"date": erp_date, "equity_premium": 5.21},
            },
            "relative": {
                "latest_date": relative_date,
                "record_count": 2,
                "records": [
                    {"date": "2026-08-06", "zz500_ratio": 1.6},
                    {"date": relative_date, "zz500_ratio": 1.61},
                ],
                "latest_signal": {"date": relative_date, "zz500_ratio": 1.61},
            },
        },
    }


def build_hsi_erp_payload(hsi_date="2026-07-31"):
    return {
        "version": "1.1",
        "signal_type": "hsi_erp",
        "latest_date": hsi_date,
        "record_count": 2,
        "records": [
            {"date": "2026-06-30", "hsi_erp": 2.5},
            {"date": hsi_date, "hsi_erp": 2.2},
        ],
        "latest_signal": {"date": hsi_date, "hsi_erp": 2.2},
    }


class SyncProductionSignalsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sync = load_sync_module()

    def test_sync_writes_components_and_preserves_backups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shared_dir = Path(temp_dir)
            old_erp = {"latest_date": "2026-07-10", "records": [{"date": "2026-07-10"}]}
            old_relative = {"latest_date": "2026-07-16", "records": [{"date": "2026-07-16"}]}
            (shared_dir / "erp_signal.json").write_text(json.dumps(old_erp), encoding="utf-8")
            (shared_dir / "relative_signal.json").write_text(json.dumps(old_relative), encoding="utf-8")

            result = self.sync.sync_payload(
                build_payload(),
                shared_dir,
                captured_at=datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc),
            )

            erp = json.loads((shared_dir / "erp_signal.json").read_text(encoding="utf-8"))
            relative = json.loads((shared_dir / "relative_signal.json").read_text(encoding="utf-8"))
            merged = json.loads((shared_dir / "merged_signal.json").read_text(encoding="utf-8"))
            backup_dir = Path(result["backup_dir"])

            self.assertEqual(erp["latest_date"], "2026-08-07")
            self.assertEqual(erp["signal_type"], "equity_risk_premium")
            self.assertEqual(relative["latest_date"], "2026-08-07")
            self.assertEqual(relative["signal_type"], "csi300_relative_index")
            self.assertEqual(merged["latest_date"], "2026-08-07")
            self.assertEqual(
                json.loads((backup_dir / "erp_signal.json").read_text(encoding="utf-8"))["latest_date"],
                "2026-07-10",
            )

    def test_rejects_component_latest_date_mismatch(self):
        payload = build_payload()
        payload["components"]["erp"]["latest_date"] = "2026-08-06"

        with self.assertRaisesRegex(ValueError, "does not match record max date"):
            self.sync.validate_merged_payload(payload)

    def test_rejects_downgrade_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shared_dir = Path(temp_dir)
            current = {"latest_date": "2026-08-08", "records": [{"date": "2026-08-08"}]}
            (shared_dir / "erp_signal.json").write_text(json.dumps(current), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Refusing to downgrade"):
                self.sync.sync_payload(build_payload(), shared_dir)

    def test_dry_run_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shared_dir = Path(temp_dir)
            result = self.sync.sync_payload(build_payload(), shared_dir, dry_run=True)

            self.assertTrue(result["dry_run"])
            self.assertFalse((shared_dir / "erp_signal.json").exists())
            self.assertFalse((shared_dir / "relative_signal.json").exists())

    def test_sync_writes_validated_hsi_erp_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shared_dir = Path(temp_dir)
            result = self.sync.sync_payload(
                build_payload(), shared_dir, hsi_erp_payload=build_hsi_erp_payload()
            )

            hsi_erp = json.loads((shared_dir / "hsi_erp_signal.json").read_text(encoding="utf-8"))
            self.assertEqual(hsi_erp["latest_date"], "2026-07-31")
            self.assertEqual(result["hsi_erp"]["record_count"], 2)

    def test_rejects_hsi_erp_latest_date_mismatch(self):
        payload = build_hsi_erp_payload()
        payload["latest_date"] = "2026-07-30"

        with self.assertRaisesRegex(ValueError, "does not match record max date"):
            self.sync.validate_hsi_erp_payload(payload)


if __name__ == "__main__":
    unittest.main()
