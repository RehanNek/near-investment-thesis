"""DefiLlama (third-party, free, no key): cross-checks and the cross-chain market total.

Saves full JSON responses to data/raw/defillama/. Used for:
  - NEAR Intents fees, revenue and volume (cross-check for the revenue tracker and Explorer API)
  - NEAR chain fees (cross-check for L1 fees from BigQuery)
  - Total bridge-aggregator and DEX volume (denominator for Intents' market share, claim C4)

Usage: python -m fetch.defillama
"""
from __future__ import annotations

from datetime import datetime, timezone

from fetch.common import RAW, http_get, record_fetch, write_json

BASE = "https://api.llama.fi"
ENDPOINTS = {
    "near_intents_fees": "/summary/fees/near-intents?dataType=dailyFees",
    "near_intents_revenue": "/summary/fees/near-intents?dataType=dailyRevenue",
    "near_intents_volume": "/summary/dexs/near-intents",
    "near_chain_fees": "/summary/fees/near?dataType=dailyFees",
    "bridge_aggregators_overview": "/overview/bridge-aggregators",
    "dexs_overview": "/overview/dexs",
}


def span(chart: list) -> str:
    if not chart:
        return "-"
    f = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    return f"{f(chart[0][0])}..{f(chart[-1][0])}"


def main() -> None:
    out = RAW / "defillama"
    summary = {}
    for name, path in ENDPOINTS.items():
        data = http_get(BASE + path, timeout=120).json()
        write_json(out / f"{name}.json", data)
        chart = data.get("totalDataChart") or []
        summary[name] = {"points": len(chart), "span": span(chart)}
        print(f"  {name:28s} {len(chart):5d} daily points  {span(chart)}")
    record_fetch("defillama", base=BASE, endpoints=ENDPOINTS, summary=summary)


if __name__ == "__main__":
    main()
