"""When did NEAR's token-economics parameters change? (first-party, archival RPC)

Reads EXPERIMENTAL_protocol_config at past blocks and finds the day each of these changed since
2025-01-01 (protocol_version is recorded alongside, but its many upgrades aren't dated):
  - max_inflation_rate                                 (issuance cap; 1/20 = 5%, 1/40 = 2.5%)
  - runtime_config.transaction_costs.burnt_gas_reward  (share of gas paid to the called contract;
                                                        3/10 = 30% rebate, 0 = all gas burned)

Method: read the first block of each quarter (heights from data/raw/bigquery/blocks_daily.csv),
then bisect by day wherever a value differs between two reads. The public archival node is
severely rate-limited, so calls are spaced out, retried with long back-off and cached on disk
(data/raw/rpc/_protocol_config_cache.json), so a rerun resumes where it stopped.

Output: data/raw/rpc/protocol_changes.json
Usage:  python -m fetch.protocol_history
"""
from __future__ import annotations

import json
import time

import pandas as pd

from fetch.common import RAW, record_fetch, write_json
from fetch.rpc import ARCHIVAL, call

START = "2025-01-01"
TRACKED = ("max_inflation_rate", "burnt_gas_reward")
CACHE = RAW / "rpc" / "_protocol_config_cache.json"


def config_at(height: int) -> dict:
    """Protocol config at a past block (cached)."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if str(height) in cache:
        return cache[str(height)]
    for attempt in range(10):
        try:
            r = call("EXPERIMENTAL_protocol_config", {"block_id": int(height)}, ARCHIVAL)
            break
        except Exception:
            if attempt == 9:
                raise
            time.sleep(30 * (attempt + 1))
    time.sleep(3)
    out = {
        "protocol_version": r["protocol_version"],
        "max_inflation_rate": r["max_inflation_rate"],
        "burnt_gas_reward": r["runtime_config"]["transaction_costs"]["burnt_gas_reward"],
    }
    cache[str(height)] = out
    write_json(CACHE, cache)
    return out


def main() -> None:
    days = pd.read_csv(RAW / "bigquery" / "blocks_daily.csv")
    days = days[days.block_date >= START].reset_index(drop=True)
    days["height"] = days.first_height + 1  # first block of each day, +1 to sit safely inside it
    seen: dict[int, dict] = {}

    def econ(i: int) -> dict:
        if i not in seen:
            seen[i] = config_at(days.height[i])
            print(f"  {days.block_date[i]}: {seen[i]}", flush=True)
        return {k: seen[i][k] for k in TRACKED}

    changes = []

    def find(lo: int, hi: int) -> None:
        """Recursive bisection by day. Assumes a parameter doesn't change and change back between two
        reads; the quarterly checkpoints keep those gaps short."""
        if econ(lo) == econ(hi):
            return
        if hi - lo == 1:
            before, after = econ(lo), econ(hi)
            for k in TRACKED:
                if before[k] != after[k]:
                    changes.append({"parameter": k, "from": before[k], "to": after[k],
                                    "last_day_before": days.block_date[lo], "first_day_after": days.block_date[hi],
                                    "height_checked_after": int(days.height[hi])})
            return
        mid = (lo + hi) // 2
        find(lo, mid)
        find(mid, hi)

    checkpoints = days[days.block_date.str[5:].isin(["01-01", "04-01", "07-01", "10-01"])].index.tolist()
    checkpoints = sorted(set([0] + checkpoints + [len(days) - 1]))
    for a, b in zip(checkpoints, checkpoints[1:]):
        find(a, b)
    changes.sort(key=lambda c: c["first_day_after"])

    out = {"source": ARCHIVAL, "method": "EXPERIMENTAL_protocol_config at the first block of each day, bisected",
           "start": START, "end": days.block_date.iloc[-1], "latest": seen[len(days) - 1], "changes": changes}
    write_json(RAW / "rpc" / "protocol_changes.json", out)
    record_fetch("protocol_history", url=ARCHIVAL, changes=len(changes), end=out["end"])
    for c in changes:
        print(f"{c['first_day_after']}: {c['parameter']} {c['from']} -> {c['to']}", flush=True)


if __name__ == "__main__":
    main()
