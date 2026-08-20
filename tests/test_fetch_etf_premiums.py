from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_etf_premiums.py"
SPEC = importlib.util.spec_from_file_location("fetch_etf_premiums", MODULE_PATH)
premium = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(premium)


class PremiumHistoryTests(unittest.TestCase):
    def test_requested_thirteen_funds_are_configured(self):
        self.assertEqual(list(premium.ETF_NAMES), [
            "159501", "159696", "513870", "159632", "159659", "159509", "513100",
            "159941", "513300", "159660", "513390", "159513", "513110",
        ])

    def test_build_history_joins_close_and_nav_by_date(self):
        nav_items = [
            {"date": "2026-08-18", "nav": 2.0},
            {"date": "2026-08-19", "nav": 2.1},
        ]
        candles = [
            {"t": 1786982400, "c": 2.2},
            {"t": 1787068800, "c": 2.31},
            {"t": 1787155200, "c": 9.99},
        ]
        result = premium.build_history(nav_items, candles, "2026-08-18", "2026-08-20")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["date"], "2026-08-18")
        self.assertAlmostEqual(result[0]["premium"], 10.0)
        self.assertAlmostEqual(result[1]["premium"], 10.0)

    def test_distribution_and_percentile(self):
        values = [-1.0, 0.0, 2.9, 3.0, 5.9, 6.0, 9.9, 10.0, 12.0]
        result = premium.distribution(values)
        self.assertEqual(sum(item["count"] for item in result), len(values))
        self.assertEqual(premium.percentile(values, 6.0), 66.7)
        self.assertIsNone(premium.percentile([], 6.0))

    def test_each_fund_uses_its_own_meaningful_ranges(self):
        normal = premium.distribution([5.0, 7.0, 9.0, 11.0, 13.0])
        high_premium = premium.distribution([14.0, 17.0, 20.0, 23.0, 26.0])
        self.assertNotEqual([item["label"] for item in normal], [item["label"] for item in high_premium])
        self.assertIn("20%", " ".join(item["label"] for item in high_premium))

    def test_history_keeps_only_latest_120_unique_trading_days(self):
        older = [{"date": f"2026-01-{day:02d}", "premium": day, "close": 1, "nav": 1} for day in range(1, 32)]
        newer = [{"date": f"2026-{month:02d}-{day:02d}", "premium": day, "close": 1, "nav": 1} for month in range(2, 7) for day in range(1, 29)]
        result = premium.merge_history(older, newer)
        self.assertEqual(len(result), 120)
        self.assertEqual(result[-1]["date"], "2026-06-28")

    def test_current_snapshot_replaces_same_day_record(self):
        old = [{"date": "2026-08-20", "premium": 18, "close": 2.5, "nav": 2.1}]
        current = [{"date": "2026-08-20", "premium": 24.87, "close": 2.792, "nav": 2.236}]
        result = premium.merge_history(old, current)
        self.assertEqual(result[0]["premium"], 24.87)


if __name__ == "__main__":
    unittest.main()
