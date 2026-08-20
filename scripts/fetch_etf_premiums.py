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
API_BASE = "https://api.freebacktrack.tech"
HISTORY_DAYS = 180
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
PREMIUM_BINS = (
    ("discount", "折价 < 0%", None, 0.0),
    ("low", "0%–3%", 0.0, 3.0),
    ("medium", "3%–6%", 3.0, 6.0),
    ("high", "6%–10%", 6.0, 10.0),
    ("extreme", "≥ 10%", 10.0, None),
)


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


def distribution(values: list[float]) -> list[dict]:
    result: list[dict] = []
    for key, label, lower, upper in PREMIUM_BINS:
        count = sum(
            (lower is None or value >= lower) and (upper is None or value < upper)
            for value in values
        )
        result.append({"key": key, "label": label, "count": count})
    return result


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
    start_date = end_date - timedelta(days=HISTORY_DAYS)
    start = start_date.isoformat()
    end = end_date.isoformat()
    codes = list(ETF_NAMES)
    metrics = current_metrics(codes)
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
        history = histories.get(code, [])
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
            "history": history,
            "error": errors.get(code, ""),
        })

    payload = {
        "schema_version": 1,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": {"calendar_days": HISTORY_DAYS, "from": start, "to": end},
        "methodology": {
            "current": "实时场内价格 / 估算净值基准 - 1",
            "history": "每日场内收盘价 / 同日官方单位净值 - 1",
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
    print(f"已保存 {len(funds)} 只纳指ETF的近{HISTORY_DAYS}天溢价数据：{TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
