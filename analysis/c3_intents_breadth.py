"""C3. Intents is a real, broad-based growth engine.

Step 1 (only where the full download is present): consolidate the raw Explorer API pages
(data/raw/explorer/pages/, ~2.6 GB, git-ignored) into one deduplicated table, data/raw/explorer/swaps.parquet
(also git-ignored), then write the committed per-swap table from it: data/raw/explorer/swaps/*.parquet, one row
per swap with the six fields this analysis uses.
Step 2 (everywhere, part of `make charts`): aggregate the committed per-swap table into the summaries the
charts are drawn from.

The committed table keeps the rows in download order and changes one thing: `user` is a 64-bit id, the first
8 bytes of SHA-256 of the user's address, because the address strings alone are over 120 MB. Distinct-user counts
and top-user shares are the same on ids as on addresses (the build fails if two addresses share an id).

Definitions
  - swap:   one successful 1Click swap (status SUCCESS), deduplicated by deposit address + memo + creation time
            (a deposit address can be used again later; the download has 58 such repeats)
  - volume: amountInUsd (USD value of what the user sent)
  - user:   the first address in `senders`; for swaps paid from an existing Intents balance
            (no senders), the refund account (`refundTo`), which is the user's own Intents account
  - chain:  the blockchain of the origin / destination asset, from the 1Click token list
  - stablecoin: a token whose symbol contains "USD", or DAI

Outputs (data/derived/): c3_daily.csv, c3_monthly.csv, c3_referrers_monthly.csv, c3_chains_monthly.csv
Months not fully covered by the downloaded pages are flagged `complete_month = False`.

Usage: python -m analysis.c3_intents_breadth            (consolidate if pages changed, then aggregate)
       python -m analysis.c3_intents_breadth --table    (also print the monthly summary)
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from analysis.common import RAW, save

PAGES = RAW / "explorer" / "pages"
SWAPS = RAW / "explorer" / "swaps.parquet"
STATE = RAW / "explorer" / "state.json"
TABLE = RAW / "explorer" / "swaps"  # committed: one row per swap, split so each file stays well under GitHub's limit
PARTS = 3
COLS = ["ts", "volume_usd", "origin", "destination", "user", "referral", "deposit_type"]


def consolidate() -> None:
    files = sorted(glob.glob(str(PAGES / "*.jsonl.gz")))
    if not files:
        return
    if SWAPS.exists() and SWAPS.stat().st_mtime > max(PAGES.joinpath(f).stat().st_mtime for f in files):
        return
    cols = {k: [] for k in ("key", "ts", "volume_usd", "origin", "destination", "user", "referral", "deposit_type")}
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                senders = r.get("senders") or []
                cols["key"].append(f"{r.get('depositAddress')}|{r.get('depositMemo') or ''}")
                cols["ts"].append(int(r.get("createdAtTimestamp") or 0))
                v = r.get("amountInUsd")
                cols["volume_usd"].append(float(v) if v not in (None, "") else np.nan)
                cols["origin"].append(r.get("originAsset"))
                cols["destination"].append(r.get("destinationAsset"))
                cols["user"].append(senders[0] if senders else r.get("refundTo"))
                cols["referral"].append(r.get("referral") or "(none)")
                cols["deposit_type"].append(r.get("depositType"))
    df = pd.DataFrame(cols).drop_duplicates(["key", "ts"])
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), SWAPS, compression="zstd")
    print(f"  consolidated {len(files)} pages -> {len(df):,} unique swaps")


def user_ids(addresses: pd.Series) -> np.ndarray:
    """A 64-bit id per user: the first 8 bytes of SHA-256 of the address."""
    codes, uniq = pd.factorize(addresses.fillna("(none)"))
    ids = np.array([int.from_bytes(hashlib.sha256(str(u).encode()).digest()[:8], "big", signed=True) for u in uniq],
                   dtype="int64")
    if len(np.unique(ids)) != len(uniq):
        raise RuntimeError("two user addresses share a 64-bit id; use more bytes of the hash")
    return ids[codes]


def parts() -> list:
    return sorted(TABLE.glob("swaps-*.parquet"))


def write_table() -> None:
    """Write the committed per-swap table from the full local one, when the local one is newer."""
    if not SWAPS.exists() or (parts() and min(p.stat().st_mtime for p in parts()) > SWAPS.stat().st_mtime):
        return
    df = pd.read_parquet(SWAPS, columns=COLS)
    df["user"] = user_ids(df.user)
    TABLE.mkdir(exist_ok=True)
    for p in parts():
        p.unlink()
    edges = np.linspace(0, len(df), PARTS + 1).astype(int)
    for i in range(PARTS):
        pq.write_table(pa.Table.from_pandas(df.iloc[edges[i]:edges[i + 1]], preserve_index=False),
                       TABLE / f"swaps-{i + 1}-of-{PARTS}.parquet", compression="zstd", compression_level=15)
    print(f"  wrote {len(df):,} swaps to {TABLE.relative_to(RAW.parent.parent)}/ in {PARTS} files")


def read_swaps(columns=None) -> pd.DataFrame:
    """The committed per-swap table, rows in download order."""
    return pd.concat([pd.read_parquet(p, columns=columns) for p in parts()], ignore_index=True)


def load() -> pd.DataFrame:
    df = read_swaps()
    df["date"] = pd.to_datetime(df.ts, unit="s").dt.normalize()
    tokens = {t["assetId"]: t for t in json.loads((RAW / "oneclick" / "tokens.json").read_text())}
    chain = {k: t["blockchain"] for k, t in tokens.items()}
    sym = {k: str(t["symbol"]).upper() for k, t in tokens.items()}
    for side in ("origin", "destination"):
        df[f"{side}_chain"] = df[side].map(chain).fillna("(unknown)")
        s = df[side].map(sym).fillna("")
        df[f"{side}_stable"] = s.str.contains("USD") | (s == "DAI")
    for c in ("user", "referral", "origin_chain", "destination_chain", "deposit_type"):
        df[c] = df[c].astype("category")
    return df


def topn_share(g: pd.DataFrame, by: str, n: int = 10) -> float:
    v = g.groupby(by, observed=True).volume_usd.sum().sort_values(ascending=False)
    return 100 * v.head(n).sum() / v.sum() if v.sum() else np.nan


def monthly(df: pd.DataFrame, complete_from: pd.Timestamp) -> pd.DataFrame:
    df["month"] = df.date.dt.to_period("M")
    out = []
    for m, g in df.groupby("month"):
        vol = g.volume_usd.sum()
        nonnear = g[(g.origin_chain != "near") & (g.destination_chain != "near")].volume_usd.sum()
        out.append({
            "month": str(m),
            "swaps": len(g),
            "volume_usd": vol,
            "unique_users": g.user.nunique(),
            "top10_users_share_of_volume_pct": topn_share(g, "user", 10),
            "top100_users_share_of_volume_pct": topn_share(g, "user", 100),
            "active_referrers": g.referral.nunique(),
            "top_referrer_share_of_volume_pct": topn_share(g, "referral", 1),
            "active_origin_chains": g.origin_chain.nunique(),
            "active_chain_pairs": g.groupby(["origin_chain", "destination_chain"], observed=True).ngroups,
            "non_near_both_sides_share_pct": 100 * nonnear / vol if vol else np.nan,
            "stable_to_stable_share_pct": 100 * g[g.origin_stable & g.destination_stable].volume_usd.sum() / vol if vol else np.nan,
            "any_stable_share_pct": 100 * g[g.origin_stable | g.destination_stable].volume_usd.sum() / vol if vol else np.nan,
            "swaps_missing_usd": int(g.volume_usd.isna().sum()),
            "complete_month": bool(m.start_time >= complete_from and m.end_time.normalize() < df.date.max()),
        })
    return pd.DataFrame(out)


def breakdown(df: pd.DataFrame, col: str, n: int = 10) -> pd.DataFrame:
    rows = []
    for m, g in df.groupby("month"):
        v = g.groupby(col, observed=True).volume_usd.sum().sort_values(ascending=False)
        total = v.sum()
        for name, x in v.head(n).items():
            rows.append({"month": str(m), col: name, "volume_usd": x, "share_pct": 100 * x / total})
        rows.append({"month": str(m), col: "(other)", "volume_usd": v.iloc[n:].sum(), "share_pct": 100 * v.iloc[n:].sum() / total})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--table", action="store_true", help="also print the monthly summary")
    args = ap.parse_args()
    consolidate()
    write_table()
    if not parts():
        print(f"  C3: no per-swap table in {TABLE.relative_to(RAW.parent.parent)}/; keeping the committed summaries "
              "(data/derived/c3_*.csv). `make fetch-explorer` downloads the swaps.")
        return
    df = load()
    state = json.loads(STATE.read_text())["backfill"]
    oldest = pd.to_datetime(state["oldest"], unit="s")
    complete_from = oldest.normalize() + pd.Timedelta(days=1) if not state.get("done") else pd.Timestamp("1970-01-01")

    daily = df.groupby("date").agg(swaps=("ts", "size"), volume_usd=("volume_usd", "sum"),
                                   unique_users=("user", "nunique")).reset_index()
    daily["complete_day"] = (daily.date >= complete_from) & (daily.date < df.date.max())
    save(daily, "c3_daily")
    m = monthly(df, complete_from)
    # Download gaps: 3+ days with no swaps once activity passed 1,000 swaps a day (fetch.explorer --fill-gaps refills them).
    busy = daily.date[daily.swaps >= 1000].min()
    missing = pd.date_range(busy, df.date.max()).difference(daily.date)
    runs = [g for g in np.split(missing, np.where(np.diff(missing.asi8) > 86400 * 10**9)[0] + 1) if len(g) >= 3] if len(missing) else []
    for g in runs:
        print(f"  WARNING: no swaps from {g[0].date()} to {g[-1].date()} ({len(g)} days): a download gap? "
              "Run python -m fetch.explorer --fill-gaps")
        m.loc[m.month.isin({str(p) for p in g.to_period("M")}), "complete_month"] = False
    save(m, "c3_monthly")
    save(breakdown(df, "referral"), "c3_referrers_monthly")
    save(breakdown(df, "origin_chain"), "c3_chains_monthly")

    print(f"  C3: {len(df):,} swaps; covering {df.date.min().date()} .. {df.date.max().date()} "
          f"(complete from {complete_from.date()}; backfill done: {bool(state.get('done'))})")
    if args.table:
        cols = ["month", "swaps", "volume_usd", "unique_users", "top10_users_share_of_volume_pct", "active_referrers",
                "top_referrer_share_of_volume_pct", "active_origin_chains", "non_near_both_sides_share_pct",
                "stable_to_stable_share_pct", "complete_month"]
        print(m[cols].to_string(index=False, float_format=lambda x: f"{x:,.1f}"))


if __name__ == "__main__":
    main()
