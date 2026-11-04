import assert from "node:assert/strict";
import test from "node:test";
import { expectedSession, freshness, number, recentEvents, validReport } from "../app/lib/market.ts";

test("missing values are never converted to zero", () => {
  assert.equal(number(null), "—");
  assert.equal(number(undefined), "—");
  assert.equal(number(0), "0.0");
});
test("latest completed session respects weekends, DST and US market holidays", () => {
  assert.equal(expectedSession(new Date("2026-11-05T01:00:00Z")), "2026-11-04");
  assert.equal(expectedSession(new Date("2026-11-09T01:00:00Z")), "2026-11-06");
  assert.equal(expectedSession(new Date("2026-07-04T01:00:00Z")), "2026-07-02");
  assert.equal(expectedSession(new Date("2026-04-04T01:00:00Z")), "2026-04-02");
  assert.equal(expectedSession(new Date("2026-11-27T01:00:00Z")), "2026-11-25");
  assert.equal(expectedSession(new Date("2026-07-07T01:00:00Z")), "2026-07-06");
});
test("fresh request time cannot disguise stale or intraday market data", () => {
  const report = { generated_at: "2026-11-04T15:30:00Z", indicators: [
    { name: "qqq_rsi", detail: "行情日期 2026-11-04" },
    { name: "vix", detail: "行情日期 2026-11-04" },
  ] };
  assert.equal(freshness(report, new Date("2026-11-05T01:00:00Z")).intraday, true);
  assert.equal(freshness(report, new Date("2026-11-06T01:00:00Z")).stale, true);
});
test("180 natural-day window excludes old and future records", () => {
  const events = ["2026-11-06", "2026-11-05", "2026-05-10", "2026-05-09"].map(market_date => ({ market_date }));
  assert.deepEqual(recentEvents(events, new Date("2026-11-05T12:00:00Z")).map(x => x.market_date), ["2026-11-05", "2026-05-10"]);
});
test("demo and malformed cache cannot pass the live report contract", () => {
  assert.equal(validReport({ mode: "preview", indicators: [], decision: {} }), false);
  assert.equal(validReport(null), false);
  assert.equal(validReport({ mode: "live", generated_at: "broken", indicators: [{}], decision: {} }), false);
});
