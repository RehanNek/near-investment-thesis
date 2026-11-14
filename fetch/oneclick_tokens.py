"""NEAR Intents 1Click API (first-party): the list of supported tokens.

Endpoint: https://1click.chaindefuser.com/v0/tokens (public, no key). Maps each asset id used in
Explorer API swaps (e.g. nep141:btc.omft.near) to its blockchain and symbol, so swaps can be
grouped by chain and stablecoins identified. Also carries current USD prices.

Usage: python -m fetch.oneclick_tokens
"""
from __future__ import annotations

from fetch.common import RAW, http_get, record_fetch, write_json

URL = "https://1click.chaindefuser.com/v0/tokens"


def main() -> None:
    tokens = http_get(URL).json()
    write_json(RAW / "oneclick" / "tokens.json", tokens)
    chains = sorted({t["blockchain"] for t in tokens})
    print(f"  {len(tokens)} tokens on {len(chains)} chains")
    record_fetch("oneclick_tokens", url=URL, tokens=len(tokens), chains=len(chains))


if __name__ == "__main__":
    main()
