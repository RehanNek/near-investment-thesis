"""Cross-checks: each key series compared with an independent source, month by month.

  1. NEAR price:        NearBlocks (used) vs CoinGecko vs price implied by revenue.near.org
  2. L1 gross fees:     ours (BigQuery burn / 0.70) vs DefiLlama NEAR chain fees vs NearBlocks txn fees
  3. Intents revenue:   revenue.near.org vs DefiLlama NEAR Intents revenue
  4. NEAR minted:       ours (BigQuery supply jumps) vs the protocol rule (inflation rate x supply)
                        vs revenue.near.org's cumulative 2026 emissions

Output: data/derived/crosschecks_monthly.csv (one row per month and check), printed summary.
"""
from __future__ import annotations

import json

import pandas as pd

from analysis.common import (RAW, coingecko_price_daily, defillama_daily, intents_revenue_monthly, monthly,
                             near_price_daily, save, supply_flows_daily, tracker)


def pct_diff(a, b):
    return 100 * (a - b) / b


def main() -> None:
    rows = []

    # 1. Price
    p = near_price_daily().merge(coingecko_price_daily(), on="date", how="inner")
    p["month"] = monthly(p)
    pm = p.groupby("month")[["near_usd", "coingecko_usd"]].mean()
    rev = intents_revenue_monthly().set_index("month")
    pm["tracker_implied_usd"] = rev.intents_revenue_usd / rev.intents_revenue_near
    for m, r in pm.iterrows():
        rows.append({"month": str(m), "check": "price_usd", "ours": r.near_usd,
                     "independent": r.coingecko_usd, "source": "CoinGecko", "pct_diff": pct_diff(r.near_usd, r.coingecko_usd)})
        if pd.notna(r.tracker_implied_usd):
            rows.append({"month": str(m), "check": "price_usd", "ours": r.near_usd, "independent": r.tracker_implied_usd,
                         "source": "revenue.near.org implied", "pct_diff": pct_diff(r.near_usd, r.tracker_implied_usd)})

    # 2. L1 gross fees
    c1 = pd.read_csv(RAW.parent / "derived" / "c1_revenue_mix_monthly.csv").set_index("month")
    dl = defillama_daily("near_chain_fees", "fees_usd"); dl["month"] = monthly(dl).astype(str)
    dlm = dl.groupby("month").fees_usd.sum()
    nb = pd.DataFrame(json.loads((RAW / "nearblocks" / "charts.json").read_text()))
    nb["date"] = pd.to_datetime(nb.date.str[:10]); nb["month"] = monthly(nb).astype(str)
    nbm = nb.assign(fee=nb.txn_fee_usd.astype(float)).groupby("month").fee.sum()
    for m, r in c1.iterrows():
        for src, ser in (("DefiLlama", dlm), ("NearBlocks", nbm)):
            if m in ser.index and ser[m] > 0:
                rows.append({"month": m, "check": "l1_gross_fees_usd", "ours": r.l1_gross_fees_usd,
                             "independent": ser[m], "source": src, "pct_diff": pct_diff(r.l1_gross_fees_usd, ser[m])})

    # 3. Intents revenue
    dr = defillama_daily("near_intents_revenue", "rev_usd"); dr["month"] = monthly(dr)
    drm = dr.groupby("month").rev_usd.sum()
    for m, r in rev.iterrows():
        if m in drm.index and drm[m] > 0:
            rows.append({"month": str(m), "check": "intents_revenue_usd", "ours": r.intents_revenue_usd,
                         "independent": drm[m], "source": "DefiLlama", "pct_diff": pct_diff(r.intents_revenue_usd, drm[m])})

    # 4. Minted
    s = supply_flows_daily(); s["month"] = monthly(s)
    b = pd.read_csv(RAW / "bigquery" / "blocks_daily.csv", parse_dates=["block_date"])
    b["month"] = b.block_date.dt.to_period("M")
    sup = b.groupby("month").end_of_day_total_supply_near.first()
    mm = s.groupby("month").agg(minted=("minted_near", "sum"), days=("date", "nunique"))
    for m, r in mm.iterrows():
        rate = 0.05 if m < pd.Period("2025-11") else 0.025
        expected = sup[m] * rate * r.days / 365
        rows.append({"month": str(m), "check": "minted_near", "ours": r.minted, "independent": expected,
                     "source": f"protocol rule ({rate:.1%} x supply)", "pct_diff": pct_diff(r.minted, expected)})
    ar = tracker("absoluteRevEmissions"); last = ar.iloc[-1]
    ours_ytd = s[(s.date >= "2026-01-01") & (s.date <= last.date)].minted_near.sum()
    rows.append({"month": f"2026-01..{last.date}", "check": "minted_near_ytd", "ours": ours_ytd,
                 "independent": last.emissionsNear, "source": "revenue.near.org emissions",
                 "pct_diff": pct_diff(ours_ytd, last.emissionsNear)})

    df = pd.DataFrame(rows)
    save(df, "crosschecks_monthly")
    summary = df.groupby(["check", "source"]).pct_diff.agg(
        months="count", median_pct_diff="median", worst_abs_pct_diff=lambda x: x.abs().max())
    print(summary.round(1).to_string())


if __name__ == "__main__":
    main()
