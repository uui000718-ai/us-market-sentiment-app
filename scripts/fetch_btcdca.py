from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "site" / "data" / "nasdaq-dca.json"
TOP_URL = "https://www.btcdca.me/nasdaq/api/score"
DIMENSIONS_URL = "https://www.btcdca.me/nasdaq/api/score-12d"
EXPECTED_DIMENSIONS = {
    "pe", "pb", "macd", "rsi", "bollinger", "ma50", "ma200",
    "vix", "yield10y", "dxy", "fearGreed", "aaii",
}


def fetch_json(url: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "MarketPulseSentimentApp/1.0",
            })
            with urlopen(request, timeout=25) as response:
                return json.load(response)
        except Exception as error:  # network retry
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"读取 {url} 失败：{last_error}")


def main() -> int:
    top = fetch_json(TOP_URL)
    twelve = fetch_json(DIMENSIONS_URL)
    if not top.get("success") or not isinstance(top.get("data"), dict):
        raise RuntimeError("顶部评分接口格式异常")
    dimensions = twelve.get("dimensions")
    if not twelve.get("success") or not isinstance(dimensions, dict):
        raise RuntimeError("12维度接口格式异常")
    missing = EXPECTED_DIMENSIONS.difference(dimensions)
    if missing:
        raise RuntimeError(f"12维度接口缺少字段：{', '.join(sorted(missing))}")

    payload = {
        "schema_version": 1,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "homepage": "https://www.btcdca.me/nasdaq/",
            "top_score": TOP_URL,
            "dimensions": DIMENSIONS_URL,
        },
        "top": top["data"],
        "twelve": twelve,
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(TARGET)
    print(f"已保存第三方纳指定投评分：{TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
