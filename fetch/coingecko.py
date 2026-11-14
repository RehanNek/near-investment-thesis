"""CoinGecko (third-party): NEAR price, market cap and trading volume, daily.

The keyless public API allows up to 365 days of history. Used as a cross-check for the
first-party price implied by revenue.near.org (revenue_usd / revenue_near).

Usage: python -m fetch.coingecko
"""
from __future__ import annotations

from fetch.common import RAW, http_get, record_fetch, write_json

URL = "https://api.coingecko.com/api/v3/coins/near/market_chart"


def main() -> None:
    data = http_get(URL, params={"vs_currency": "usd", "days": 365, "interval": "daily"}, backoff=30.0).json()
    write_json(RAW / "coingecko" / "near_market_chart_365d.json", data)
    print(f"  prices {len(data['prices'])}, market caps {len(data['market_caps'])}, volumes {len(data['total_volumes'])}")
    record_fetch("coingecko", url=URL, days=365, points=len(data["prices"]))


if __name__ == "__main__":
    main()
