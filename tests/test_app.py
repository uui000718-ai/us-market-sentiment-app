import tempfile
import unittest
import io
import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app


class SentimentTests(unittest.TestCase):
    def test_demo_report_is_complete(self):
        report = app.collect(demo=True)
        self.assertEqual(report["available_indicators"], 6)
        self.assertGreaterEqual(report["score"], 0)
        self.assertLessEqual(report["score"], 100)
        cftc = next(item for item in report["indicators"] if item["name"] == "cftc_positioning")
        self.assertEqual(cftc["weight"], 0)
        self.assertEqual(report["decision"]["total_indicators"], 5)

    def test_utf8_split_respects_limit(self):
        parts = app.split_utf8("标题\n" + "美股情绪" * 100, max_bytes=80)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part.encode("utf-8")) <= 80 for part in parts))

    def test_save_report(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"DATA_DIR": folder}):
            path = app.save_report(app.collect(demo=True))
            self.assertEqual(path, Path(folder) / "latest.json")
            self.assertTrue(path.exists())

    def test_serverchan_payload_and_response(self):
        response = io.BytesIO(b'{"code":0,"message":"ok"}')
        response.__enter__ = lambda value: value
        response.__exit__ = lambda *args: None
        environment = {"SERVERCHAN3_TITLE": "测试日报", "SERVERCHAN3_TAGS": "美股|测试"}
        with patch.dict("os.environ", environment), patch("app.urlopen", return_value=response) as mocked:
            app.send_serverchan("## test", "sctp123tSecretKey")
        request = mocked.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "https://123.push.ft07.com/send/sctp123tSecretKey.send")
        payload = app.json.loads(request.data)
        self.assertEqual(payload["title"], "测试日报")
        self.assertEqual(payload["desp"], "## test")
        self.assertEqual(payload["tags"], "美股|测试")

    def test_serverchan_rejects_invalid_sendkey(self):
        with self.assertRaises(ValueError):
            app.send_serverchan("test", "invalid-key")

    def test_report_types(self):
        report = app.collect(demo=True)
        self.assertNotIn("VIX 波动率", app.render_report(report, "brief"))
        standard = app.render_report(report, "standard")
        self.assertIn("| AAII 投资者情绪 |", standard)
        self.assertIn("4周均值 78.60", standard)
        self.assertIn("RSI1", standard)
        self.assertIn("RSI6", standard)
        self.assertIn("RSI14", standard)
        self.assertIn("综合决策", standard)
        self.assertIn("触发理由", standard)
        self.assertIn("美东时间", standard)
        self.assertIn("纳斯达克100 52周位置", standard)
        self.assertTrue("距52周收盘高点回撤" in standard or "创52周收盘新高" in standard)
        self.assertEqual(standard.count("综合风险偏好"), 1)
        self.assertIn("当前值", app.render_report(report, "full"))
        self.assertIn("综合风险偏好", app.render_report(report, "custom"))

    def test_wilder_rsi_for_rising_series(self):
        self.assertEqual(app.wilder_rsi([float(value) for value in range(1, 30)]), 100.0)
        self.assertEqual(app.wilder_rsi([3.0, 2.0], period=1), 0.0)

    def test_fifty_two_week_position(self):
        drawdown = app.fifty_two_week_position([100.0, 120.0, 110.0])
        self.assertFalse(drawdown["is_new_high"])
        self.assertEqual(drawdown["latest"], 110.0)
        self.assertEqual(drawdown["high"], 120.0)
        self.assertAlmostEqual(drawdown["drawdown_pct"], 8.333333, places=5)

        new_high = app.fifty_two_week_position([100.0, 120.0, 121.0])
        self.assertTrue(new_high["is_new_high"])
        self.assertEqual(new_high["latest"], 121.0)
        self.assertEqual(new_high["high"], 121.0)
        self.assertEqual(new_high["drawdown_pct"], 0.0)

    def test_weighted_decision_rules_and_reasons(self):
        self.assertEqual(app.DECISION_WEIGHTS, {
            "aaii": 20,
            "ndx_forward_pe": 10,
            "naaim": 20,
            "vix": 25,
            "qqq_rsi": 25,
        })
        source_data = {
            "aaii": {"date": "2026-08-05", "bullish": 49.0, "bearish": 30.0},
            "ndx_pe": {"date": "2026-08-05", "forward_pe": 22.5},
            "naaim": {"exposure": 69.0, "four_week_average": 96.0},
        }
        histories = {"^VIX": {"closes": [36.0]}}
        decision = app.build_decision(source_data, histories, {1: 0.0, 6: 18.0, 14: 19.5}, as_of=date(2026, 8, 5))
        self.assertEqual(decision["recommendation"], "强烈买入")
        self.assertTrue(decision["full_position_signal"])
        self.assertEqual(decision["buy_triggers"], 4)
        self.assertEqual(decision["sell_triggers"], 2)
        reasons = "\n".join(item["reason"] for item in decision["triggers"])
        self.assertIn("预估市盈率 22.50x < 23x", reasons)
        self.assertIn("AAII看涨 49.0% > 45%", reasons)
        self.assertIn("NAAIM 4周均值 96.00 > 95", reasons)
        self.assertIn("VIX 36.00 > 35", reasons)
        self.assertIn("QQQ RSI6 18.00 ≤ 20", reasons)

    def test_aaii_bearish_near_45_triggers_buy(self):
        decision = app.build_decision(
            {"aaii": {"date": "2026-08-05", "bullish": 31.0, "bearish": 42.3}},
            {},
            {},
            as_of=date(2026, 8, 5),
        )
        self.assertEqual(decision["buy_triggers"], 1)
        self.assertEqual(decision["sell_triggers"], 0)
        self.assertEqual(decision["triggers"][0]["direction"], "buy")
        self.assertIn("42.3% 位于42%–45%", decision["triggers"][0]["reason"])

    def test_aaii_bullish_above_45_sells_and_bearish_above_45_buys(self):
        bullish = app.build_decision(
            {"aaii": {"date": "2026-08-05", "bullish": 46.0, "bearish": 30.0}}, {}, {}, as_of=date(2026, 8, 5)
        )
        self.assertEqual(bullish["sell_triggers"], 1)
        self.assertLess(bullish["score"], 0)
        self.assertIn("AAII看涨 46.0% > 45%", bullish["triggers"][0]["reason"])

        bearish = app.build_decision(
            {"aaii": {"date": "2026-08-05", "bullish": 30.0, "bearish": 46.0}}, {}, {}, as_of=date(2026, 8, 5)
        )
        self.assertEqual(bearish["buy_triggers"], 1)
        self.assertEqual(bearish["sell_triggers"], 0)
        self.assertGreater(bearish["score"], 0)
        self.assertIn("AAII看跌 46.0% > 45%（强买入）", bearish["triggers"][0]["reason"])

    def test_stale_aaii_and_pe_do_not_trigger_buy(self):
        decision = app.build_decision(
            {
                "aaii": {"date": "2026-07-28", "bullish": 30.0, "bearish": 46.0},
                "ndx_pe": {"date": "2026-07-28", "forward_pe": 22.0},
            },
            {},
            {},
            as_of=date(2026, 8, 5),
        )
        self.assertEqual(decision["buy_triggers"], 0)
        self.assertEqual(len(decision["suppressed_signals"]), 2)
        self.assertIn("AAII数据已8天", decision["suppressed_signals"][0])
        self.assertIn("预估市盈率数据已8天", decision["suppressed_signals"][1])

    def test_seven_day_old_data_can_still_trigger_buy(self):
        decision = app.build_decision(
            {
                "aaii": {"date": "2026-07-29", "bullish": 30.0, "bearish": 46.0},
                "ndx_pe": {"date": "2026-07-29", "forward_pe": 22.0},
            },
            {},
            {},
            as_of=date(2026, 8, 5),
        )
        self.assertEqual(decision["buy_triggers"], 2)
        self.assertEqual(decision["suppressed_signals"], [])

    def test_macromicro_series_uses_latest_row(self):
        result = app.parse_macromicro_series({
            "series": [
                {"date": "2026-07-01", "val": 80.0},
                {"date": "2026-07-08", "val": 82.95},
            ]
        })
        self.assertEqual(result["date"], "2026-07-08")
        self.assertEqual(result["exposure"], 82.95)
        self.assertEqual(result["four_week_average"], 81.475)
        self.assertEqual(result["source"], "MacroMicro授权API")

    def test_manual_naaim_update_and_four_week_average(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "naaim.json"
            path.write_text(json.dumps({"records": [
                {"date": "2026-07-22", "exposure": 84.02},
                {"date": "2026-07-15", "exposure": 95.64},
                {"date": "2026-07-08", "exposure": 82.95},
            ]}), encoding="utf-8")
            app.update_manual_naaim(79.7, "2026-07-29", path)
            result = app.load_manual_naaim(path)
        self.assertEqual(result["date"], "2026-07-29")
        self.assertEqual(result["exposure"], 79.7)
        self.assertAlmostEqual(result["four_week_average"], 85.5775)
        self.assertEqual(result["source"], "GitHub手动记录")

    def test_cftc_reference_indicator_has_zero_weight(self):
        rows = [{
            "report_date_as_yyyy_mm_dd": "2026-07-28T00:00:00.000",
            "pct_of_oi_asset_mgr_long": "60.0",
            "pct_of_oi_asset_mgr_short": "10.0",
        }, {
            "report_date_as_yyyy_mm_dd": "2026-07-21T00:00:00.000",
            "pct_of_oi_asset_mgr_long": "55.0",
            "pct_of_oi_asset_mgr_short": "15.0",
        }]
        with patch("app.http_bytes", return_value=json.dumps(rows).encode("utf-8")):
            result = app.fetch_cftc_asset_manager_positioning()
        self.assertEqual(result["net_pct"], 50.0)
        self.assertEqual(result["four_week_average"], 45.0)
        self.assertEqual(result["three_year_percentile"], 100.0)

    def test_naaim_reminder_uses_beijing_friday(self):
        friday = datetime(2026, 8, 7, 8, 47, tzinfo=ZoneInfo("Asia/Shanghai"))
        reminder = app.naaim_update_reminder({"date": "2026-07-29"}, friday)
        self.assertIn("美东周四", reminder)
        self.assertIn("北京时间周五", reminder)
        fresh = app.naaim_update_reminder({"date": "2026-08-05"}, friday)
        self.assertIsNone(fresh)

    def test_serverchan_uid_must_match_sendkey(self):
        with self.assertRaises(ValueError):
            app.serverchan3_endpoint("sctp123tSecretKey", "456")


if __name__ == "__main__":
    unittest.main()
