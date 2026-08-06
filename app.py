#!/usr/bin/env python3
"""美股情绪监控：采集、评分与 Server酱³ 手机推送。"""

from __future__ import annotations

import argparse
import csv
import email.utils
import html
import io
import json
import math
import os
import re
import statistics
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

DECISION_WEIGHTS = {
    "aaii": 20,
    "ndx_forward_pe": 10,
    "naaim": 20,
    "vix": 25,
    "qqq_rsi": 25,
}


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def pct_change(values: list[float], periods: int) -> float | None:
    if len(values) <= periods or not values[-periods - 1]:
        return None
    return values[-1] / values[-periods - 1] - 1


def yahoo_history(symbol: str, days: int = 220) -> dict[str, Any]:
    end = int(time.time())
    start = int((datetime.now(timezone.utc) - timedelta(days=days * 2)).timestamp())
    encoded = quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?period1={start}&period2={end}&interval=1d&events=history"
    )
    timeout = float(os.getenv("REQUEST_TIMEOUT", "15"))
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    indicators = result.get("indicators", {})
    series = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    if not series:
        series = (indicators.get("quote") or [{}])[0].get("close", [])
    points = [
        (datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), float(value))
        for ts, value in zip(timestamps, series)
        if value is not None and math.isfinite(float(value))
    ]
    if not points:
        raise ValueError(f"{symbol} 没有可用行情")
    return {"symbol": symbol, "dates": [p[0] for p in points], "closes": [p[1] for p in points]}


def demo_history(symbol: str, days: int = 180) -> dict[str, Any]:
    """确定性的离线演示数据，仅供界面/流程验证。"""
    bases = {"^VIX": 17.8, "QQQ": 560, "^NDX": 23000}
    base = bases.get(symbol, 100 + (sum(map(ord, symbol)) % 25))
    slope = {"SPY": 0.0010, "TLT": -0.0001, "HYG": 0.00025, "LQD": 0.00005}.get(symbol, 0.00035)
    today = datetime.now(timezone.utc).date()
    values: list[float] = []
    dates: list[str] = []
    for i in range(days):
        wave = math.sin(i * 0.23 + sum(map(ord, symbol))) * 0.012
        values.append(base * (1 + slope * (i - days + 1)) * (1 + wave))
        dates.append((today - timedelta(days=days - i - 1)).isoformat())
    return {"symbol": symbol, "dates": dates, "closes": values}


def http_bytes(url: str, *, referer: str | None = None) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    with urlopen(request, timeout=float(os.getenv("REQUEST_TIMEOUT", "20"))) as response:
        return response.read()


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(html.unescape("".join(self._cell)).strip())
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def fetch_aaii() -> dict[str, Any]:
    try:
        feed = ElementTree.fromstring(http_bytes("https://insights.aaii.com/feed"))
        content_tag = "{http://purl.org/rss/1.0/modules/content/}encoded"
        for item in feed.findall(".//item"):
            title = item.findtext("title") or ""
            if "Sentiment Survey" not in title:
                continue
            content = item.findtext(content_tag) or item.findtext("description") or ""
            plain = html.unescape(re.sub(r"<[^>]+>", " ", content)).replace("\xa0", " ")
            results = re.search(
                r"This week.s Sentiment Survey results:.*?Bullish:\s*([0-9.]+)%.*?"
                r"Neutral:\s*([0-9.]+)%.*?Bearish:\s*([0-9.]+)%",
                plain,
                re.I | re.S,
            )
            if not results:
                continue
            bullish, neutral, bearish = map(float, results.groups())
            published = email.utils.parsedate_to_datetime(item.findtext("pubDate") or "")
            directional = bullish / (bullish + bearish) * 100 if bullish + bearish else 50.0
            return {
                "date": published.date().isoformat(),
                "bullish": bullish,
                "neutral": neutral,
                "bearish": bearish,
                "spread": bullish - bearish,
                "score": directional,
                "source": "AAII Insights官方周报",
            }
    except Exception:
        pass

    url = "https://www.aaii.com/sentimentsurvey/sent_results"
    body = http_bytes(url, referer="https://www.aaii.com/sentimentsurvey").decode("utf-8", "ignore")
    parser = _TableParser()
    parser.feed(body)
    for row in parser.rows:
        if len(row) < 4 or not re.fullmatch(r"[A-Z][a-z]{2}\s+\d{1,2}", row[0]):
            continue
        bullish, neutral, bearish = [float(value.rstrip("% ")) for value in row[1:4]]
        parsed = datetime.strptime(f"2000 {row[0]}", "%Y %b %d")
        now = datetime.now(timezone.utc)
        year = now.year - 1 if parsed.month > now.month + 1 else now.year
        report_date = parsed.replace(year=year).date().isoformat()
        directional = bullish / (bullish + bearish) * 100 if bullish + bearish else 50.0
        return {
            "date": report_date,
            "bullish": bullish,
            "neutral": neutral,
            "bearish": bearish,
            "spread": bullish - bearish,
            "score": directional,
            "source": "AAII官方历史结果页",
        }
    raise ValueError("AAII 页面中未找到最新调查数据")


