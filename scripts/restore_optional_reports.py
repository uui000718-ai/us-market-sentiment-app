"""Seed optional reports from the last public deployment before independent refreshes."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://uui000718-ai.github.io/us-market-sentiment-app/data/"
FILES = ("nasdaq-dca.json", "etf-premiums.json", "market-context.json")


def restore(name):
    try:
        with urlopen(Request(BASE + name, headers={"User-Agent": "MarketPulse/1.0"}), timeout=10) as response:
            raw = response.read(2_000_000)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not payload.get("fetched_at"):
            raise ValueError("Not a timestamped report")
        if name == "etf-premiums.json" and (payload.get("schema_version") != 2 or payload.get("basis") != "iopv"):
            raise ValueError("Legacy mixed NAV/IOPV premiums must not be restored")
        target = ROOT / "site" / "data" / name
        if target.exists():
            current = json.loads(target.read_text(encoding="utf-8"))
            if str(current.get("fetched_at", "")) >= str(payload["fetched_at"]):
                return
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
        print(f"Restored published optional report: {name}")
    except Exception:
        print(f"Optional report restore skipped: {name}")


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(restore, FILES))
