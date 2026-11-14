"""C4. Intents is gaining share, not just moving with the market.

Market share of NEAR Intents among native cross-chain swap venues, monthly, from DefiLlama's
free per-protocol daily volumes (data/raw/defillama/dexs_overview.json):

    peer set: NEAR Intents, THORChain DEX, Chainflip AMM, Maya Protocol

Reference series (not added to the denominator, to avoid double counting, since aggregators
route trades through venues like these): total bridge-aggregator volume (LI.FI, Socket, Jumper,
Rango, ...), and total DEX volume (a "market activity" proxy for the counterpoint).

Coverage limit: DefiLlama's bridge volume data (Relay, deBridge, Across, Mayan, ...) is paid-only
(HTTP 402), so those competitors are missing. The denominator is incomplete, which overstates
Intents' share. The trend is more reliable than the level.

Output: data/derived/c4_market_share_monthly.csv
"""
from __future__ import annotations

import json

import pandas as pd

from analysis.common import RAW, save

PEERS = ["NEAR Intents", "THORChain DEX", "Chainflip AMM", "Maya Protocol"]


def breakdown(name: str) -> pd.DataFrame:
    d = json.loads((RAW / "defillama" / f"{name}.json").read_text())
    rows = []
    for ts, values in d["totalDataChartBreakdown"]:
        rows.append({"date": pd.to_datetime(ts, unit="s"), **{k: v for k, v in values.items() if isinstance(v, (int, float))}})
    return pd.DataFrame(rows).fillna(0.0)


def total(name: str) -> pd.DataFrame:
    d = json.loads((RAW / "defillama" / f"{name}.json").read_text())
    df = pd.DataFrame(d["totalDataChart"], columns=["ts", "volume"])
    df["date"] = pd.to_datetime(df.ts, unit="s")
    return df[["date", "volume"]]


def build() -> pd.DataFrame:
    dex = breakdown("dexs_overview")
    dex = dex[dex.date >= "2024-12-01"]
    dex["month"] = dex.date.dt.to_period("M")
    m = dex.groupby("month")[PEERS].sum()
    m.columns = [c.lower().replace(" ", "_") + "_usd" for c in m.columns]
    m["peer_total_usd"] = m.sum(axis=1)
    m["intents_share_of_peers_pct"] = 100 * m.near_intents_usd / m.peer_total_usd
    m["days"] = dex.groupby("month").date.nunique()

    agg = total("bridge_aggregators_overview"); agg["month"] = agg.date.dt.to_period("M")
    m["bridge_aggregators_usd"] = agg.groupby("month").volume.sum()
    alld = total("dexs_overview"); alld["month"] = alld.date.dt.to_period("M")
    m["all_dex_usd"] = alld.groupby("month").volume.sum()
    m["intents_vs_aggregators_ratio"] = m.near_intents_usd / m.bridge_aggregators_usd

    m = m.reset_index()
    m["partial_month"] = m.days < m.month.dt.days_in_month
    m["month"] = m.month.astype(str)
    return m.drop(columns="days")


def main() -> None:
    df = build()
    save(df, "c4_market_share_monthly")
    cols = ["month", "near_intents_usd", "thorchain_dex_usd", "chainflip_amm_usd", "maya_protocol_usd",
            "intents_share_of_peers_pct", "bridge_aggregators_usd", "all_dex_usd"]
    show = df[~df.partial_month][cols].copy()
    for c in cols[1:]:
        if c.endswith("_usd"):
            show[c] = show[c] / 1e9
    print("(volumes in $B)")
    print(show.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


if __name__ == "__main__":
    main()
