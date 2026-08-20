from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "site" / "data" / "etf-premiums.json"
HISTORY_TARGET = ROOT / "data" / "etf-premium-history.json"
API_BASE = "https://api.freebacktrack.tech"
HISTORY_TRADING_DAYS = 120
FETCH_CALENDAR_DAYS = 240
ETF_NAMES = {
    "159501": "嘉实纳斯达克100ETF",
    "159696": "易方达纳斯达克100ETF",
    "513870": "富国纳斯达克100ETF",
    "159632": "华安纳斯达克100ETF",
    "159659": "招商纳斯达克100ETF",
    "159509": "景顺长城纳斯达克科技ETF",
    "513100": "国泰纳斯达克100ETF",
    "159941": "广发纳斯达克100ETF",
    "513300": "华夏纳斯达克100ETF",
    "159660": "汇添富纳斯达克100ETF",
    "513390": "博时纳斯达克100ETF",
    "159513": "大成纳斯达克100ETF",
    "513110": "华泰柏瑞纳斯达克100ETF",
}
BIN_KEYS = ("discount", "low", "medium", "high", "extreme")


def fetch_json(url: str, *, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "User-Agent": "MarketPulseSentimentApp/1.0",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
            with urlopen(request, timeout=35) as response:
                return json.load(response)
        except Exception as error:  # network retry
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"读取 {url} 失败：{last_error}")


def candle_date(timestamp: object) -> str | None:
    try:
        value = float(timestamp)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return datetime.fromtimestamp(value, ZoneInfo("Asia/Shanghai")).date().isoformat()


def build_history(nav_items: list[dict], candles: list[dict], start: str, end: str) -> list[dict]:
    nav_by_date: dict[str, float] = {}
    for item in nav_items:
        item_date = str(item.get("date", ""))[:10]
        try:
            nav = float(item.get("nav"))
        except (TypeError, ValueError):
            continue
        if start <= item_date <= end and math.isfinite(nav) and nav > 0:
            nav_by_date[item_date] = nav

    history: list[dict] = []
    for candle in candles:
        item_date = candle_date(candle.get("t"))
        if not item_date or not (start <= item_date <= end):
            continue
        nav = nav_by_date.get(item_date)
        try:
            close = float(candle.get("c"))
        except (TypeError, ValueError):
            continue
        if nav is None or not math.isfinite(close) or close <= 0:
            continue
        history.append({
            "date": item_date,
            "close": round(close, 4),
            "nav": round(nav, 4),
            "premium": round((close / nav - 1) * 100, 4),
        })
    history.sort(key=lambda item: item["date"])
    return history


def nice_step(raw_step: float) -> float:
    if not math.isfinite(raw_step) or raw_step <= 0:
        return 1.0
    exponent = math.floor(math.log10(raw_step))
    scale = 10 ** exponent
    fraction = raw_step / scale
    if fraction <= 1:
        nice_fraction = 1
    elif fraction <= 2:
        nice_fraction = 2
    elif fraction <= 2.5:
        nice_fraction = 2.5
    elif fraction <= 5:
        nice_fraction = 5
    else:
        nice_fraction = 10
    return nice_fraction * scale


def fund_bins(values: list[float]) -> tuple[tuple[str, str, float | None, float | None], ...]:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        cutoffs = (0.0, 3.0, 6.0, 10.0)
    else:
        span = finite[-1] - finite[0]
        step = nice_step(span / 4) if span > 0 else nice_step(max(abs(finite[0]) * 0.1, 0.5))
        first = math.floor(finite[0] / step) * step + step
        cutoffs = tuple(round(first + index * step, 4) for index in range(4))

    def display(value: float) -> str:
        return f"{value:g}%"

    a, b, c, d = cutoffs
    return (
        (BIN_KEYS[0], f"< {display(a)}", None, a),
        (BIN_KEYS[1], f"{display(a)}–{display(b)}", a, b),
        (BIN_KEYS[2], f"{display(b)}–{display(c)}", b, c),
        (BIN_KEYS[3], f"{display(c)}–{display(d)}", c, d),
        (BIN_KEYS[4], f"≥ {display(d)}", d, None),
    )


def distribution(values: list[float]) -> list[dict]:
    result: list[dict] = []
    for key, label, lower, upper in fund_bins(values):
        count = sum(
            (lower is None or value >= lower) and (upper is None or value < upper)
            for value in values
        )
        result.append({"key": key, "label": label, "count": count})
    return result


def load_saved_history() -> dict[str, list[dict]]:
    if not HISTORY_TARGET.exists():
        return {}
    try:
        payload = json.loads(HISTORY_TARGET.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(code): items
        for code, items in payload.get("funds", {}).items()
        if isinstance(items, list)
    }


