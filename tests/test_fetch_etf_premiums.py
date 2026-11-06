from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_etf_premiums.py"
SPEC = importlib.util.spec_from_file_location("fetch_etf_premiums", MODULE_PATH)
premium = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(premium)
NOW = datetime(2026, 11, 6, 12, 50, tzinfo=timezone.utc)


def quote(code="513870", price="1.988", iopv="1.6956", vendor="17.24", stamp="20261106161455", **overrides):
    fields = [""] * 88
    fields[1], fields[2], fields[3], fields[30], fields[77], fields[78], fields[81] = "名称", code, price, stamp, vendor, iopv, "1.8122"
    for index, value in overrides.items():
        fields[int(index)] = value
    return f'v_{"sh" if code.startswith("5") else "sz"}{code}="{"~".join(fields)}";'


def metric(**kwargs):
    codes, errors = premium.parse_quotes(quote(**kwargs), [kwargs.get("code", "513870")], NOW)
    assert not errors, errors
    return next(iter(codes.values()))


def history_item(day, value=0.0, hour=16):
    quote_at = datetime.fromisoformat(day + f"T{hour:02d}:00:00+08:00")
    price = round(2 * (1 + value / 100), 4)
    calculated = round((price / 2 - 1) * 100, 4)
    return {"date": day, "close": price, "iopv": 2.0, "premium": calculated,
            "vendor_premium": round(calculated, 2), "quote_at": quote_at.isoformat(),
            "retrieved_at": (quote_at + timedelta(minutes=5)).isoformat(),
            "source": premium.SOURCE, "basis": "iopv", "session": "close"}