def _xlsx_rows(payload: bytes) -> list[list[str]]:
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("x:si", namespace):
                shared.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in sheet.findall(".//x:sheetData/x:row", namespace):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", namespace):
            reference = cell.get("r", "A1")
            letters = re.match(r"[A-Z]+", reference)
            if not letters:
                continue
            column = 0
            for char in letters.group(0):
                column = column * 26 + ord(char) - 64
            value_node = cell.find("x:v", namespace)
            value = "" if value_node is None else (value_node.text or "")
            if cell.get("t") == "s" and value:
                value = shared[int(value)]
            values[column - 1] = value
        if values:
            rows.append([values.get(index, "") for index in range(max(values) + 1)])
    return rows


def fetch_naaim() -> dict[str, Any]:
    page_url = "https://www.naaim.org/programs/naaim-exposure-index/"
    xlsx_url = os.getenv("NAAIM_XLSX_URL", "").strip()
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        if not xlsx_url:
            page = http_bytes(page_url).decode("utf-8", "ignore")
            matches = re.findall(r"https?[^\"'<> ]+?\.xlsx", html.unescape(page), re.I)
            if not matches:
                raise ValueError("NAAIM 页面未提供公开 Excel")
            xlsx_url = matches[0]
        payload = http_bytes(xlsx_url, referer=page_url)
        records: list[tuple[str, float]] = []
        for row in _xlsx_rows(payload)[1:]:
            if len(row) < 2:
                continue
            try:
                serial, exposure = float(row[0]), float(row[1])
            except ValueError:
                continue
            report_date = (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat()
            records.append((report_date, exposure))
        if not records:
            raise ValueError("NAAIM Excel 中未找到暴露指数")
        records.sort(key=lambda item: item[0], reverse=True)
        latest_date, latest_exposure = records[0]
        recent = [value for _, value in records[:4]]
        candidates.append({
            "date": latest_date,
            "exposure": latest_exposure,
            "four_week_average": statistics.mean(recent),
            "score": clamp(latest_exposure),
            "source": "NAAIM官方Excel",
        })
    except Exception as official_error:
        errors.append(f"NAAIM官方源失败（{official_error}）")
    try:
        candidates.append(fetch_macromicro_naaim())
    except Exception as macromicro_error:
        errors.append(f"MacroMicro授权API失败（{macromicro_error}）")
    try:
        candidates.append(load_manual_naaim())
    except Exception as manual_error:
        errors.append(f"GitHub手动记录失败（{manual_error}）")
    if not candidates:
        raise ValueError("；".join(errors))
    return max(candidates, key=lambda item: str(item["date"]))


def manual_naaim_path() -> Path:
    configured = Path(os.getenv("NAAIM_MANUAL_PATH", "data/naaim_manual.json"))
    return configured if configured.is_absolute() else ROOT / configured


def load_manual_naaim(path: Path | None = None) -> dict[str, Any]:
    source_path = path or manual_naaim_path()
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    records: list[tuple[str, float]] = []
    for row in payload.get("records", []):
        report_date = datetime.strptime(str(row["date"]), "%Y-%m-%d").date().isoformat()
        exposure = float(row["exposure"])
        if not math.isfinite(exposure):
            continue
        records.append((report_date, exposure))
    if not records:
        raise ValueError("手动记录文件中没有有效数据")
    records.sort(key=lambda item: item[0], reverse=True)
    latest_date, latest_exposure = records[0]
    return {
        "date": latest_date,
        "exposure": latest_exposure,
        "four_week_average": statistics.mean(value for _, value in records[:4]),
        "score": clamp(latest_exposure),
        "source": "GitHub手动记录",
    }


def update_manual_naaim(exposure: float, report_date: str, path: Path | None = None) -> Path:
    if not math.isfinite(exposure) or not -200 <= exposure <= 200:
        raise ValueError("NAAIM数值必须是-200到200之间的数字")
    normalized_date = datetime.strptime(report_date, "%Y-%m-%d").date().isoformat()
    target = path or manual_naaim_path()
    records: list[dict[str, Any]] = []
    if target.exists():
        payload = json.loads(target.read_text(encoding="utf-8"))
        records = list(payload.get("records", []))
    records = [row for row in records if str(row.get("date")) != normalized_date]
    records.append({"date": normalized_date, "exposure": round(float(exposure), 4)})
    records.sort(key=lambda row: str(row["date"]), reverse=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"records": records[:260]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def fetch_cftc_asset_manager_positioning() -> dict[str, Any]:
    """读取CFTC标普500 E-mini期货中Asset Manager/Institutional周度仓位。"""
    query = urlencode({
        "$select": (
            "report_date_as_yyyy_mm_dd,open_interest_all,"
            "asset_mgr_positions_long,asset_mgr_positions_short,"
            "pct_of_oi_asset_mgr_long,pct_of_oi_asset_mgr_short"
        ),
        "$where": "cftc_contract_market_code='13874A'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": "160",
    })
    url = f"https://publicreporting.cftc.gov/resource/gpe5-46if.json?{query}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            rows = json.loads(http_bytes(url).decode("utf-8"))
            break
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    else:
        raise RuntimeError(f"CFTC官方接口连续3次请求失败：{last_error}") from last_error
    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            report_date = str(row["report_date_as_yyyy_mm_dd"])[:10]
            long_pct = float(row["pct_of_oi_asset_mgr_long"])
            short_pct = float(row["pct_of_oi_asset_mgr_short"])
            net_pct = long_pct - short_pct
        except (KeyError, TypeError, ValueError):
            continue
        records.append({
            "date": report_date,
            "long_pct": long_pct,
            "short_pct": short_pct,
            "net_pct": net_pct,
        })
    if not records:
        raise ValueError("CFTC数据集中没有E-mini S&P 500机构仓位")
    latest = records[0]
    net_values = [row["net_pct"] for row in records]
    percentile = sum(value <= latest["net_pct"] for value in net_values) / len(net_values) * 100
    return {
        **latest,
        "four_week_average": statistics.mean(row["net_pct"] for row in records[:4]),
        "three_year_percentile": percentile,
        "source": "CFTC TFF官方数据",
    }


def parse_macromicro_series(payload: dict[str, Any]) -> dict[str, Any]:
    series = payload.get("series")
    if not isinstance(series, list) or not series:
        raise ValueError("MacroMicro响应中没有series数据")
    valid = [row for row in series if isinstance(row, dict) and row.get("date") and row.get("val") is not None]
    if not valid:
        raise ValueError("MacroMicro series中没有有效NAAIM记录")
    valid.sort(key=lambda row: str(row["date"]), reverse=True)
    latest = valid[0]
    exposure = float(latest["val"])
    recent = [float(row["val"]) for row in valid[:4]]
    return {
        "date": str(latest["date"]),
        "exposure": exposure,
        "four_week_average": statistics.mean(recent),
        "score": clamp(exposure),
        "source": "MacroMicro授权API",
    }


def fetch_macromicro_naaim() -> dict[str, Any]:
    api_url = os.getenv("MACROMICRO_NAAIM_API_URL", "").strip()
    api_key = os.getenv("MACROMICRO_API_KEY", "").strip()
    if not api_url or not api_key:
        raise RuntimeError("未配置MACROMICRO_NAAIM_API_URL或MACROMICRO_API_KEY")
    parsed = urlparse(api_url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith("macromicro.me"):
        raise ValueError("MacroMicro API地址必须是macromicro.me的HTTPS地址")
    request = Request(
        api_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urlopen(request, timeout=float(os.getenv("REQUEST_TIMEOUT", "20"))) as response:
        return parse_macromicro_series(json.load(response))


def _load_ndx_history() -> list[tuple[datetime, float]]:
    path = ROOT / "reference" / "ndx_forward_pe_history.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return [(datetime.strptime(row["date"], "%Y-%m"), float(row["forward_pe"])) for row in csv.DictReader(handle)]


def fetch_ndx_forward_pe() -> dict[str, Any]:
    override = os.getenv("NDX_FORWARD_PE_OVERRIDE", "").strip()
    if override:
        forward_pe = float(override)
        as_of = datetime.strptime(os.getenv("NDX_FORWARD_PE_DATE", datetime.now().date().isoformat()), "%Y-%m-%d")
        source = "手动配置"
    else:
        try:
            page = http_bytes("https://vcpscanner.com/market-valuation/nasdaq-100").decode("utf-8", "ignore")
            normalized = html.unescape(page).replace('\\"', '"')
            match = re.search(
                r'"index_name":"nasdaq100","snapshot_date":"([^"]+)".*?"forward_pe":([0-9.]+)',
                normalized,
                re.S,
            )
            if not match:
                raise ValueError("页面未找到 Nasdaq-100 forward_pe")
            as_of = datetime.strptime(match.group(1), "%Y-%m-%d")
            forward_pe = float(match.group(2))
            source = "VCP Scanner（日更成分股聚合）"
        except Exception:
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise RuntimeError("缺少 pypdf，请先安装 requirements.txt") from exc
            url = "https://www.nasdaq.com/docs/index/global-index-investment-insights"
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(http_bytes(url))).pages)
            line = next((line for line in text.splitlines() if "Nasdaq-100" in line and "%" in line), "")
            match = re.search(r"(\d+\.\d+)\s+(\d+\.\d+)\s+([+-]\d+\.\d+)%\s*$", line)
            if not match:
                raise ValueError("Nasdaq 官方 PDF 中未识别到 Nasdaq-100 NTM P/E")
            forward_pe = float(match.group(1))
            date_match = re.search(r"Data as of\s+(\d{1,2}/\d{1,2}/\d{4})", text)
            as_of = datetime.strptime(date_match.group(1), "%m/%d/%Y") if date_match else datetime.now(timezone.utc).replace(tzinfo=None)
            source = "Nasdaq Global Index Insights（备用）"
    start = as_of.replace(year=as_of.year - int(os.getenv("NDX_PE_PERCENTILE_YEARS", "10")))
    history = [value for date, value in _load_ndx_history() if start <= date <= as_of]
    history.append(forward_pe)
    percentile = sum(value <= forward_pe for value in history) / len(history) * 100
    return {
        "date": as_of.date().isoformat(),
        "forward_pe": forward_pe,
        "ten_year_median": statistics.median(history),
        "percentile": percentile,
        "score": 100 - percentile,
        "source": source,
    }


def wilder_rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        raise ValueError("计算 RSI 的历史行情不足")
    changes = [current - previous for previous, current in zip(values, values[1:])]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    if average_gain == 0:
        return 0.0
    return 100 - 100 / (1 + average_gain / average_loss)


def fifty_two_week_position(values: list[float], sessions: int = 252) -> dict[str, Any]:
    """计算最新收盘价相对最近252个交易日收盘高点的位置。"""
    if len(values) < 2:
        raise ValueError("计算52周位置的历史行情不足")
    window = [float(value) for value in values[-sessions:]]
    latest = window[-1]
    previous_high = max(window[:-1])
    high = max(previous_high, latest)
    is_new_high = latest > previous_high
    drawdown_pct = (high - latest) / high * 100 if high else 0.0
    return {
        "latest": latest,
        "high": high,
        "is_new_high": is_new_high,
        "drawdown_pct": max(0.0, drawdown_pct),
        "sessions": len(window),
    }


def data_age_days(value: str | None, as_of: date | None = None) -> int | None:
    """返回数据日期距决策日的日历天数；日期缺失或无效时返回None。"""
    if not value:
        return None
    try:
        data_date = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    reference = as_of or datetime.now(ZoneInfo("America/New_York")).date()
    return (reference - data_date).days


def buy_signal_fresh(data: dict[str, Any], max_age_days: int = 7, as_of: date | None = None) -> tuple[bool, int | None]:
    age = data_age_days(data.get("date"), as_of)
    return age is not None and age <= max_age_days, age


def stale_buy_note(data: dict[str, Any], max_age_days: int = 7, as_of: date | None = None) -> str:
    fresh, age = buy_signal_fresh(data, max_age_days, as_of)
    if fresh:
        return ""
    if age is None:
        return "；⚠️ 数据日期缺失或无效，不参与买入提示"
    return f"；⚠️ 数据距今{age}天，已超过{max_age_days}天，不参与买入提示"


def naaim_update_reminder(naaim: dict[str, Any] | None, now: datetime | None = None) -> str | None:
    """NAAIM美东周四发布；在对应的北京时间周五提醒检查手动记录。"""
    beijing_now = (now or datetime.now(ZoneInfo("Asia/Shanghai"))).astimezone(ZoneInfo("Asia/Shanghai"))
    if beijing_now.weekday() != 4:
        return None
    age = data_age_days(naaim.get("date") if naaim else None, beijing_now.date())
    if age is not None and age <= 3:
        return None
    current = "当前没有可用记录" if age is None else f"当前记录为 {naaim['date']}（距今{age}天）"
    return (
        "⏰ NAAIM通常在美东周四发布，对应北京时间周五；"
        f"{current}。请今天查看最新值，并在GitHub Actions中运行“手动更新 NAAIM 数据”。"
    )


def indicator(name: str, label: str, score: float | None, value: str, detail: str, weight: int) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "score": None if score is None else round(clamp(score), 1),
        "value": value,
        "detail": detail,
        "weight": weight,
    }


def sentiment_label(score: float) -> str:
    if score < 20:
        return "极度恐惧"
    if score < 40:
        return "恐惧"
    if score < 60:
        return "中性"
    if score < 80:
        return "贪婪"
    return "极度贪婪"


def decision_recommendation(score: float) -> str:
    if score >= 50:
        return "强烈买入"
    if score >= 20:
        return "建议买入"
    if score > -20:
        return "观望"
    if score > -50:
        return "建议分批卖出"
    return "建议卖出"


def build_decision(
    source_data: dict[str, dict[str, Any]],
    histories: dict[str, dict[str, Any]],
    qqq_rsis: dict[int, float],
    as_of: date | None = None,
) -> dict[str, Any]:
    """按用户设定阈值生成五项指标的加权决策和触发理由。"""
    strengths = {name: 0.0 for name in DECISION_WEIGHTS}
    available: set[str] = set()
    triggers: list[dict[str, str]] = []
    suppressed_signals: list[str] = []
    full_position_signal = False

    def trigger(indicator_name: str, direction: str, strength: float, reason: str) -> None:
        signed = strength if direction == "buy" else -strength
        strengths[indicator_name] = max(-2.0, min(2.0, strengths[indicator_name] + signed))
        triggers.append({
            "indicator": indicator_name,
            "direction": direction,
            "reason": reason,
        })

    aaii = source_data.get("aaii")
    if aaii:
        available.add("aaii")
        aaii_fresh, aaii_age = buy_signal_fresh(aaii, as_of=as_of)
        if float(aaii["bullish"]) > 45:
            trigger("aaii", "sell", 1.0, f"AAII看涨 {aaii['bullish']:.1f}% > 45%")
        bearish = float(aaii["bearish"])
        if bearish > 45 and aaii_fresh:
            trigger("aaii", "buy", 2.0, f"AAII看跌 {aaii['bearish']:.1f}% > 45%（强买入）")
        elif bearish >= 42 and aaii_fresh:
            trigger("aaii", "buy", 1.0, f"AAII看跌 {aaii['bearish']:.1f}% 位于42%–45%（接近45%）")
        elif bearish >= 42:
            age_text = "日期无效" if aaii_age is None else f"已{aaii_age}天"
            suppressed_signals.append(f"AAII数据{age_text}，超过7天有效期，已停止参与买入判断")

    ndx_pe = source_data.get("ndx_pe")
    if ndx_pe:
        available.add("ndx_forward_pe")
        forward_pe = float(ndx_pe["forward_pe"])
        ndx_pe_fresh, ndx_pe_age = buy_signal_fresh(ndx_pe, as_of=as_of)
        if forward_pe < 23 and ndx_pe_fresh:
            trigger("ndx_forward_pe", "buy", 2.0, f"纳指100预估市盈率 {forward_pe:.2f}x < 23x（强买入）")
        elif forward_pe < 24 and ndx_pe_fresh:
            trigger("ndx_forward_pe", "buy", 1.0, f"纳指100预估市盈率 {forward_pe:.2f}x < 24x")
        elif forward_pe < 24:
            age_text = "日期无效" if ndx_pe_age is None else f"已{ndx_pe_age}天"
            suppressed_signals.append(f"预估市盈率数据{age_text}，超过7天有效期，已停止参与买入判断")

    naaim = source_data.get("naaim")
    if naaim:
        available.add("naaim")
        exposure = float(naaim["exposure"])
        four_week_average = float(naaim["four_week_average"])
        if exposure < 70:
            trigger("naaim", "buy", 2.0, f"NAAIM {exposure:.2f} < 70（强买入）")
        elif exposure < 75:
            trigger("naaim", "buy", 1.5, f"NAAIM {exposure:.2f} < 75")
        elif exposure < 80:
            trigger("naaim", "buy", 1.0, f"NAAIM {exposure:.2f} < 80")
        if four_week_average > 95:
            trigger("naaim", "sell", 1.5, f"NAAIM 4周均值 {four_week_average:.2f} > 95")

    vix = histories.get("^VIX", {}).get("closes", [])
    if vix:
        available.add("vix")
        latest_vix = float(vix[-1])
        if latest_vix > 35:
            trigger("vix", "buy", 2.0, f"VIX {latest_vix:.2f} > 35（强买入）")
        elif latest_vix > 30:
            trigger("vix", "buy", 1.0, f"VIX {latest_vix:.2f} > 30")
        elif latest_vix < 14:
            trigger("vix", "sell", 1.0, f"VIX {latest_vix:.2f} < 14（分批卖出）")

    if qqq_rsis:
        available.add("qqq_rsi")
        rsi6 = float(qqq_rsis[6])
        if rsi6 <= 20:
            full_position_signal = True
            trigger("qqq_rsi", "buy", 2.0, f"QQQ RSI6 {rsi6:.2f} ≤ 20（全仓买入规则提示）")
        elif rsi6 < 30:
            trigger("qqq_rsi", "buy", 1.0, f"QQQ RSI6 {rsi6:.2f} < 30")

    total_weight = sum(DECISION_WEIGHTS[name] for name in available)
    weighted_score = (
        round(
            sum(DECISION_WEIGHTS[name] * strengths[name] / 2 for name in available)
            / total_weight
            * 100,
            1,
        )
        if total_weight else 0.0
    )
    recommendation = decision_recommendation(weighted_score) if total_weight else "数据不足"
    buy_triggers = sum(item["direction"] == "buy" for item in triggers)
    sell_triggers = sum(item["direction"] == "sell" for item in triggers)
    return {
        "score": weighted_score,
        "recommendation": recommendation,
        "full_position_signal": full_position_signal,
        "buy_triggers": buy_triggers,
        "sell_triggers": sell_triggers,
        "available_indicators": len(available),
        "total_indicators": len(DECISION_WEIGHTS),
        "weights": DECISION_WEIGHTS.copy(),
        "strengths": strengths,
        "triggers": triggers,
        "suppressed_signals": suppressed_signals,
    }


def collect(demo: bool = False) -> dict[str, Any]:
    histories: dict[str, dict[str, Any]] = {}
    source_data: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if demo:
        histories = {
            "^VIX": demo_history("^VIX"),
            "QQQ": demo_history("QQQ"),
            "^NDX": demo_history("^NDX", days=280),
        }
        today = datetime.now(timezone.utc).date().isoformat()
        source_data = {
            "aaii": {"date": today, "bullish": 36.3, "neutral": 26.5, "bearish": 37.2, "spread": -0.9, "score": 49.4, "source": "演示数据"},
            "ndx_pe": {"date": today, "forward_pe": 23.4, "ten_year_median": 22.9, "percentile": 55.0, "score": 45.0, "source": "演示数据"},
            "naaim": {"date": today, "exposure": 82.95, "four_week_average": 78.60, "score": 82.95, "source": "演示数据"},
            "cftc_positioning": {
                "date": today, "long_pct": 58.0, "short_pct": 12.0, "net_pct": 46.0,
                "four_week_average": 44.5, "three_year_percentile": 72.0, "source": "演示数据",
            },
        }
    else:
        fetchers = {
            "aaii": fetch_aaii,
            "ndx_pe": fetch_ndx_forward_pe,
            "naaim": fetch_naaim,
            "cftc_positioning": fetch_cftc_asset_manager_positioning,
        }
        for name, fetcher in fetchers.items():
            try:
                source_data[name] = fetcher()
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
        for symbol in ["^VIX", "QQQ", "^NDX"]:
            try:
                histories[symbol] = yahoo_history(symbol, days=280 if symbol == "^NDX" else 220)
            except Exception as exc:
                errors.append(f"{symbol}: {type(exc).__name__}: {exc}")

    items: list[dict[str, Any]] = []
    aaii = source_data.get("aaii")
    if aaii:
        items.append(indicator(
            "aaii", "AAII 投资者情绪", aaii["score"],
            f"看多 {aaii['bullish']:.1f}% / 中性 {aaii['neutral']:.1f}% / 看空 {aaii['bearish']:.1f}%",
            f"多空差 {aaii['spread']:+.1f} 个百分点；发布日期 {aaii['date']}{stale_buy_note(aaii)}", 20,
        ))
    else:
        items.append(indicator("aaii", "AAII 投资者情绪", None, "不可用", "AAII 数据获取失败", 20))

    ndx_pe = source_data.get("ndx_pe")
    if ndx_pe:
        years = int(os.getenv("NDX_PE_PERCENTILE_YEARS", "10"))
        items.append(indicator(
            "ndx_forward_pe", "纳斯达克100预估市盈率", ndx_pe["score"],
            f"{ndx_pe['forward_pe']:.2f}x / {years}年百分位 {ndx_pe['percentile']:.1f}%",
            f"10年历史中位数 {ndx_pe['ten_year_median']:.2f}x；数据日期 {ndx_pe['date']}{stale_buy_note(ndx_pe)}", 20,
        ))
    else:
        items.append(indicator("ndx_forward_pe", "纳斯达克100预估市盈率", None, "不可用", "Nasdaq估值数据获取失败", 20))

    naaim = source_data.get("naaim")
    if naaim:
        items.append(indicator(
            "naaim", "NAAIM 主动经理暴露指数", naaim["score"], f"{naaim['exposure']:.2f}",
            f"4周均值 {naaim['four_week_average']:.2f}；{naaim.get('source', 'NAAIM')}；数据日期 {naaim['date']}", 20,
        ))
    else:
        items.append(indicator("naaim", "NAAIM 主动经理暴露指数", None, "不可用", "最新数据需NAAIM订阅、授权API或GitHub手动记录", 20))

    cftc = source_data.get("cftc_positioning")
    if cftc:
        items.append(indicator(
            "cftc_positioning", "CFTC机构仓位（参考）", cftc["three_year_percentile"],
            f"净仓位 {cftc['net_pct']:+.1f}% / 3年百分位 {cftc['three_year_percentile']:.1f}%",
            (
                f"多仓 {cftc['long_pct']:.1f}% / 空仓 {cftc['short_pct']:.1f}%；"
                f"净仓位4周均值 {cftc['four_week_average']:+.1f}%；"
                f"数据日期 {cftc['date']}；仅供参考，权重0%，不参与综合评分"
            ),
            0,
        ))
    else:
        items.append(indicator(
            "cftc_positioning", "CFTC机构仓位（参考）", None, "不可用",
            "CFTC周度数据获取失败；仅供参考，不参与综合评分", 0,
        ))

    vix = histories.get("^VIX", {}).get("closes", [])
    if vix:
        latest = vix[-1]
        if latest <= 12:
            score = 100
        elif latest <= 20:
            score = 100 - (latest - 12) * 5
        elif latest <= 30:
            score = 60 - (latest - 20) * 3
        elif latest <= 45:
            score = 30 - (latest - 30) * 2
        else:
            score = 0
        items.append(indicator("vix", "VIX 恐慌指数", score, f"{latest:.2f}", f"行情日期 {histories['^VIX']['dates'][-1]}", 20))
    else:
        items.append(indicator("vix", "VIX 恐慌指数", None, "不可用", "VIX 行情获取失败", 20))

    qqq = histories.get("QQQ", {}).get("closes", [])
    qqq_rsis: dict[int, float] = {}
    if qqq:
        qqq_rsis = {period: wilder_rsi(qqq, period) for period in (1, 6, 14)}
        items.append(indicator(
            "qqq_rsi", "QQQ 日线 RSI", qqq_rsis[14],
            f"RSI1 {qqq_rsis[1]:.2f} / RSI6 {qqq_rsis[6]:.2f} / RSI14 {qqq_rsis[14]:.2f}",
            f"行情日期 {histories['QQQ']['dates'][-1]}；以RSI6触发：<30买入，≤20全仓规则提示", 20,
        ))
    else:
        items.append(indicator("qqq_rsi", "QQQ 日线 RSI", None, "不可用", "QQQ 行情获取失败", 20))

    ndx_52_week = None
    ndx_history = histories.get("^NDX", {})
    if ndx_history.get("closes"):
        ndx_52_week = {
            **fifty_two_week_position(ndx_history["closes"]),
            "date": ndx_history["dates"][-1],
            "source": "Yahoo Finance ^NDX",
        }

    valid = [item for item in items if item["score"] is not None]
    total_weight = sum(item["weight"] for item in valid)
    score = round(sum(item["score"] * item["weight"] for item in valid) / total_weight, 1) if total_weight else None
    market_dates = [history["dates"][-1] for history in histories.values() if history.get("dates")]
    market_dates.extend(data["date"] for data in source_data.values() if data.get("date"))
    decision = build_decision(source_data, histories, qqq_rsis)
    reminder = naaim_update_reminder(naaim)
    return {
        "schema_version": 5,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "market_date": max(market_dates) if market_dates else None,
        "score": score,
        "label": sentiment_label(score) if score is not None else "数据不足",
        "mode": "demo" if demo else "live",
        "available_indicators": len(valid),
        "total_indicators": len(items),
        "indicators": items,
        "ndx_52_week": ndx_52_week,
        "decision": decision,
        "reminders": [reminder] if reminder else [],
        "errors": errors,
        "disclaimer": "以上为用户自定义阈值生成的规则信号，仅供信息参考，不构成投资建议。全仓提示不代表适合个人风险承受能力；各数据源更新频率不同，请结合仓位、估值滞后和最新市场情况独立判断。",
    }


def data_dir() -> Path:
    configured = Path(os.getenv("DATA_DIR", "data"))
    return configured if configured.is_absolute() else ROOT / configured


def save_report(report: dict[str, Any]) -> Path:
    folder = data_dir()
    history = folder / "history"
    history.mkdir(parents=True, exist_ok=True)
    latest = folder / "latest.json"
    body = json.dumps(report, ensure_ascii=False, indent=2)
    latest.write_text(body, encoding="utf-8")
    stamp = report["generated_at"].replace(":", "-")
    (history / f"{stamp}.json").write_text(body, encoding="utf-8")
    return latest


def _template_context(report: dict[str, Any]) -> dict[str, str]:
    score = report.get("score")
    score_text = "--" if score is None else f"{score:.1f}/100"
    indicator_rows = []
    indicator_details = []
    for item in report["indicators"]:
        value = str(item["value"]).replace("|", "/")
        detail = str(item["detail"]).replace("|", "/")
        indicator_rows.append(f"| {item['label']} | {value} | {detail} |")
        indicator_details.extend([
            f"### {item['label']}",
            f"- 当前值：{item['value']}",
            f"- 说明：{item['detail']}",
            "",
        ])
    ndx_position = report.get("ndx_52_week")
    if ndx_position:
        latest = ndx_position["latest"]
        high = ndx_position["high"]
        if ndx_position["is_new_high"]:
            value = f"创52周收盘新高 {latest:,.2f}点"
        else:
            value = f"距52周收盘高点回撤 {ndx_position['drawdown_pct']:.2f}%"
        detail = f"当前 {latest:,.2f}点；52周高点 {high:,.2f}点；行情日期 {ndx_position['date']}"
    else:
        value = "不可用"
        detail = "纳斯达克100指数行情获取失败"
    indicator_rows.append(f"| 纳斯达克100 52周位置 | {value} | {detail} |")
    indicator_details.extend([
        "### 纳斯达克100 52周位置",
        f"- 当前值：{value}",
        f"- 说明：{detail}",
        "",
    ])
    errors = ""
    if report.get("errors"):
        errors = "\n".join(f"- {error}" for error in report["errors"])
    decision = report.get("decision", {})
    trigger_lines = []
    for item in decision.get("triggers", []):
        icon = "🟢 买入" if item["direction"] == "buy" else "🔴 卖出"
        trigger_lines.append(f"- **{icon}**｜{item['reason']}")
    for reason in decision.get("suppressed_signals", []):
        trigger_lines.append(f"- **⚪ 数据过期**｜{reason}")
    if not trigger_lines:
        trigger_lines.append("- 本次没有指标达到预设的买入或卖出阈值。")
    decision_score = decision.get("score")
    decision_score_text = "--" if decision_score is None else f"{decision_score:+.1f}"
    return {
        "title": os.getenv("REPORT_TITLE", "🇺🇸 美股情绪日报"),
        "date": report.get("market_date") or "日期未知",
        "generated_at": report.get("generated_at") or "",
        "score": score_text,
        "score_number": "--" if score is None else f"{score:.1f}",
        "label": report["label"],
        "session": f"美东时间 {format_market_date(report.get('market_date'))}收盘后",
        "coverage": f"{report['available_indicators']}/{report['total_indicators']}",
        "indicator_table": "\n".join([
            "| 指标 | 最新数据 | 参考信息 |",
            "|:--|:--|:--|",
            *indicator_rows,
        ]),
        "indicator_lines": "\n".join(indicator_rows),
        "indicator_details": "\n".join(indicator_details).rstrip(),
        "decision_recommendation": decision.get("recommendation", "数据不足"),
        "decision_score": decision_score_text,
        "decision_coverage": f"{decision.get('available_indicators', 0)}/{decision.get('total_indicators', 5)}",
        "decision_weights": "AAII 20%｜预估市盈率 10%｜NAAIM 20%｜VIX 25%｜QQQ RSI 25%",
        "trigger_reasons": "\n".join(trigger_lines),
        "reminders": "\n".join(f"> {item}" for item in report.get("reminders", [])),
        "errors": errors,
        "error_count": str(len(report.get("errors", []))),
        "disclaimer": report["disclaimer"],
    }


def format_market_date(value: str | None) -> str:
    if not value:
        eastern_date = datetime.now(ZoneInfo("America/New_York")).date()
    else:
        eastern_date = datetime.strptime(value, "%Y-%m-%d").date()
    return f"{eastern_date.year}年{eastern_date.month}月{eastern_date.day}日"


def render_report(report: dict[str, Any], report_type: str | None = None) -> str:
    """按 brief/standard/full/custom 生成可推送内容。"""
    report_type = (report_type or os.getenv("REPORT_TYPE", "standard")).strip().lower()
    context = _template_context(report)
    if report_type == "brief":
        lines = [
            f"## {context['title']}",
            f"> {context['session']}",
            f"> 市场情绪温度：**{context['label']}**（{context['score']}，越高越偏积极）",
            f"> 买入决策：**{context['decision_recommendation']}**（买入决策分 {context['decision_score']}）",
            f"> 数据完整度：{context['coverage']}",
        ]
        if context["reminders"]:
            lines += ["", context["reminders"]]
        return "\n".join(lines)
    if report_type == "custom":
        configured = Path(os.getenv("CUSTOM_TEMPLATE_PATH", "templates/serverchan.md"))
        template_path = configured if configured.is_absolute() else ROOT / configured
        if not template_path.is_file():
            raise FileNotFoundError(f"自定义模板不存在：{template_path}")
        try:
            return template_path.read_text(encoding="utf-8").format_map(context)
        except KeyError as exc:
            raise ValueError(f"自定义模板包含未知占位符：{exc.args[0]}") from exc
    if report_type == "full":
        lines = [
            f"## {context['title']}",
            f"> {context['session']}",
            f"> 市场情绪温度：**{context['label']}**（{context['score']}，越高越偏积极）",
            f"> 买入决策：**{context['decision_recommendation']}**（买入决策分 {context['decision_score']}）",
            f"> 决策权重：{context['decision_weights']}",
            f"> 数据完整度：{context['coverage']}",
            context["reminders"],
            "",
            context["indicator_table"],
            "",
            "### 触发理由",
            context["trigger_reasons"],
            "",
            "### 指标说明",
            context["indicator_details"],
        ]
        if context["errors"]:
            lines += ["", "### 数据源异常", context["errors"]]
        lines += ["", context["disclaimer"]]
        return "\n".join(lines)
    if report_type != "standard":
        raise ValueError("REPORT_TYPE 仅支持 brief、standard、full、custom")
    lines = [
        f"## {context['title']}",
        f"> {context['session']}",
        f"> 市场情绪温度：**{context['label']}**（{context['score']}，越高越偏积极）",
        f"> 买入决策：**{context['decision_recommendation']}**（买入决策分 {context['decision_score']}）",
        f"> 决策权重：{context['decision_weights']}",
        f"> 数据完整度：{context['coverage']}",
        context["reminders"],
        "",
        context["indicator_table"],
        "",
        "### 触发理由",
        context["trigger_reasons"],
    ]
    lines += ["", context["disclaimer"]]
    if report.get("errors"):
        lines.append(f"> ⚠️ {len(report['errors'])} 个数据源本次未成功，请查看表格中的“不可用”项目。")
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    """保留旧调用接口，实际交给可配置报告渲染器。"""
    return render_report(report)


def split_utf8(text: str, max_bytes: int = 3500) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        encoded = line.encode("utf-8")
        if size + len(encoded) > max_bytes and current:
            chunks.append("".join(current).rstrip())
            current, size = [], 0
        if len(encoded) > max_bytes:
            for char in line:
                char_size = len(char.encode("utf-8"))
                if size + char_size > max_bytes and current:
                    chunks.append("".join(current).rstrip())
                    current, size = [], 0
                current.append(char)
                size += char_size
        else:
            current.append(line)
            size += len(encoded)
    if current:
        chunks.append("".join(current).rstrip())
    return chunks


def serverchan3_endpoint(sendkey: str, uid: str | None = None) -> str:
    sendkey = sendkey.strip()
    match = re.fullmatch(r"sctp(\d+)t[A-Za-z0-9_-]+", sendkey)
    if not match:
        raise ValueError("SERVERCHAN3_SENDKEY 格式不正确，应以 sctp{uid}t 开头")
    resolved_uid = (uid or match.group(1)).strip()
    if not resolved_uid.isdigit() or resolved_uid != match.group(1):
        raise ValueError("SERVERCHAN3_UID 与 SendKey 中的 UID 不一致")
    return f"https://{resolved_uid}.push.ft07.com/send/{quote(sendkey, safe='')}.send"


def send_serverchan(content: str, sendkey: str | None = None) -> None:
    sendkey = sendkey or os.getenv("SERVERCHAN3_SENDKEY", "")
    if not sendkey:
        raise RuntimeError("未设置 SERVERCHAN3_SENDKEY")
    endpoint = serverchan3_endpoint(sendkey, os.getenv("SERVERCHAN3_UID") or None)
    timeout = float(os.getenv("REQUEST_TIMEOUT", "15"))
    configured_max = int(os.getenv("SERVERCHAN3_MAX_BYTES", "20000"))
    max_bytes = max(1000, min(configured_max, 50000))
    title = os.getenv("SERVERCHAN3_TITLE") or os.getenv("REPORT_TITLE", "美股情绪日报")
    tags = os.getenv("SERVERCHAN3_TAGS", "美股|情绪监控").strip()
    chunks = split_utf8(content, max_bytes=max_bytes)
    for index, chunk in enumerate(chunks, start=1):
        chunk_title = title if len(chunks) == 1 else f"{title}（{index}/{len(chunks)}）"
        payload: dict[str, str] = {"title": chunk_title, "desp": chunk}
        if tags:
            payload["tags"] = tags
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            raise RuntimeError("Server酱³ 请求失败，请检查网络和 SendKey") from None
        if result.get("code", 0) != 0 or result.get("errno", 0) != 0 or result.get("success") is False:
            message = result.get("message") or result.get("errmsg") or "未知错误"
            raise RuntimeError(f"Server酱³ 返回错误：{message}")


def run_once(demo: bool = False, notify: bool = False) -> dict[str, Any]:
    report = collect(demo=demo)
    save_report(report)
    if notify:
        send_serverchan(render_report(report))
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    parser = argparse.ArgumentParser(description="美股情绪监控")
    parser.add_argument("--demo", action="store_true", help="使用离线演示数据")
    parser.add_argument("--notify", action="store_true", help="通过 Server酱³ 推送到手机")
    parser.add_argument("--update-naaim", type=float, metavar="VALUE", help="写入一条手动NAAIM记录")
    parser.add_argument("--naaim-date", metavar="YYYY-MM-DD", help="手动NAAIM记录对应的调查日期")
    args = parser.parse_args()
    if args.update_naaim is not None:
        if not args.naaim_date:
            parser.error("--update-naaim 必须同时提供 --naaim-date")
        path = update_manual_naaim(args.update_naaim, args.naaim_date)
        print(f"已更新NAAIM手动记录：{path}")
        if not args.notify:
            return 0
    report = run_once(demo=args.demo, notify=args.notify)
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
