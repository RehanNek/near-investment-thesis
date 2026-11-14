"""C2. The L1 is becoming Intents' settlement layer.

From BigQuery (transactions table, since Jan 2025):
  - monthly average L1 transactions per day, transactions sent directly to intents.near, and
    the Intents share of L1 transactions;
  - the same split by the two big consumer apps (KaiChing, HOT) from queries/l1_app_split_daily.sql,
    giving L1 activity with KaiChing removed and the Intents share on that basis;
  - what drove the March -> April 2026 drop, grouping accounts by parent (e.g. all *.kaiching
    accounts together), from queries/l1_drop_mar_apr_2026.sql.

Note: signers of transactions to intents.near are mostly solvers and relayers, so Intents
*user* counts come from the Explorer API (C3), not from L1 signers.

Outputs: data/derived/c2_l1_monthly.csv, data/derived/c2_drop_mar_apr_2026.csv
"""
from __future__ import annotations

import pandas as pd

from analysis.common import bq, l1_daily, monthly, save


def build_monthly() -> pd.DataFrame:
    d = l1_daily()
    split = bq("l1_app_split_daily", parse_dates=["block_date"]).rename(
        columns={"block_date": "date", "transactions": "transactions_split"})
    d = d.merge(split, on="date", how="left")
    d["month"] = monthly(d)
    m = d.groupby("month").agg(days=("date", "nunique"), tx_per_day=("transactions", "mean"),
                               intents_tx_per_day=("tx_to_intents", "mean"),
                               kaiching_tx_per_day=("kaiching_tx", "mean"),
                               hot_tg_tx_per_day=("hot_tg_tx", "mean"),
                               signers_per_day=("signers", "mean")).reset_index()
    m["intents_share_of_l1_tx_pct"] = 100 * m.intents_tx_per_day / m.tx_per_day
    m["non_intents_tx_per_day"] = m.tx_per_day - m.intents_tx_per_day
    # L1 activity without the two big consumer apps (KaiChing, HOT) and without Intents
    m["other_tx_per_day"] = m.tx_per_day - m.intents_tx_per_day - m.kaiching_tx_per_day - m.hot_tg_tx_per_day
    m["tx_ex_kaiching_per_day"] = m.tx_per_day - m.kaiching_tx_per_day
    m["intents_share_ex_kaiching_pct"] = 100 * m.intents_tx_per_day / m.tx_ex_kaiching_per_day
    m["partial_month"] = m.days < m.month.dt.days_in_month
    m["month"] = m.month.astype(str)
    return m.drop(columns="days")


def build_drop() -> pd.DataFrame:
    d = bq("l1_drop_mar_apr_2026")
    p = d.pivot_table(index=["side", "account_parent"], columns="month", values="transactions", aggfunc="sum").fillna(0)
    p.columns = [f"tx_{c.replace('-', '_')}" for c in p.columns]
    p = p.reset_index()
    p["change"] = p.tx_2026_04 - p.tx_2026_03
    return p.sort_values(["side", "change"])


def main() -> None:
    m = build_monthly()
    save(m, "c2_l1_monthly")
    drop = build_drop()
    save(drop, "c2_drop_mar_apr_2026")
    cols = ["month", "tx_per_day", "kaiching_tx_per_day", "hot_tg_tx_per_day", "intents_tx_per_day",
            "other_tx_per_day", "intents_share_of_l1_tx_pct", "intents_share_ex_kaiching_pct"]
    print(m[~m.partial_month][cols].to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
    tot = l1_daily(); tot["m"] = monthly(tot).astype(str); t = tot.groupby("m").transactions.sum()
    k = drop[(drop.side == "receiver") & (drop.account_parent == "kaiching")].iloc[0]
    fall = t["2026-04"] - t["2026-03"]
    print(f"\nMarch -> April 2026: total L1 transactions {t['2026-03']/1e6:.1f}M -> {t['2026-04']/1e6:.1f}M "
          f"({fall/1e6:+.1f}M). KaiChing (*.kaiching): {k.tx_2026_03/1e6:.1f}M -> {k.tx_2026_04/1e6:.1f}M, "
          f"{100*k.change/fall:.0f}% of the fall; {100*k.tx_2026_03/t['2026-03']:.0f}% of March transactions.")


if __name__ == "__main__":
    main()
