"""Independent market context; deliberately does not alter buy/sell scores."""
from __future__ import annotations

import csv
import io
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "site" / "data" / "market-context.json"
PUBLISHED = "https://uui000718-ai.github.io/us-market-sentiment-app/data/market-context.json"
SPECS = {
    "nasdaq_participation": ("纳指等权相对表现", "relative", "QQQE / QQQ"),
    "sp500_participation": ("标普等权相对表现", "relative", "RSP / SPY"),
    "real_yield": ("10年期实际利率", "yield", "DFII10"),
    "financial_stress": ("金融压力指数", "stress", "STLFSI4"),
}


def request_bytes(url: str, timeout: int = 20) -> bytes:
    last_error = None
    for attempt in range(2):
        try:
            with urlopen(Request(url, headers={"User-Agent": "MarketPulse/1.0", "Accept": "application/json,text/csv,*/*"}), timeout=timeout) as response:
                return response.read(2_000_000)
        except Exception as error:
            last_error = error
            if attempt == 0:
                time.sleep(1)
    raise RuntimeError(str(last_error))


def normalize_points(rows: list[dict]) -> list[dict]:
    points = {}
    for row in rows:
        try:
            day = date.fromisoformat(str(row["date"])).isoformat()
            value = float(row["value"])
        except (KeyError, ValueError, TypeError):
            continue
        if math.isfinite(value):
            points[day] = value
    return [{"date": day, "value": points[day]} for day in sorted(points)]


def fred_series(code: str, start: date) -> list[dict]:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode({"id": code, "cosd": start.isoformat()})
    body = request_bytes(url).decode("utf-8-sig")
    return normalize_points([{"date": row.get("observation_date") or row.get("DATE"), "value": row.get(code)} for row in csv.DictReader(io.StringIO(body))])


def closed_price_points(result: dict, now: datetime) -> list[dict]:
    ny_now = now.astimezone(ZoneInfo("America/New_York"))
    adjusted = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")
    if not adjusted:
        raise ValueError("Adjusted close unavailable; refusing to mix price conventions")
    rows = []
    for timestamp, value in zip(result.get("timestamp", []), adjusted):
        day = datetime.fromtimestamp(timestamp, ZoneInfo("America/New_York")).date()
        if day > ny_now.date() or (day == ny_now.date() and (ny_now.hour, ny_now.minute) < (16, 5)):
            continue
        if value is not None and float(value) > 0:
            rows.append({"date": day.isoformat(), "value": value})
    return normalize_points(rows)


def yahoo_series(symbol: str, now: datetime) -> list[dict]:
    query = urlencode({"range": "1y", "interval": "1d", "events": "history"})
    payload = json.loads(request_bytes(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"))
    return closed_price_points(payload["chart"]["result"][0], now)


def relative_metric(left: list[dict], right: list[dict]) -> dict:
    a = {p["date"]: p["value"] for p in normalize_points(left) if p["value"] > 0}
    b = {p["date"]: p["value"] for p in normalize_points(right) if p["value"] > 0}
    days = sorted(a.keys() & b.keys())
    if len(days) < 61:
        raise ValueError("At least 61 aligned daily observations are required")
    ratios = [{"date": day, "value": a[day] / b[day]} for day in days]
    changes = {str(n): round((ratios[-1]["value"] / ratios[-n - 1]["value"] - 1) * 100, 3) for n in (20, 60)}
    return {"as_of": days[-1], "value": changes["20"], "unit": "%", "changes": changes, "sample_count": len(days), "series": ratios[-61:]}


def series_metric(points: list[dict], kind: str) -> dict:
    points = normalize_points(points)
    if len(points) < (21 if kind == "yield" else 5):
        raise ValueError("Insufficient valid FRED observations")
    last = points[-1]
    if kind == "yield":
        previous = points[-21]
        change = round((last["value"] - previous["value"]) * 100, 2)
    else:
        cutoff = (date.fromisoformat(last["date"]) - timedelta(days=28)).isoformat()
        candidates = [p for p in points if p["date"] <= cutoff]
        if not candidates:
            raise ValueError("Four-week comparison unavailable")
        previous = candidates[-1]
        change = round(last["value"] - previous["value"], 4)
    # Fixed 3-year trailing observation window, explicitly dated in the payload.
    cutoff = (date.fromisoformat(last["date"]) - timedelta(days=365 * 3)).isoformat()
    window = [p for p in points if p["date"] >= cutoff]
    percentile = round(sum(p["value"] <= last["value"] for p in window) / len(window) * 100, 1)
    return {
        "as_of": last["date"], "value": last["value"], "unit": "%" if kind == "yield" else "指数",
        "change": change, "comparison_date": previous["date"], "percentile": percentile,
        "sample_count": len(window), "window_from": window[0]["date"], "window_to": last["date"],
        "series": points[-(61 if kind == "yield" else 26):],
    }


def previous_items() -> dict[str, dict]:
    candidates = []
    if TARGET.exists():
        try:
            candidates.append(json.loads(TARGET.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    try:
        candidates.append(json.loads(request_bytes(PUBLISHED, timeout=5)))
    except Exception:
        pass
    result = {}
    for payload in candidates:
        for item in payload.get("items", []):
            if not isinstance(item, dict) or item.get("value") is None:
                continue
            old = result.get(item.get("id"), {})
            if str(item.get("retrieved_at", "")) >= str(old.get("retrieved_at", "")):
                result[item["id"]] = item
    return result


def main() -> int:
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    start = now.date() - timedelta(days=365 * 3 + 40)
    sources, errors = {}, {}
    jobs = {
        "QQQE": lambda: yahoo_series("QQQE", now), "QQQ": lambda: yahoo_series("QQQ", now),
        "RSP": lambda: yahoo_series("RSP", now), "SPY": lambda: yahoo_series("SPY", now),
        "DFII10": lambda: fred_series("DFII10", start), "STLFSI4": lambda: fred_series("STLFSI4", start),
    }
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = {pool.submit(task): key for key, task in jobs.items()}
        for future in as_completed(pending):
            key = pending[future]
            try:
                sources[key] = future.result()
            except Exception as error:
                errors[key] = type(error).__name__
    previous = previous_items()
    builders = {
        "nasdaq_participation": lambda: relative_metric(sources["QQQE"], sources["QQQ"]),
        "sp500_participation": lambda: relative_metric(sources["RSP"], sources["SPY"]),
        "real_yield": lambda: series_metric(sources["DFII10"], "yield"),
        "financial_stress": lambda: series_metric(sources["STLFSI4"], "stress"),
    }
    items = []
    for key, (title, kind, symbol) in SPECS.items():
        base = {"id": key, "title": title, "kind": kind, "symbol": symbol}
        try:
            item = {**base, **builders[key](), "retrieved_at": stamp, "retained": False, "error": ""}
        except Exception:
            item = {**previous.get(key, {}), **base, "retained": True, "error": "本次抓取失败，保留上次可用数据"}
            if item.get("value") is None:
                item.update({"value": None, "as_of": None, "series": [], "error": "数据暂时不可用"})
        items.append(item)
    payload = {"schema_version": 1, "fetched_at": stamp, "items": items, "source_errors": errors}
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(TARGET)
    print(f"Market context: {sum(item['value'] is not None and not item['retained'] for item in items)}/4 refreshed; saved to {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