class PremiumTests(unittest.TestCase):
    def test_requested_thirteen_funds_are_configured(self):
        self.assertEqual(list(premium.ETF_NAMES), [
            "159501", "159696", "513870", "159632", "159659", "159509", "513100",
            "159941", "513300", "159660", "513390", "159513", "513110",
        ])

    def test_real_513870_snapshot_matches_iopv_not_delayed_nav(self):
        current = metric()
        self.assertEqual(current["premium"], 17.2446)
        self.assertEqual(current["iopv"], 1.6956)
        self.assertEqual(current["vendor_premium"], 17.24)
        self.assertEqual(current["quote_at"], "2026-11-06T16:14:55+08:00")
        self.assertNotIn("nav_base", current)
        self.assertNotIn("nav_date", current)

    def test_missing_iopv_does_not_fall_back_to_field81_nav(self):
        values, errors = premium.parse_quotes(quote(iopv=""), ["513870"], NOW)
        self.assertEqual(values, {})
        self.assertIn("IOPV", errors["513870"])

    def test_missing_or_inconsistent_vendor_is_rejected(self):
        for vendor in ("", "9.70", "NaN"):
            with self.subTest(vendor=vendor):
                values, errors = premium.parse_quotes(quote(vendor=vendor), ["513870"], NOW)
                self.assertEqual(values, {})
                self.assertIn("513870", errors)

    def test_zero_and_negative_premiums_are_values_not_missing(self):
        self.assertEqual(metric(price="2", iopv="2", vendor="0")["premium"], 0.0)
        self.assertEqual(metric(price="1.9", iopv="2", vendor="-5")["premium"], -5.0)
        self.assertEqual(premium.number_or_none(0), 0)
        self.assertIsNone(premium.number_or_none(True))

    def test_invalid_price_or_iopv_and_bad_timestamps_rejected(self):
        cases = [{"price": "0"}, {"iopv": "0"}, {"iopv": "NaN"}, {"stamp": "20260230150000"},
                 {"stamp": "20261107150000"}, {"stamp": "20261109150000"}, {"stamp": "2026-11-06"}]
        for case in cases:
            with self.subTest(case=case):
                values, errors = premium.parse_quotes(quote(**case), ["513870"], NOW)
                self.assertEqual(values, {})
                self.assertTrue(errors)

    def test_symbol_field_identity_and_short_response_rejected(self):
        for raw in (quote(**{"2": "513300"}), quote().replace("v_sh", "v_sz"), 'v_sh513870="1~name~513870";'):
            values, errors = premium.parse_quotes(raw, ["513870"], NOW)
            self.assertEqual(values, {})
            self.assertIn("513870", errors)

    def test_intraday_and_retained_do_not_create_close_history(self):
        intraday = metric(stamp="20261106145959")
        self.assertEqual(intraday["status"], "intraday")
        self.assertEqual(premium.current_history_item(intraday, NOW), [])
        self.assertEqual(premium.current_history_item({**metric(), "retained": True}, NOW), [])
        self.assertEqual(len(premium.current_history_item(metric(), NOW)), 1)

    def test_stale_quote_not_added_as_new_history_but_date_correction_allowed(self):
        old = metric(stamp="20261105161455")
        self.assertEqual(old["status"], "stale")
        self.assertEqual(premium.current_history_item(old, NOW), [])
        corrected = premium.current_history_item(old, NOW, {"2026-11-05"})
        self.assertEqual(corrected[0]["date"], "2026-11-05")

    def test_morning_and_weekend_can_record_last_completed_session(self):
        fri = metric()
        saturday = datetime(2026, 11, 7, 0, 0, tzinfo=timezone.utc)
        monday_morning = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(len(premium.current_history_item(fri, saturday)), 1)
        self.assertEqual(len(premium.current_history_item(fri, monday_morning)), 1)

    def test_legacy_mixed_history_not_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "history.json"
            target.write_text(json.dumps({"schema_version": 1, "funds": {"513870": [{"date": "2026-11-06", "premium": 9.7, "nav": 1.8122}]}}))
            with patch.object(premium, "HISTORY_TARGET", target):
                self.assertEqual(premium.load_saved_history(NOW), {})
            target.write_text(json.dumps({"schema_version": 2, "basis": "iopv", "funds": {"513870": [history_item("2026-11-06")]}}))
            with patch.object(premium, "HISTORY_TARGET", target):
                self.assertEqual(len(premium.load_saved_history(NOW)["513870"]), 1)

    def test_history_requires_iopv_provenance_formula_and_actual_close(self):
        good = history_item("2026-11-06")
        cases = [{**good, "basis": "nav"}, {**good, "premium": 9.7}, {**good, "source": "unknown"},
                 {**good, "date": "2026-11-05"}, history_item("2026-11-06", hour=14),
                 {**good, "retrieved_at": ""}, {"date": "2026-11-06", "premium": 0}]
        for item in cases:
            with self.subTest(item=item):
                self.assertEqual(premium.merge_history([item], now=NOW), [])
        self.assertEqual(premium.merge_history([good], now=NOW)[0]["premium"], 0.0)

    def test_120_latest_unique_weekdays_and_latest_snapshot_wins(self):
        day = datetime(2026, 1, 1)
        rows = []
        while len(rows) < 135:
            if day.weekday() < 5:
                rows.append(history_item(day.date().isoformat(), 1))
            day += timedelta(days=1)
        later = {**rows[-1], "retrieved_at": rows[-1]["retrieved_at"].replace("16:05", "16:10")}
        merged = premium.merge_history(rows, [later], now=NOW)
        self.assertEqual(len(merged), 120)
        self.assertEqual(merged[0]["date"], rows[-120]["date"])
        self.assertEqual(merged[-1], later)

    def test_intraday_overwrite_cannot_destroy_valid_close(self):
        end = history_item("2026-11-06", 3)
        unfinished = history_item("2026-11-06", 2, hour=14)
        self.assertEqual(premium.merge_history([end], [unfinished], now=NOW), [end])

    def test_failure_retains_original_timestamps_and_valid_history(self):
        current = metric()
        original = premium.current_history_item(current, NOW)
        report, saved = premium.build_report({}, {"513870": original}, {"513870": current}, {"513870": "failed"}, NOW + timedelta(hours=1))
        fund = next(x for x in report["funds"] if x["code"] == "513870")
        self.assertTrue(fund["current"]["retained"])
        self.assertEqual(fund["current"]["quote_at"], current["quote_at"])
        self.assertEqual(fund["current"]["retrieved_at"], current["retrieved_at"])
        self.assertEqual(saved["funds"]["513870"], original)
        self.assertIsNone(fund["percentile"])
        self.assertEqual(fund["sample_count"], 1)
        missing = next(x for x in report["funds"] if x["code"] == "159501")
        self.assertIsNone(missing["current"]["premium"])
        self.assertEqual(missing["sample_count"], 0)

    def test_schema2_and_distribution_never_fabricate_120_samples(self):
        report, history = premium.build_report({"513870": metric()}, {}, {}, {}, NOW)
        fund = next(x for x in report["funds"] if x["code"] == "513870")
        self.assertEqual((report["schema_version"], report["basis"], history["schema_version"]), (2, "iopv", 2))
        self.assertEqual(report["window"]["trading_days"], 120)
        self.assertEqual(fund["sample_count"], 1)
        self.assertEqual(sum(row["count"] for row in fund["distribution"]), 1)
        self.assertEqual(fund["history_status"], "accumulating")
        self.assertIsNone(fund["percentile"])

    def test_newer_history_beats_stale_published_current(self):
        fresh = metric()
        older = metric(stamp="20261105161455")
        history = premium.current_history_item(fresh, NOW)
        report, _ = premium.build_report({}, {"513870": history}, {"513870": older}, {}, NOW)
        fund = next(x for x in report["funds"] if x["code"] == "513870")
        self.assertEqual(fund["current"]["quote_at"], fresh["quote_at"])
        self.assertTrue(fund["current"]["retained"])
        self.assertEqual(premium.previous_currents({"schema_version": 2, "basis": "iopv", "funds": None}, NOW), {})

    def test_distribution_ranges_and_percentile_math(self):
        values = [-1.0, 0.0, 2.9, 3.0, 5.9, 6.0, 9.9, 10.0, 12.0]
        self.assertEqual(sum(item["count"] for item in premium.distribution(values)), len(values))
        self.assertEqual(premium.percentile(values, 6.0), 66.7)
        self.assertIsNone(premium.percentile([], 6.0))
        normal = premium.distribution([5, 7, 9, 11, 13])
        high = premium.distribution([14, 17, 20, 23, 26])
        self.assertNotEqual([x["label"] for x in normal], [x["label"] for x in high])

    def test_network_failure_is_per_fund_non_destructive(self):
        with patch.object(premium, "fetch_text", side_effect=RuntimeError("offline")):
            values, errors = premium.current_metrics(["513870", "159501"], NOW)
        self.assertEqual(values, {})
        self.assertEqual(set(errors), {"513870", "159501"})


if __name__ == "__main__":
    unittest.main()