def merge_history(*groups: list[dict]) -> list[dict]:
    by_date: dict[str, dict] = {}
    for group in groups:
        for item in group:
            item_date = str(item.get("date", ""))[:10]
            try:
                premium_value = float(item.get("premium"))
            except (TypeError, ValueError):
                continue
            if len(item_date) != 10 or not math.isfinite(premium_value):
                continue
            by_date[item_date] = {
                "date": item_date,
                "close": number_or_none(item.get("close")),
                "nav": number_or_none(item.get("nav")),
                "premium": round(premium_value, 4),
            }
    return [by_date[key] for key in sorted(by_date)][-HISTORY_TRADING_DAYS:]


def current_history_item(metric: dict) -> list[dict]:
    item_date = str(metric.get("quoteDate") or "")[:10]
    close = number_or_none(metric.get("price") or metric.get("currentPrice") or metric.get("close"))
    nav = number_or_none(metric.get("navBase") or metric.get("iopv"))
    premium_value = number_or_none(metric.get("premiumPercent"))
    if len(item_date) != 10 or close is None or nav is None or premium_value is None:
        return []
    return [{"date": item_date, "close": close, "nav": nav, "premium": premium_value}]


def percentile(values: list[float], current: float | None) -> float | None:
    if current is None or not values:
        return None
    return round(sum(value <= current for value in values) / len(values) * 100, 1)


def fetch_history(code: str, start: str, end: str) -> list[dict]:
    nav_url = f"{API_BASE}/api/holdings/nav-history?{urlencode({'code': code, 'from': start, 'to': end})}"
    kline_url = f"{API_BASE}/api/markets/kline/{code}?{urlencode({'tf': '1d', 'limit': 260, 'market': 'cn'})}"
    nav_payload = fetch_json(nav_url)
    kline_payload = fetch_json(kline_url)
    return build_history(nav_payload.get("items", []), kline_payload.get("candles", []), start, end)


def current_metrics(codes: list[str]) -> dict[str, dict]:
    payload = {
        "codes": codes,
        "fundKinds": {code: "exchange" for code in codes},
    }
    response = fetch_json(f"{API_BASE}/api/markets/fund-metrics", payload=payload)
    return {
        str(item.get("code")): item
        for item in response.get("items", [])
        if item.get("ok") is not False and item.get("code")
    }


def number_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if math.isfinite(number) else None


def main() -> int:
    end_date = date.today()
    start_date = end_date - timedelta(days=FETCH_CALENDAR_DAYS)
    start = start_date.isoformat()
    end = end_date.isoformat()
    codes = list(ETF_NAMES)
    metrics = current_metrics(codes)
    saved_histories = load_saved_history()
    histories: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_history, code, start, end): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                histories[code] = future.result()
            except Exception as error:
                histories[code] = []
                errors[code] = str(error)

    funds = []
    for code, fallback_name in ETF_NAMES.items():
        metric = metrics.get(code, {})
        history = merge_history(
            saved_histories.get(code, []),
            histories.get(code, []),
            current_history_item(metric),
        )
        histories[code] = history
        values = [float(item["premium"]) for item in history]
        current_premium = number_or_none(metric.get("premiumPercent"))
        funds.append({
            "code": code,
            "name": str(metric.get("name") or fallback_name),
            "current": {
                "price": number_or_none(metric.get("price")),
                "nav_base": number_or_none(metric.get("navBase") or metric.get("iopv")),
                "premium": current_premium,
                "quote_date": str(metric.get("quoteDate") or ""),
                "nav_date": str(metric.get("latestNavDate") or metric.get("navDate") or ""),
            },
            "sample_count": len(history),
            "percentile": percentile(values, current_premium),
            "distribution": distribution(values),
            "error": errors.get(code, ""),
        })

    all_history = [item for items in histories.values() for item in items]
    history_dates = sorted({str(item.get("date", "")) for item in all_history if item.get("date")})
    payload = {
        "schema_version": 1,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": {
            "trading_days": HISTORY_TRADING_DAYS,
            "from": history_dates[0] if history_dates else start,
            "to": history_dates[-1] if history_dates else end,
        },
        "methodology": {
            "current": "实时场内价格 / 估算净值基准 - 1",
            "history": "每日收盘后记录场内价格与估算净值；历史接口补齐后按官方单位净值校正",
            "percentile": "历史样本中溢价率小于等于当前溢价率的比例",
        },
        "source": {
            "homepage": "https://freebacktrack.tech/index.html",
            "api": API_BASE,
        },
        "funds": funds,
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(TARGET)
    history_payload = {"schema_version": 1, "max_trading_days": HISTORY_TRADING_DAYS, "funds": histories}
    HISTORY_TARGET.parent.mkdir(parents=True, exist_ok=True)
    history_temporary = HISTORY_TARGET.with_suffix(".json.tmp")
    history_temporary.write_text(json.dumps(history_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    history_temporary.replace(HISTORY_TARGET)
    print(f"已保存 {len(funds)} 只纳指ETF的近{HISTORY_TRADING_DAYS}个交易日溢价数据：{TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
