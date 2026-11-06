"""Collect price / same-snapshot IOPV - 1; never silently fall back to NAV.

Schema 1 histories mixed IOPV and delayed NAV and are intentionally not imported.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "site" / "data" / "etf-premiums.json"
HISTORY_TARGET = ROOT / "data" / "etf-premium-history.json"
PUBLISHED_URL = "https://uui000718-ai.github.io/us-market-sentiment-app/data/etf-premiums.json"
QUOTE_URL = "https://qt.gtimg.cn/q="
SOURCE = "tencent-quote"
SHANGHAI = ZoneInfo("Asia/Shanghai")
HISTORY_TRADING_DAYS = 120
MIN_PERCENTILE_SAMPLES = 20
VENDOR_TOLERANCE_PP = 0.10
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


def number_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if math.isfinite(number) else None


def iso_time(value: object) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return result.astimezone(SHANGHAI) if result.tzinfo is not None else None


def completed_session(now: datetime) -> str:
    """Weekday expectation, not a claim to know Chinese holidays."""
    local = now.astimezone(SHANGHAI)
    day = local.date()
    if local.time() < wall_time(15):
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def fetch_text(url: str, *, encoding: str = "utf-8") -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "MarketPulseSentimentApp/2.0", "Accept": "*/*"})
            with urlopen(request, timeout=20) as response:
                return response.read().decode(encoding)
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"行情读取失败：{type(last_error).__name__}")


def parse_quotes(raw: str, codes: list[str], now: datetime) -> tuple[dict[str, dict], dict[str, str]]:
    """Tencent ETF fields 3/30/77/78 are price/time/premium/IOPV.

    Never substitute field 81, navBase, latestNav or a fund NAV endpoint.
    """
    quotes: dict[str, dict] = {}
    errors = {code: "行情响应缺少该基金" for code in codes}
    requested = set(codes)
    retrieved_at = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    for symbol, value in re.findall(r'v_((?:sh|sz)\d{6})="([^"\r\n]*)"', raw):
        code = symbol[2:]
        if code not in requested:
            continue
        fields = value.split("~")
        try:
            if len(fields) < 79 or fields[2] != code or symbol != ("sh" if code.startswith("5") else "sz") + code:
                raise ValueError("行情代码或字段结构不匹配")
            price, iopv, vendor = (number_or_none(fields[index]) for index in (3, 78, 77))
            if price is None or price <= 0 or iopv is None or iopv <= 0:
                raise ValueError("缺少有效IOPV或价格；不改用单位净值")
            if vendor is None:
                raise ValueError("缺少行情溢价率，无法交叉核验")
            if not re.fullmatch(r"\d{14}", fields[30]):
                raise ValueError("行情时间格式无效")
            quote_time = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
            if quote_time > now.astimezone(SHANGHAI) + timedelta(minutes=2) or quote_time.weekday() >= 5:
                raise ValueError("行情时间为未来或非工作日")
            premium = round((price / iopv - 1) * 100, 4)
            if abs(premium - vendor) > VENDOR_TOLERANCE_PP:
                raise ValueError("价格/IOPV与行情溢价率不一致")
            quote_date = quote_time.date().isoformat()
            status = "close" if quote_time.time() >= wall_time(15) else "intraday"
            if quote_date < completed_session(now):
                status = "stale"
            quotes[code] = {
                "price": price, "iopv": iopv, "premium": premium, "vendor_premium": vendor,
                "quote_date": quote_date, "quote_at": quote_time.isoformat(timespec="seconds"),
                "retrieved_at": retrieved_at, "source": SOURCE, "basis": "iopv",
                "retained": False, "status": status,
            }
            errors.pop(code, None)
        except (ValueError, OverflowError) as error:
            errors[code] = str(error)
    return quotes, errors


def current_metrics(codes: list[str], now: datetime) -> tuple[dict[str, dict], dict[str, str]]:
    symbols = [("sh" if code.startswith("5") else "sz") + code for code in codes]
    try:
        return parse_quotes(fetch_text(QUOTE_URL + ",".join(symbols), encoding="gb18030"), codes, now)
    except Exception as error:
        return {}, {code: str(error) for code in codes}


def valid_snapshot(item: object, now: datetime) -> bool:
    if not isinstance(item, dict) or item.get("basis") != "iopv" or item.get("source") != SOURCE:
        return False
    price, iopv, value, vendor = (number_or_none(item.get(key)) for key in ("price", "iopv", "premium", "vendor_premium"))
    quote_at, retrieved_at = iso_time(item.get("quote_at")), iso_time(item.get("retrieved_at"))
    if any(x is None for x in (price, iopv, value, vendor, quote_at, retrieved_at)) or price <= 0 or iopv <= 0:
        return False
    if quote_at > now + timedelta(minutes=2) or retrieved_at > now + timedelta(minutes=2) or quote_at.weekday() >= 5:
        return False
    if retrieved_at < quote_at - timedelta(minutes=2):
        return False
    return (item.get("quote_date") == quote_at.date().isoformat()
            and abs((price / iopv - 1) * 100 - value) <= 0.001
            and abs(value - vendor) <= VENDOR_TOLERANCE_PP)


def normalized_history_item(item: object, now: datetime) -> dict | None:
    if not isinstance(item, dict) or item.get("session") != "close":
        return None
    current = {**item, "price": item.get("close"), "quote_date": item.get("date")}
    if not valid_snapshot(current, now):
        return None
    quote_at = iso_time(item["quote_at"])
    if quote_at.time() < wall_time(15):
        return None
    return {key: item[key] for key in (
        "date", "close", "iopv", "premium", "vendor_premium", "quote_at", "retrieved_at", "source", "basis", "session"
    )}


def merge_history(*groups: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    by_date: dict[str, dict] = {}
    for group in groups:
        for item in group:
            record = normalized_history_item(item, now)
            if record is None:
                continue
            prior = by_date.get(record["date"])
            if prior is None or (record["quote_at"], record["retrieved_at"]) >= (prior["quote_at"], prior["retrieved_at"]):
                by_date[record["date"]] = record
    return [by_date[key] for key in sorted(by_date)][-HISTORY_TRADING_DAYS:]


def current_history_item(metric: dict, now: datetime, known_dates: set[str] | None = None) -> list[dict]:
    if not valid_snapshot(metric, now) or metric.get("retained"):
        return []
    quote_at = iso_time(metric["quote_at"])
    if quote_at.time() < wall_time(15):
        return []
    # Old quotes can be displayed on holidays, but do not create new history.
    if metric["quote_date"] != completed_session(now) and metric["quote_date"] not in (known_dates or set()):
        return []
    return [{
        "date": metric["quote_date"], "close": metric["price"], "iopv": metric["iopv"],
        "premium": metric["premium"], "vendor_premium": metric["vendor_premium"],
        "quote_at": metric["quote_at"], "retrieved_at": metric["retrieved_at"],
        "source": metric["source"], "basis": "iopv", "session": "close",
    }]


def read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_saved_history(now: datetime | None = None) -> dict[str, list[dict]]:
    payload = read_json(HISTORY_TARGET)
    if payload.get("schema_version") != 2 or payload.get("basis") != "iopv":
        return {}
    funds = payload.get("funds", {})
    if not isinstance(funds, dict):
        return {}
    return {str(code): merge_history(items, now=now) for code, items in funds.items() if isinstance(items, list)}


def previous_currents(payload: dict, now: datetime) -> dict[str, dict]:
    if payload.get("schema_version") != 2 or payload.get("basis") != "iopv":
        return {}
    funds = payload.get("funds")
    if not isinstance(funds, list):
        return {}
    return {fund["code"]: fund["current"] for fund in funds
            if isinstance(fund, dict) and fund.get("code") in ETF_NAMES and valid_snapshot(fund.get("current"), now)}


def load_previous_current(now: datetime) -> dict[str, dict]:
    result = previous_currents(read_json(TARGET), now)
    try:
        with urlopen(Request(PUBLISHED_URL, headers={"User-Agent": "MarketPulseSentimentApp/2.0"}), timeout=15) as response:
            remote = previous_currents(json.load(response), now)
        for code, current in remote.items():
            if code not in result or current["quote_at"] > result[code]["quote_at"]:
                result[code] = current
    except Exception:
        pass
    return result


def nice_step(raw_step: float) -> float:
    if not math.isfinite(raw_step) or raw_step <= 0:
        return 1.0
    exponent = math.floor(math.log10(raw_step))
    scale = 10 ** exponent
    fraction = raw_step / scale
    nice_fraction = next((value for value in (1, 2, 2.5, 5, 10) if fraction <= value), 10)
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
    a, b, c, d = cutoffs
    return (
        (BIN_KEYS[0], f"< {a:g}%", None, a),
        (BIN_KEYS[1], f"{a:g}%–{b:g}%", a, b),
        (BIN_KEYS[2], f"{b:g}%–{c:g}%", b, c),
        (BIN_KEYS[3], f"{c:g}%–{d:g}%", c, d),
        (BIN_KEYS[4], f"≥ {d:g}%", d, None),
    )


def distribution(values: list[float]) -> list[dict]:
    return [{"key": key, "label": label, "count": sum(
        (lower is None or value >= lower) and (upper is None or value < upper) for value in values
    )} for key, label, lower, upper in fund_bins(values)]


def percentile(values: list[float], current: float | None) -> float | None:
    if current is None or not values:
        return None
    return round(sum(value <= current for value in values) / len(values) * 100, 1)


def build_report(metrics: dict[str, dict], saved: dict[str, list[dict]], previous: dict[str, dict],
                 errors: dict[str, str], now: datetime) -> tuple[dict, dict]:
    histories: dict[str, list[dict]] = {}
    funds = []
    for code, name in ETF_NAMES.items():
        history = merge_history(saved.get(code, []), now=now)
        metric = metrics.get(code, {})
        error = errors.get(code, "")
        candidate = metric if valid_snapshot(metric, now) else None
        prior = previous.get(code)
        if prior is not None and not valid_snapshot(prior, now):
            prior = None
        if history:
            latest = history[-1]
            historical_current = {**latest, "price": latest["close"], "quote_date": latest["date"]}
            historical_current = {key: value for key, value in historical_current.items() if key not in ("close", "date", "session")}
            if prior is None or historical_current["quote_at"] > prior["quote_at"]:
                prior = historical_current
        if candidate and prior and candidate["quote_at"] < prior["quote_at"]:
            candidate = None
            error = "新响应行情时间早于已保存快照；保留较新数据"
        history = merge_history(history, current_history_item(candidate or {}, now, {item["date"] for item in history}), now=now)
        histories[code] = history
        if candidate:
            current = candidate.copy()
        else:
            if prior:
                current = {**prior, "retained": True, "status": "retained"}
            else:
                current = {"price": None, "iopv": None, "premium": None, "vendor_premium": None,
                           "quote_date": "", "quote_at": "", "retrieved_at": "", "source": SOURCE,
                           "basis": "iopv", "retained": False, "status": "unavailable"}
            error = error or "未取得通过校验的IOPV行情"
        values = [item["premium"] for item in history]
        count = len(values)
        funds.append({
            "code": code, "name": name, "current": current,
            "sample_count": count,
            "percentile": percentile(values, current["premium"]) if count >= MIN_PERCENTILE_SAMPLES else None,
            "distribution": distribution(values),
            "history_from": history[0]["date"] if history else None,
            "history_to": history[-1]["date"] if history else None,
            "history_status": "complete" if count >= HISTORY_TRADING_DAYS else "accumulating",
            "error": error,
        })
    dates = sorted({item["date"] for items in histories.values() for item in items})
    payload = {
        "schema_version": 2, "basis": "iopv", "history_mode": "daily-close-iopv",
        "fetched_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "window": {"trading_days": HISTORY_TRADING_DAYS, "from": dates[0] if dates else None, "to": dates[-1] if dates else None},
        "min_percentile_samples": MIN_PERCENTILE_SAMPLES,
        "methodology": {
            "current": "同一行情快照的场内价格 / IOPV - 1；与行情溢价字段交叉校验，不使用单位净值替代",
            "history": "每日收盘后采集IOPV参考溢价；仅统计已验证的同口径记录，最多保留120个交易日",
            "percentile": "同口径收盘样本中溢价率小于等于当前值的比例；少于20个有效样本时暂不展示",
        },
        "source": {"name": "腾讯财经公开ETF行情（非交易所授权实时行情）", "homepage": "https://gu.qq.com/", "api": QUOTE_URL},
        "migration": "旧记录混有单位净值口径，未导入IOPV统计；不伪造历史IOPV数据",
        "funds": funds,
    }
    return payload, {"schema_version": 2, "basis": "iopv", "max_trading_days": HISTORY_TRADING_DAYS, "funds": histories}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    now = datetime.now(timezone.utc)
    metrics, errors = current_metrics(list(ETF_NAMES), now)
    payload, history = build_report(metrics, load_saved_history(now), load_previous_current(now), errors, now)
    write_json(HISTORY_TARGET, history)
    write_json(TARGET, payload)
    valid = sum(fund["current"]["premium"] is not None for fund in payload["funds"])
    print(f"已保存{len(ETF_NAMES)}只ETF的IOPV同口径数据；{valid}只具备有效快照，历史按实际收盘样本累积（上限120日）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
