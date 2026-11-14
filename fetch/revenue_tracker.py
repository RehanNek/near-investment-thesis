"""NEAR Revenue Tracker (https://revenue.near.org): NEAR's own first-party revenue dashboard.

There is no documented API. The page embeds its data in the Next.js payload, so this
fetcher saves the raw HTML (gzipped, dated) and extracts every embedded data series
into JSON files. Re-running on a later day adds a new dated snapshot.

Output: data/raw/revenue_tracker/<YYYY-MM-DD>/{page.html.gz, <series>.json}

Usage: python -m fetch.revenue_tracker
"""
from __future__ import annotations

import gzip
import json
import re

from fetch.common import RAW, http_get, record_fetch, utc_now, write_json

URL = "https://revenue.near.org/"

# Series names on the page, keyed by the fields their rows carry (two series are both called "data").
SERIES_BY_SIGNATURE = {
    ("cumulative", "date", "value"): "monthly_revenue_chart",
    ("cumulativeUsd", "intentsUsd", "isoDate", "label", "protocolUsd", "volumeUsd"): "daily_revenue_and_volume",
}


def extract_payload(html: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    if not chunks:
        raise SystemExit("No embedded data found; the page layout may have changed.")
    return "".join(json.loads('"' + c + '"') for c in chunks)


def extract_series(blob: str) -> dict[str, list]:
    dec = json.JSONDecoder()
    found: dict[str, list] = {}
    for m in re.finditer(r'"([A-Za-z_][A-Za-z0-9_]*)":\[\{', blob):
        key = m.group(1)
        try:
            val, _ = dec.raw_decode(blob, m.end() - 2)
        except ValueError:
            continue
        if not (isinstance(val, list) and val and isinstance(val[0], dict)):
            continue
        name = SERIES_BY_SIGNATURE.get(tuple(sorted(val[0].keys())), key)
        if name == "items":
            name = "faq"
        elif name == "rows":
            name = "revenue_wallets"
        elif name == "stats":
            name = "headline_stats"
        if name not in found or len(val) > len(found[name]):
            found[name] = val
    return found


def main() -> None:
    html = http_get(URL).text
    series = extract_series(extract_payload(html))
    day = utc_now()[:10]
    out = RAW / "revenue_tracker" / day
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / "page.html.gz", "wt", encoding="utf-8") as f:
        f.write(html)
    for name, rows in series.items():
        write_json(out / f"{name}.json", rows)
        print(f"  {name:28s} {len(rows):5d} rows")
    record_fetch("revenue_tracker", url=URL, snapshot=str(out.relative_to(RAW.parent.parent)),
                 series={k: len(v) for k, v in series.items()})


if __name__ == "__main__":
    main()
