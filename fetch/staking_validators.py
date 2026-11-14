"""Which validators explain the lowest month end in the staking history? (first-party chain data)

fetch/staking_history.py saves the total NEAR staked at each month end. One month end stands well below
the months on either side of it, and a total alone cannot say why. This saves every validator's stake at
that month end and at the month ends before and after it, so the build can show where the difference sits.

It is the same call as fetch/staking_history.py: `validators` with {"epoch_id": ...} on the archival RPC
node, using the epoch ids already saved in data/raw/rpc/staking_history.csv. Each validator's `stake` is
what counts towards that epoch's total. `prev_epoch_kickout` lists the validators the node reports as
kicked out, with the reason; they are saved with a stake of zero when they are not in that epoch's set.

Each epoch is cached on disk (data/raw/rpc/_staking_validators_cache.json), so a rerun makes no calls.
The public archival node allows only a few calls at a time (see fetch/staking_history.py).

References:
  https://docs.near.org/api-reference/post-validators   (the `validators` method)
  https://docs.near.org/api/rpc/providers               (the archival endpoint)
Output: data/raw/rpc/staking_validators.csv
Usage:  python -m fetch.staking_validators
"""
from __future__ import annotations

import pandas as pd

from fetch.common import RAW, read_json, record_fetch, write_json
from fetch.rpc import ARCHIVAL, YOCTO
from fetch.staking_history import OUT as HISTORY, validators_in

CACHE = RAW / "rpc" / "_staking_validators_cache.json"
OUT = RAW / "rpc" / "staking_validators.csv"


def compact(v: dict) -> dict:
    """Keep what we use from one `validators` response: each validator's stake, and who was kicked out and why."""
    return {
        "epoch_height": v["epoch_height"],
        "epoch_start_height": v["epoch_start_height"],
        "stakes": {x["account_id"]: x["stake"] for x in v["current_validators"]},
        "kickouts": {x["account_id"]: next(iter(x["reason"])) if isinstance(x["reason"], dict) else str(x["reason"])
                     for x in v["prev_epoch_kickout"]},
    }


def epoch(epoch_id: str) -> dict:
    """One past epoch's validators, compacted (cached)."""
    cache = read_json(CACHE, {})
    if epoch_id not in cache:
        cache[epoch_id] = compact(validators_in(epoch_id))
        write_json(CACHE, cache)
    return cache[epoch_id]


def months_around_low(history: pd.DataFrame) -> pd.DataFrame:
    """The month end with the lowest staked share, and the month ends before and after it."""
    i = int(history.staked_share_of_supply_pct.idxmin())
    return history.iloc[max(i - 1, 0): i + 2]


def main() -> None:
    history = pd.read_csv(HISTORY)
    rows = []
    for m in months_around_low(history).itertuples():
        e = epoch(m.epoch_id)
        if (e["epoch_height"], e["epoch_start_height"]) != (m.epoch_height, m.epoch_start_height):
            raise RuntimeError(f"{m.month}: the epoch returned is not the one in {HISTORY.name}")
        total = sum(int(s) for s in e["stakes"].values()) / YOCTO
        if abs(total - m.total_stake_near) > 1:
            raise RuntimeError(f"{m.month}: validators sum to {total:,.0f} NEAR, {HISTORY.name} has {m.total_stake_near:,.0f}")
        for account, stake in e["stakes"].items():
            rows.append({"month": m.month, "epoch_height": m.epoch_height, "account_id": account,
                         "stake_near": int(stake) / YOCTO, "kicked_out": e["kickouts"].get(account, "")})
        for account, reason in e["kickouts"].items():
            if account not in e["stakes"]:
                rows.append({"month": m.month, "epoch_height": m.epoch_height, "account_id": account,
                             "stake_near": 0.0, "kicked_out": reason})
        print(f"  {m.month}: {total:,.0f} NEAR staked by {len(e['stakes'])} validators, {len(e['kickouts'])} kicked out")
    df = pd.DataFrame(rows).sort_values(["month", "stake_near", "account_id"], ascending=[True, False, True])
    df.to_csv(OUT, index=False)
    record_fetch("staking_validators", url=ARCHIVAL,
                 method="validators by epoch_id (archival RPC) for the lowest month end in staking_history.csv and the month ends either side",
                 months=sorted(df.month.unique().tolist()), rows=len(df), file=OUT.name)
    print(f"Saved {len(df)} rows to {OUT.name}")


if __name__ == "__main__":
    main()
