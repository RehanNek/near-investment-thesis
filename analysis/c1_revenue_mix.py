"""C1. Most of NEAR's revenue now comes from beyond the L1.

Compares, month by month since Jan 2025:
  - L1 side:      NEAR burned by L1 gas fees (BigQuery, block-level supply changes), valued in USD
                  at the daily NEAR price. Gross L1 fees = burned / share burned: 0.70 until
                  HSP-027 took effect, 1.0 after (analysis.common.l1_burn_share).
  - Intents side: NEAR's net Intents revenue after partner payouts (revenue.near.org), and gross
                  Intents fees (revenue.near.org).

Two like-for-like shares are reported:
  - net basis:   Intents net revenue vs L1 burn (value kept by the protocol in each case)
  - gross basis: Intents gross fees vs L1 gross fees (all fees paid by users in each case)

Output: data/derived/c1_revenue_mix_monthly.csv
"""
from __future__ import annotations

import pandas as pd

from analysis.common import (l1_burn_share, intents_fees_daily, intents_revenue_monthly, monthly,
                             near_price_daily, save, supply_flows_daily)


def build() -> pd.DataFrame:
    burn = supply_flows_daily().merge(near_price_daily(), on="date", how="left")
    burn["near_usd"] = burn.near_usd.ffill()
    burn["l1_burn_usd"] = burn.burned_near * burn.near_usd
    burn["l1_gross_fees_usd"] = burn.l1_burn_usd / l1_burn_share(burn.date)
    burn["month"] = monthly(burn)
    l1 = burn.groupby("month").agg(l1_burn_near=("burned_near", "sum"), l1_burn_usd=("l1_burn_usd", "sum"),
                                   l1_gross_fees_usd=("l1_gross_fees_usd", "sum"),
                                   days=("date", "nunique")).reset_index()

    fees = intents_fees_daily()
    fees["month"] = monthly(fees)
    gross = fees.groupby("month", as_index=False).intents_gross_fees_usd.sum()

    df = l1.merge(gross, on="month", how="left").merge(intents_revenue_monthly(), on="month", how="left")
    df[["intents_gross_fees_usd", "intents_revenue_usd", "intents_revenue_near"]] = \
        df[["intents_gross_fees_usd", "intents_revenue_usd", "intents_revenue_near"]].fillna(0.0)

    df["intents_share_net_pct"] = 100 * df.intents_revenue_usd / (df.intents_revenue_usd + df.l1_burn_usd)
    df["intents_share_gross_pct"] = 100 * df.intents_gross_fees_usd / (df.intents_gross_fees_usd + df.l1_gross_fees_usd)
    df["partial_month"] = df.days < df.month.dt.days_in_month
    df["month"] = df.month.astype(str)
    return df.drop(columns="days")


def main() -> None:
    df = build()
    path = save(df, "c1_revenue_mix_monthly")
    full = df[~df.partial_month]
    show = full[["month", "l1_burn_usd", "intents_revenue_usd", "intents_share_net_pct",
                 "l1_gross_fees_usd", "intents_gross_fees_usd", "intents_share_gross_pct"]]
    print(show.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
    last3 = full.tail(3)
    net = 100 * last3.intents_revenue_usd.sum() / (last3.intents_revenue_usd.sum() + last3.l1_burn_usd.sum())
    gross = 100 * last3.intents_gross_fees_usd.sum() / (last3.intents_gross_fees_usd.sum() + last3.l1_gross_fees_usd.sum())
    print(f"\nLast 3 complete months ({last3.month.iloc[0]}..{last3.month.iloc[-1]}): "
          f"Intents share of revenue {net:.1f}% (net basis), {gross:.1f}% (gross basis)")
    print(f"Saved {path.relative_to(path.parents[2])}")


if __name__ == "__main__":
    main()
