import importlib.util
import unittest
from datetime import date
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "erp_improvement_sandbox"
    / "hsi_daily_erp_experiment.py"
)
SPEC = importlib.util.spec_from_file_location("hsi_daily_erp_experiment", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class HsiDailyErpExperimentTests(unittest.TestCase):
    def test_parse_catalog_keeps_only_hsi_idx_reports(self):
        payload = b'''{
          "indexSeriesList": [
            {"seriesCode": "hsi", "reportList": [
              {"reportType": "idx", "reportDate": [
                {"date": "2026-08-14 00:00:00", "url": "/daily.csv"}
              ]},
              {"reportType": "ips", "reportDate": [
                {"date": "2026-08-14 00:00:00", "url": "/ignored.xls"}
              ]}
            ]}
          ]
        }'''

        reports = MODULE.parse_hsi_catalog(payload)

        self.assertEqual(reports, [{
            "date": date(2026, 8, 14),
            "url": "https://www.hsi.com.hk/daily.csv",
        }])

    def test_parse_hsi_idx_csv_reads_official_daily_pe(self):
        text = (
            '"交易日"\t"指數"\t"指數貨幣"\t"指數收市"\t"市盈率"\r\n'
            '"Trade Date"\t"Index"\t"Index Currency"\t"Index Close"\t"PE Ratio (times)"\r\n'
            '"20260814"\t"Hang Seng Index 恒生指數"\t"HKD"\t"25116.85"\t"13.91"\r\n'
        )

        record = MODULE.parse_hsi_idx_csv(text.encode("utf-16"), "https://www.hsi.com.hk/daily.csv")

        self.assertEqual(record["date"], date(2026, 8, 14))
        self.assertEqual(record["hsi_close"], 25116.85)
        self.assertEqual(record["hsi_pe"], 13.91)

    def test_parse_treasury_xml_reads_10_year_rate(self):
        payload = b'''<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"
              xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
              xmlns="http://www.w3.org/2005/Atom">
          <entry><content type="application/xml"><m:properties>
            <d:NEW_DATE m:type="Edm.DateTime">2026-08-13T00:00:00</d:NEW_DATE>
            <d:BC_10YEAR m:type="Edm.Double">4.23</d:BC_10YEAR>
          </m:properties></content></entry>
        </feed>'''

        records = MODULE.parse_treasury_xml(payload)

        self.assertEqual(records, [{"date": date(2026, 8, 13), "us10y": 4.23}])

    def test_daily_erp_uses_latest_prior_rate_and_never_future_rate(self):
        hsi = [{
            "date": date(2026, 8, 14),
            "hsi_close": 25116.85,
            "hsi_pe": 13.91,
            "hsi_source_url": "https://www.hsi.com.hk/daily.csv",
        }]
        treasury = [
            {"date": date(2026, 8, 13), "us10y": 4.23},
            {"date": date(2026, 8, 17), "us10y": 4.10},
        ]

        record = MODULE.build_daily_erp_records(hsi, treasury)[0]

        self.assertEqual(record["us10y_date"], "2026-08-13")
        self.assertEqual(record["rate_lag_days"], 1)
        self.assertAlmostEqual(record["hsi_erp_pct"], 100 / 13.91 - 4.23, places=6)

    def test_hybrid_history_uses_only_prior_monthly_anchor(self):
        closes = [
            {"date": date(2026, 1, 30), "hsi_close": 20000.0},
            {"date": date(2026, 2, 2), "hsi_close": 21000.0},
            {"date": date(2026, 2, 27), "hsi_close": 22000.0},
            {"date": date(2026, 3, 2), "hsi_close": 23000.0},
        ]
        monthly = [
            {"date": date(2026, 1, 30), "hsi_pe": 10.0},
            {"date": date(2026, 2, 27), "hsi_pe": 11.0},
        ]

        records = MODULE.build_hybrid_hsi_records(closes, monthly, [])
        february_2 = next(row for row in records if row["date"] == date(2026, 2, 2))
        march_2 = next(row for row in records if row["date"] == date(2026, 3, 2))

        self.assertEqual(february_2["hsi_pe_anchor_date"], date(2026, 1, 30))
        self.assertAlmostEqual(february_2["hsi_pe"], 10.5)
        self.assertEqual(march_2["hsi_pe_anchor_date"], date(2026, 2, 27))
        self.assertAlmostEqual(march_2["hsi_pe"], 11.5)

    def test_official_daily_pe_overrides_monthly_derived_value(self):
        closes = [
            {"date": date(2026, 1, 30), "hsi_close": 20000.0},
            {"date": date(2026, 2, 2), "hsi_close": 21000.0},
        ]
        monthly = [{"date": date(2026, 1, 30), "hsi_pe": 10.0}]
        official = [{
            "date": date(2026, 2, 2),
            "hsi_close": 21001.0,
            "hsi_pe": 10.2,
            "hsi_source_url": "https://www.hsi.com.hk/daily.csv",
            "hsi_pe_source_type": "official_daily",
            "hsi_pe_anchor_date": date(2026, 2, 2),
            "hsi_pe_anchor_value": 10.2,
            "hsi_close_source": "official",
        }]

        records = MODULE.build_hybrid_hsi_records(closes, monthly, official)
        latest = records[-1]

        self.assertEqual(latest["hsi_pe"], 10.2)
        self.assertEqual(latest["hsi_close"], 21001.0)
        self.assertEqual(latest["hsi_pe_source_type"], "official_daily")

    def test_freshness_blocks_stale_hsi_or_rate(self):
        records = [{
            "date": "2026-08-08",
            "us10y_date": "2026-08-01",
            "rate_lag_days": 7,
        }]

        freshness = MODULE.assess_freshness(records, date(2026, 8, 14), 4, 4)

        self.assertFalse(freshness["ok"])
        self.assertEqual(len(freshness["errors"]), 2)


if __name__ == "__main__":
    unittest.main()
