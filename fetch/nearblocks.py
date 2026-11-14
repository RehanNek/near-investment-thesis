"""NearBlocks (third-party, free, no key): daily L1 statistics since 2020.

Endpoint: https://api.nearblocks.io/v1/charts. One row per day with active accounts,
transactions, new accounts and contracts, fees, supply, price and market cap.
Used as a cross-check for BigQuery L1 metrics and supply.

Usage: python -m fetch.nearblocks
"""
from __future__ import annotations

from fetch.common import RAW, http_get, record_fetch, write_json

URL = "https://api.nearblocks.io/v1/charts"


def main() -> None:
    rows = http_get(URL, timeout=120).json()["charts"]
    write_json(RAW / "nearblocks" / "charts.json", rows)
    print(f"  {len(rows)} daily rows, {rows[0]['date'][:10]}..{rows[-1]['date'][:10]}")
    record_fetch("nearblocks", url=URL, rows=len(rows), first=rows[0]["date"][:10], last=rows[-1]["date"][:10])


if __name__ == "__main__":
    main()
