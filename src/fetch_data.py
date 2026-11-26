"""Step 1 — download the open D&D corpus from the Open5e API (v2) into data/raw/.

Open5e aggregates every openly licensed 5e book (CC BY 4.0 or OGL 1.0a):
the official System Reference Documents 5.1 and 5.2 by Wizards of the Coast, plus
third-party supplements (Kobold Press Tome of Beasts 1-3, Deep Magic, Vault of Magic,
Tal'Dorei Campaign Setting, Black Flag SRD, ...).

The API is called ONCE, offline. The query-time pipeline never touches the network
for retrieval. Run:  python -m src.fetch_data
"""
import json
import time
import urllib.request

from src.config import DATA_RAW

BASE = "https://api.open5e.com/v2"
ENDPOINTS = [
    "documents", "creatures", "spells", "magicitems", "items", "weapons", "armor",
    "conditions", "rules", "rulesets", "classes", "species", "backgrounds", "feats",
]
PAGE_SIZE = 1000


def get_json(url: str, attempts: int = 5) -> dict:
    """GET a JSON page with exponential backoff (2s, 4s, 8s...)."""
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dm-copilot-student-project"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == attempts:
                raise
            wait = 2 ** attempt
            print(f"  {type(e).__name__} on {url} — retrying in {wait}s")
            time.sleep(wait)


def fetch_endpoint(name: str) -> list:
    url = f"{BASE}/{name}/?limit={PAGE_SIZE}"
    rows = []
    while url:
        page = get_json(url)
        rows.extend(page["results"])
        url = page.get("next")
        time.sleep(0.5)  # be gentle with a free community API
    return rows


def main():
    for name in ENDPOINTS:
        out = DATA_RAW / f"{name}.json"
        if out.exists():
            print(f"{name:12s} already downloaded ({out.stat().st_size // 1024} KB) — skipped")
            continue
        rows = fetch_endpoint(name)
        out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"{name:12s} {len(rows):5d} entries -> {out.name}")


if __name__ == "__main__":
    main()
