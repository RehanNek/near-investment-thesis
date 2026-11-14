"""C6. The share of value reaching the token is rising.

Capture ratio, monthly since Jan 2025:
    (L1 burn + NEAR captured as Intents revenue) / NEAR newly minted

  - NEAR minted and NEAR burned: BigQuery, from block-to-block changes in total supply
    (supply jumps up at epoch boundaries by the newly minted NEAR; within an epoch it only falls,
    by the NEAR burned).
  - NEAR captured as Intents revenue: revenue.near.org (revenue_near, from Aug 2025). This is the
    NEAR that flows to NEAR-controlled revenue wallets and funds buybacks.
  - NEAR newly staked for NEAR AI (stake.dao -> nearai.pool.near): reported as a separate line and a
    second ratio (capture_ratio_incl_ai_stake_pct), because staked NEAR is locked, not destroyed,
    and can be withdrawn. The headline capture ratio excludes it.

Two views of where captured NEAR goes, since buybacks are held, not burned:
  - "removed from total supply": L1 burn only (burned NEAR is destroyed)
  - "removed from circulation":  L1 burn + Intents revenue NEAR (held in revenue/buyback wallets)
Revenue-wallet balances (BigQuery ft_balances_daily) show how much captured NEAR is still held.

Outputs: data/derived/c6_capture_monthly.csv, data/derived/c6_revenue_wallets_monthly.csv
"""
from __future__ import annotations

import pandas as pd

from analysis.common import (intents_revenue_monthly, monthly, revenue_wallet_balances, save,
                             supply_flows_daily, tracker_revenue_pct_of_emissions_monthly)


def ai_stake_monthly() -> pd.DataFrame:
    """NEAR newly staked for NEAR AI each month (net), from month-end stake of nearai.pool.near.

    nearai.pool.near is the validator NEAR AI's staking contract (stake.dao) delegates to; ~99% of
    its stake comes through stake.dao (NEAR AI Cloud Credits farm + Agents subscriptions).
    Source: archival RPC snapshots in data/raw/rpc/nearai_pool_history.csv. Staked NEAR is
    locked, not destroyed, and can be withdrawn, so it's reported as a separate line.
    """
    from analysis.common import RAW
    h = pd.read_csv(RAW / "rpc" / "nearai_pool_history.csv").dropna(subset=["total_staked_near"])
    h["date"] = pd.to_datetime(h.date)
    h = h.sort_values("date")
    h["month"] = h.date.dt.to_period("M")
    month_end = h[h.date.dt.is_month_end].groupby("month").total_staked_near.last()
    added = month_end.diff()
    first = month_end.index[0]
    added[first] = month_end[first] - h[h.month == first].total_staked_near.iloc[0]  # from first July reading
    return pd.DataFrame({"month": month_end.index, "ai_staked_month_end_near": month_end.values,
                         "ai_stake_added_near": added.values})


def build_capture() -> pd.DataFrame:
    s = supply_flows_daily()
    s["month"] = monthly(s)
    m = s.groupby("month").agg(minted_near=("minted_near", "sum"), l1_burned_near=("burned_near", "sum"),
                               days=("date", "nunique")).reset_index()
    m = m.merge(intents_revenue_monthly()[["month", "intents_revenue_near"]], on="month", how="left")
    m = m.merge(tracker_revenue_pct_of_emissions_monthly(), on="month", how="left")
    m["intents_revenue_near"] = m.intents_revenue_near.fillna(0.0)
    m["captured_near"] = m.l1_burned_near + m.intents_revenue_near
    m["capture_ratio_pct"] = 100 * m.captured_near / m.minted_near
    m["l1_burn_pct_of_minted"] = 100 * m.l1_burned_near / m.minted_near
    m["intents_revenue_pct_of_minted"] = 100 * m.intents_revenue_near / m.minted_near
    # Separate line: NEAR newly locked for NEAR AI (staked, not removed; withdrawable)
    m = m.merge(ai_stake_monthly(), on="month", how="left")
    m["ai_stake_added_near"] = m.ai_stake_added_near.fillna(0.0)
    m["ai_stake_added_pct_of_minted"] = 100 * m.ai_stake_added_near / m.minted_near
    m["capture_ratio_incl_ai_stake_pct"] = 100 * (m.captured_near + m.ai_stake_added_near) / m.minted_near
    m["net_new_supply_near"] = m.minted_near - m.l1_burned_near            # change in total supply
    m["net_new_circulating_near"] = m.minted_near - m.captured_near        # if captured NEAR stays held
    m["annualised_mint_rate_pct"] = None  # filled below from supply level
    m["partial_month"] = m.days < m.month.dt.days_in_month

    supply = pd.read_csv(__import__("analysis.common", fromlist=["RAW"]).RAW / "bigquery" / "blocks_daily.csv",
                         parse_dates=["block_date"])
    supply["month"] = supply.block_date.dt.to_period("M")
    start_supply = supply.groupby("month").end_of_day_total_supply_near.first()
    m["start_supply_near"] = m.month.map(start_supply)
    m["annualised_mint_rate_pct"] = 100 * (m.minted_near / m.days * 365) / m.start_supply_near
    m["month"] = m.month.astype(str)
    return m.drop(columns="days")


def build_wallets() -> pd.DataFrame:
    w = revenue_wallet_balances()
    w["held_near"] = w.liquid.fillna(0) + w.staked.fillna(0) + w.unstaked_not_liquid.fillna(0)
    w["month"] = monthly(w)
    last = w.sort_values("date").groupby(["month", "account_id"], as_index=False).last()
    p = last.pivot_table(index="month", columns="account_id", values="held_near").ffill().fillna(0)
    p["total_held_near"] = p.sum(axis=1)
    p = p.reset_index()
    rev = intents_revenue_monthly()
    rev["cumulative_intents_revenue_near"] = rev.intents_revenue_near.cumsum()
    p = p.merge(rev[["month", "cumulative_intents_revenue_near"]], on="month", how="left")
    p["month"] = p.month.astype(str)
    return p


def build_quarterly(cap: pd.DataFrame) -> pd.DataFrame:
    """Quarterly capture ratio over complete months only (smooths batchy monthly revenue sweeps)."""
    full = cap[~cap.partial_month].copy()
    full["quarter"] = pd.PeriodIndex(full.month, freq="M").asfreq("Q").astype(str)
    q = full.groupby("quarter").agg(months=("month", "count"), minted_near=("minted_near", "sum"),
                                    l1_burned_near=("l1_burned_near", "sum"),
                                    intents_revenue_near=("intents_revenue_near", "sum")).reset_index()
    q["capture_ratio_pct"] = 100 * (q.l1_burned_near + q.intents_revenue_near) / q.minted_near
    return q


def main() -> None:
    cap = build_capture()
    save(cap, "c6_capture_monthly")
    q = build_quarterly(cap)
    save(q, "c6_capture_quarterly")
    print("Quarterly capture ratio (complete months):")
    print(q.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
    print()
    wal = build_wallets()
    save(wal, "c6_revenue_wallets_monthly")

    cols = ["month", "minted_near", "annualised_mint_rate_pct", "l1_burned_near", "intents_revenue_near",
            "capture_ratio_pct", "ai_stake_added_near", "capture_ratio_incl_ai_stake_pct", "tracker_revenue_pct_of_emissions"]
    print(cap[~cap.partial_month][cols].to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
    print("\nRevenue wallets, month-end NEAR held vs cumulative Intents revenue (NEAR):")
    print(wal.tail(8).to_string(index=False, float_format=lambda x: f"{x:,.0f}"))


if __name__ == "__main__":
    main()
