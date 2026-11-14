"""How much NEAR is staked, month by month? (first-party chain data)

fetch/rpc.py saves the stake of today's validators: one point in time, because a regular RPC node only
answers for the current epoch. An archival node keeps every past epoch, so this reads the same figure at
the end of each month since START:

  1. The header of the month's last block (heights from data/raw/bigquery/blocks_daily.csv) gives that
     block's epoch_id and the total supply. Headers come from FastNEAR's NEAR Data API, which serves past
     blocks without a key:  GET {NEARDATA}/v0/block/<height>/headers
  2. `validators` with {"epoch_id": ...} on the archival RPC node gives that epoch's validators and each
     one's stake. (Asking by block height fails with UNKNOWN_EPOCH for a past block.)

Staked NEAR = the sum of the validators' stake in that epoch.
Staked share = staked NEAR ÷ total supply at that block.
This is the same definition as the snapshot in fetch/rpc.py.

The public archival node allows only a few calls at a time and then answers HTTP 429 with a Retry-After
header (its operator also marks it as deprecated). This script waits as long as it is told to, so a full
run takes a while. Each month is cached on disk (data/raw/rpc/_staking_history_cache.json) and the CSV
is rewritten after every new month, so a rerun resumes where it stopped. The latest month and the same
month a year earlier are fetched first.

References:
  https://docs.near.org/api-reference/post-validators   (the `validators` method)
  https://docs.near.org/api/rpc/providers               (the archival endpoint)
  https://docs.fastnear.com/neardata                    (block headers by height)
Output: data/raw/rpc/staking_history.csv
Usage:  python -m fetch.staking_history
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd
import requests

from fetch.common import RAW, _session, http_get, read_json, record_fetch, write_json
from fetch.rpc import ARCHIVAL, YOCTO

START = "2025-01"
NEARDATA = "https://mainnet.neardata.xyz"
CACHE = RAW / "rpc" / "_staking_history_cache.json"
OUT = RAW / "rpc" / "staking_history.csv"


def header_at(height: int) -> dict:
    """Header of a past block, from the NEAR Data API."""
    return http_get(f"{NEARDATA}/v0/block/{int(height)}/headers").json()["header"]


def validators_in(epoch_id: str) -> dict:
    """One past epoch's validators, from the archival node. Waits out its rate limit as instructed."""
    payload = {"jsonrpc": "2.0", "id": "thesis", "method": "validators", "params": {"epoch_id": epoch_id}}
    for _ in range(60):
        try:
            r = _session.post(ARCHIVAL, json=payload, timeout=60)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(5)  # a connection left idle during a long wait gets closed: ask again on a new one
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 60)) + 2
            print(f"    the archival node asks us to wait {wait}s", flush=True)
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            time.sleep(20)
            continue
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"validators {epoch_id}: {body['error']}")
        return body["result"]
    raise RuntimeError(f"validators {epoch_id}: the archival node kept refusing")


def stake_at(height: int) -> dict:
    """Validators' total stake in the epoch that contains a past block, and the supply at that block (cached)."""
    cache = read_json(CACHE, {})
    if str(height) in cache:
        return cache[str(height)]
    header = header_at(height)
    v = validators_in(header["epoch_id"])
    if not v["epoch_start_height"] <= height:
        raise RuntimeError(f"block {height} is not in the epoch returned (starts at {v['epoch_start_height']})")
    stake = sum(int(x["stake"]) for x in v["current_validators"]) / YOCTO
    supply = int(header["total_supply"]) / YOCTO
    out = {
        "height": int(height),
        "block_time_utc": datetime.fromtimestamp(int(header["timestamp"]) / 1e9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "epoch_id": header["epoch_id"],
        "epoch_height": v["epoch_height"],
        "epoch_start_height": v["epoch_start_height"],
        "validators": len(v["current_validators"]),
        "total_stake_near": stake,
        "total_supply_near": supply,
        "staked_share_of_supply_pct": 100 * stake / supply,
    }
    cache = read_json(CACHE, {})
    cache[str(height)] = out
    write_json(CACHE, cache)
    return out


def month_ends() -> pd.DataFrame:
    """The last block of each complete month since START."""
    days = pd.read_csv(RAW / "bigquery" / "blocks_daily.csv")
    days["month"] = days.block_date.str[:7]
    last = days.groupby("month", as_index=False).last()
    complete = pd.to_datetime(last.block_date) == pd.PeriodIndex(last.month, freq="M").end_time.normalize()
    return last[complete & (last.month >= START)][["month", "block_date", "last_height"]].reset_index(drop=True)


def save(months: pd.DataFrame) -> pd.DataFrame:
    """Write every month fetched so far, oldest first, and record the fetch."""
    cache = read_json(CACHE, {})
    rows = [{"month": m.month, "block_date": m.block_date, **cache[str(int(m.last_height))]}
            for m in months.itertuples() if str(int(m.last_height)) in cache]
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    record_fetch("staking_history", url=ARCHIVAL, headers_url=NEARDATA,
                 method="block header at the last block of each month (NEAR Data API), then validators by epoch_id (archival RPC)",
                 points=len(df), months_wanted=len(months), start=df.block_date.iloc[0], end=df.block_date.iloc[-1],
                 file=OUT.name)
    return df


def main() -> None:
    months = month_ends()
    latest = months.month.iloc[-1]
    first = [latest, str(pd.Period(latest, "M") - 12)]
    order = [m for m in first if m in set(months.month)] + [m for m in months.month[::-1] if m not in first]
    by_month = months.set_index("month")
    for month in order:
        s = stake_at(int(by_month.last_height[month]))
        print(f"  {by_month.block_date[month]}: {s['total_stake_near']:,.0f} NEAR staked by {s['validators']} validators, "
              f"{s['staked_share_of_supply_pct']:.2f}% of supply", flush=True)
        df = save(months)
    print(f"Saved {len(df)} of {len(months)} month ends to {OUT.name}")


if __name__ == "__main__":
    main()
