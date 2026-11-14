"""Peer tokens for the valuation check (third-party, free, no key): DefiLlama fees and CoinGecko market caps.

Two peer sets, plus NEAR itself so every row comes from the same sources:
  - l1:   layer-1 chains with their own token
  - swap: swap and bridge businesses with their own token (the three native cross-chain swap peers
          from claim C4, plus large DEXes, aggregators and bridges)

For each name we save, under data/raw/peers/:
  - defillama/<slug>.json: daily fees, protocol revenue and token-holder revenue (the last KEEP_DAYS
    days of DefiLlama's totalDataChart; the per-chain breakdown is dropped to keep the files small)
  - coingecko/<gecko_id>.json: daily price, market cap and volume for the last 365 days
  - coingecko_markets.json: today's market cap, fully diluted valuation and supply for every token

The CoinGecko id for each name is read from DefiLlama's own `gecko_id` field, not typed in here.

Usage: python -m fetch.peers            (skips files that are already on disk)
       python -m fetch.peers --refresh  (fetches everything again)
"""
from __future__ import annotations

import sys
import time

import requests

from fetch.common import RAW, http_get, read_json, record_fetch, write_json

LLAMA = "https://api.llama.fi/summary/fees/"
GECKO = "https://api.coingecko.com/api/v3"
KEEP_DAYS = 800
DATA_TYPES = ["dailyFees", "dailyRevenue", "dailyHoldersRevenue"]

# group -> [(display name, [DefiLlama slugs to add up])]
PEERS = {
    "near": [("NEAR", ["near", "near-intents"])],
    "l1": [
        ("Ethereum", ["ethereum"]),
        ("Solana", ["solana"]),
        ("BNB Chain", ["bsc"]),
        ("Tron", ["tron"]),
        ("Avalanche", ["avalanche"]),
        ("Sui", ["sui"]),
        ("Aptos", ["aptos"]),
        ("ICP", ["icp"]),
    ],
    "swap": [
        ("THORChain", ["thorchain-dex", "thorchain"]),
        ("Chainflip", ["chainflip"]),
        ("Maya Protocol", ["maya-protocol"]),
        ("deBridge", ["debridge"]),
        ("Across", ["across"]),
        ("Uniswap", ["uniswap"]),
        ("Jupiter", ["jupiter"]),
        ("PancakeSwap", ["pancakeswap"]),
        ("Aerodrome", ["aerodrome"]),
        ("Raydium", ["raydium"]),
        ("Curve", ["curve-finance"]),
        ("Orca", ["orca"]),
        ("CoW Swap", ["cowswap"]),
        ("Meteora", ["meteora"]),
        ("Hyperliquid", ["hyperliquid"]),
    ],
}
META_KEYS = ["name", "displayName", "defillamaId", "gecko_id", "category", "linkedProtocols", "methodology", "methodologyURL"]


def fetch_llama(slug: str, refresh: bool) -> dict:
    path = RAW / "peers" / "defillama" / f"{slug}.json"
    if path.exists() and not refresh:
        return read_json(path)
    out = {"slug": slug}
    for dt in DATA_TYPES:
        try:
            d = http_get(LLAMA + slug, params={"dataType": dt}, timeout=120, retries=3).json()
        except Exception as e:  # some names have no holders-revenue series
            print(f"    {slug} {dt}: none ({e.__class__.__name__})")
            out[dt] = []
            continue
        if "meta" not in out:
            out["meta"] = {k: d.get(k) for k in META_KEYS}
        out[dt] = (d.get("totalDataChart") or [])[-KEEP_DAYS:]
    write_json(path, out)
    return out


def fetch_gecko(gid: str, refresh: bool) -> str:
    """Returns "cached", "fetched" or "missing" (CoinGecko has no coin under the id DefiLlama gives)."""
    path = RAW / "peers" / "coingecko" / f"{gid}.json"
    if path.exists() and not refresh:
        return "cached"
    try:
        d = http_get(f"{GECKO}/coins/{gid}/market_chart", params={"vs_currency": "usd", "days": 365, "interval": "daily"},
                     backoff=30.0).json()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return "missing"
        raise
    write_json(path, d)
    return "fetched"


def main() -> None:
    refresh = "--refresh" in sys.argv
    index, gids = [], []
    for group, rows in PEERS.items():
        for name, slugs in rows:
            metas = [fetch_llama(s, refresh) for s in slugs]
            gid = next((m["meta"]["gecko_id"] for m in metas if m.get("meta", {}).get("gecko_id")), None)
            if not gid:
                raise SystemExit(f"{name}: DefiLlama gives no CoinGecko id for {slugs}")
            index.append({"group": group, "name": name, "slugs": slugs, "gecko_id": gid})
            gids.append(gid)
            print(f"  {group:5s} {name:14s} {'+'.join(slugs):28s} -> {gid}")
    for gid in list(gids):
        got = fetch_gecko(gid, refresh)
        if got == "missing":
            dropped = [r["name"] for r in index if r["gecko_id"] == gid]
            print(f"  coingecko {gid}: not found, leaving out {', '.join(dropped)}")
            index = [r for r in index if r["gecko_id"] != gid]
            gids.remove(gid)
        if got != "cached":
            print(f"  coingecko {gid} {got}")
            time.sleep(7)  # the keyless API allows only a few calls a minute
    markets = http_get(f"{GECKO}/coins/markets", params={"vs_currency": "usd", "ids": ",".join(gids), "per_page": 250},
                       backoff=30.0).json()
    write_json(RAW / "peers" / "coingecko_markets.json", markets)
    write_json(RAW / "peers" / "index.json", index)
    record_fetch("peers", defillama=LLAMA, coingecko=GECKO, names=len(index), data_types=DATA_TYPES, keep_days=KEEP_DAYS)


if __name__ == "__main__":
    main()
