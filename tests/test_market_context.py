import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json

spec = importlib.util.spec_from_file_location("context", Path(__file__).resolve().parents[1] / "scripts" / "fetch_market_context.py")
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)


class ContextTests(unittest.TestCase):
    def test_relative_performance_aligns_dates_and_uses_ratio_not_difference(self):
        from datetime import date, timedelta
        points = [{"date": (date(2026, 1, 1) + timedelta(days=i)).isoformat(), "value": 100 + i} for i in range(61)]
        benchmark = [{**p, "value": 100 + i / 2} for i, p in enumerate(points)]
        result = context.relative_metric(points + [{"date": "2026-03-15", "value": 999}], benchmark)
        self.assertEqual(result["as_of"], points[-1]["date"])
        self.assertAlmostEqual(result["changes"]["60"], ((160 / 130) - 1) * 100, places=3)

    def test_future_intraday_and_missing_adjusted_prices_are_excluded(self):
        current = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)
        ts = [int(datetime(2026, 11, d, 14, 30, tzinfo=timezone.utc).timestamp()) for d in (4, 5, 6)]
        result = {"timestamp": ts, "indicators": {"adjclose": [{"adjclose": [100, 110, 120]}]}}
        self.assertEqual(context.closed_price_points(result, current), [{"date": "2026-11-04", "value": 100.0}])
        with self.assertRaises(ValueError):
            context.closed_price_points({"timestamp": ts, "indicators": {}}, current)

    def test_real_yield_change_is_in_basis_points(self):
        from datetime import date, timedelta
        points = [{"date": (date(2026, 1, 1) + timedelta(days=i)).isoformat(), "value": 2 + i * .01} for i in range(21)]
        result = context.series_metric(points, "yield")
        self.assertEqual(result["change"], 20)

    def test_weekly_delta_uses_calendar_date_and_percentile_is_dated(self):
        points = [{"date": day, "value": value} for day, value in [("2026-09-18", -1), ("2026-09-25", -.9), ("2026-10-02", -.8), ("2026-10-16", -.5), ("2026-10-30", 0)]]
        result = context.series_metric(points, "stress")
        self.assertEqual(result["comparison_date"], "2026-10-02")
        self.assertEqual(result["change"], .8)
        self.assertEqual(result["percentile"], 100)

    def test_missing_csv_observations_are_not_zero(self):
        result = context.normalize_points([{"date": "2026-01-01", "value": "."}, {"date": "2026-01-02", "value": 0}, {"date": "invalid", "value": 1}])
        self.assertEqual(result, [{"date": "2026-01-02", "value": 0.0}])

    def test_network_failure_preserves_original_data_date_and_retrieval_time(self):
        previous = {"real_yield": {"id": "real_yield", "value": 2.5, "as_of": "2026-10-30", "retrieved_at": "2026-11-01T00:00:00Z", "series": []}}
        with TemporaryDirectory() as folder, patch.object(context, "TARGET", Path(folder) / "context.json"), patch.object(context, "previous_items", return_value=previous), patch.object(context, "yahoo_series", side_effect=RuntimeError("offline")), patch.object(context, "fred_series", side_effect=RuntimeError("offline")):
            context.main()
            payload = json.loads(context.TARGET.read_text(encoding="utf-8"))
        item = next(x for x in payload["items"] if x["id"] == "real_yield")
        self.assertEqual(item["as_of"], "2026-10-30")
        self.assertEqual(item["retrieved_at"], "2026-11-01T00:00:00Z")
        self.assertTrue(item["retained"])
        self.assertIsNone(next(x for x in payload["items"] if x["id"] == "financial_stress")["value"])


if __name__ == "__main__":
    unittest.main()
