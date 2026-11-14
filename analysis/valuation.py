"""Valuation check: is NEAR priced like an L1, like a swap business, or in between?

Reads the peer data saved by fetch/peers.py (DefiLlama fees and revenue, CoinGecko market caps) and
NEAR's own first-party revenue (data/derived/c1_revenue_mix_monthly.csv), then computes:

  1. Multiples. Market cap on AS_OF divided by annualised fees, protocol revenue and token-holder
     revenue, for NEAR, each L1 peer and each swap peer, over two windows (the last complete month,
     and the last three complete months). NEAR is shown on two bases: DefiLlama (same source as the
     peers) and the NEAR Revenue Tracker (the source the rest of the thesis uses).
  2. Price. NEAR's price over the year against an equal-weighted basket of L1 peers and of swap
     peers, by period, and how closely its daily returns follow each basket.
  3. Sum of the parts. Intents' revenue at swap-peer multiples plus the L1's fees at L1-peer
     multiples, set against NEAR's market cap.

Definitions follow DefiLlama: "fees" is everything users paid, "revenue" is the part the protocol
keeps (for a chain, the fees it burns), "holders revenue" is the part that reaches token holders
through burns, buybacks or distributions.

Outputs: data/derived/valuation_multiples.csv, valuation_price_index.csv, valuation_price_periods.csv,
         valuation_sum_of_parts.csv, valuation_summary.json
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from analysis.common import DERIVED, RAW, save

AS_OF = pd.Timestamp("2026-11-06")  # CoinGecko's 00:00 UTC point, i.e. the close of Nov 5, the last day of NEAR's committed data
MONTH = pd.Period("2026-10", "M")  # the last complete month
WINDOWS = {"1m": (MONTH, MONTH), "3m": (MONTH - 2, MONTH)}
CROSS_CHAIN = {"THORChain", "Chainflip", "deBridge", "Across"}  # the rest of the swap set are DEXes and aggregators
PERIODS = {  # for the price comparison
    "full window": (None, AS_OF),
    "before Aug 2026": (None, pd.Timestamp("2026-07-31")),
    "Aug to Oct 2026": (pd.Timestamp("2026-07-31"), pd.Timestamp("2026-10-31")),
}
PEERS = RAW / "peers"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def llama_daily(slugs: list[str]) -> pd.DataFrame:
    """Daily fees, revenue and holders revenue, added up across a name's DefiLlama slugs."""
    out = None
    for slug in slugs:
        d = _json(PEERS / "defillama" / f"{slug}.json")
        cols = {}
        for key, col in [("dailyFees", "fees"), ("dailyRevenue", "revenue"), ("dailyHoldersRevenue", "holders")]:
            s = pd.Series({pd.to_datetime(ts, unit="s"): float(v) for ts, v in d.get(key) or []}, dtype=float)
            cols[col] = s
        df = pd.DataFrame(cols)
        out = df if out is None else out.add(df, fill_value=0.0)
    return out.fillna(0.0)


def gecko_daily(gid: str) -> pd.DataFrame:
    d = _json(PEERS / "coingecko" / f"{gid}.json")
    px = pd.DataFrame(d["prices"], columns=["ms", "price"])
    mc = pd.DataFrame(d["market_caps"], columns=["ms", "mcap"])
    df = px.merge(mc, on="ms")
    df["date"] = pd.to_datetime(df.ms, unit="ms").dt.normalize()
    return df.groupby("date").last()[["price", "mcap"]]


def annualised(df: pd.DataFrame, window: tuple[pd.Period, pd.Period]) -> pd.Series:
    start, end = window[0].start_time, window[1].end_time.normalize()
    part = df[(df.index >= start) & (df.index <= end)]
    days = (end - start).days + 1
    if len(part) < days * 0.9:  # the series does not cover the window
        return pd.Series({c: np.nan for c in df.columns})
    return part.sum() * 365 / days


def near_tracker(window: tuple[pd.Period, pd.Period]) -> dict:
    """NEAR's fees and revenue from the Revenue Tracker and on-chain burns (the thesis's own basis)."""
    c1 = pd.read_csv(DERIVED / "c1_revenue_mix_monthly.csv")
    c1["month"] = pd.PeriodIndex(c1.month, freq="M")
    part = c1[(c1.month >= window[0]) & (c1.month <= window[1])]
    days = (window[1].end_time.normalize() - window[0].start_time).days + 1
    k = 365 / days
    return {
        "fees": (part.l1_gross_fees_usd.sum() + part.intents_gross_fees_usd.sum()) * k,
        "revenue": (part.l1_burn_usd.sum() + part.intents_revenue_usd.sum()) * k,
        "holders": (part.l1_burn_usd.sum() + part.intents_revenue_usd.sum()) * k,
        "l1_fees": part.l1_gross_fees_usd.sum() * k,
        "l1_revenue": part.l1_burn_usd.sum() * k,
        "intents_fees": part.intents_gross_fees_usd.sum() * k,
        "intents_revenue": part.intents_revenue_usd.sum() * k,
    }


def multiples() -> pd.DataFrame:
    index = _json(PEERS / "index.json")
    markets = {m["id"]: m for m in _json(PEERS / "coingecko_markets.json")}
    rows = []
    for r in index:
        g = gecko_daily(r["gecko_id"])
        mcap = float(g.mcap.get(AS_OF, np.nan))
        if not mcap > 0:  # CoinGecko reports no market cap for this token on the as-of date
            mcap = np.nan
        m = markets[r["gecko_id"]]
        fdv_ratio = (m.get("fully_diluted_valuation") or np.nan) / (m.get("market_cap") or np.nan)
        daily = llama_daily(r["slugs"])
        row = {
            "group": r["group"],
            "subgroup": "cross-chain" if r["name"] in CROSS_CHAIN else ("dex" if r["group"] == "swap" else r["group"]),
            "name": r["name"] if r["group"] != "near" else "NEAR (DefiLlama)",
            "mcap_usd": mcap,
            "fdv_to_mcap": fdv_ratio,
        }
        for w, window in WINDOWS.items():
            a = annualised(daily, window)
            for c in ["fees", "revenue", "holders"]:
                row[f"{c}_{w}_usd"] = a[c]
                row[f"mcap_to_{c}_{w}"] = mcap / a[c] if a[c] > 0 else np.nan  # NaN market cap stays NaN
        rows.append(row)
        if r["group"] == "near":  # the same token on the thesis's own revenue basis
            row = {**row, "name": "NEAR (Revenue Tracker)"}
            for w, window in WINDOWS.items():
                t = near_tracker(window)
                for c in ["fees", "revenue", "holders"]:
                    row[f"{c}_{w}_usd"] = t[c]
                    row[f"mcap_to_{c}_{w}"] = mcap / t[c]
            rows.append(row)
    return pd.DataFrame(rows)


def quartiles(s: pd.Series) -> dict:
    s = s.dropna()
    return {"n": int(len(s)), "p25": float(s.quantile(0.25)), "median": float(s.median()), "p75": float(s.quantile(0.75)),
            "min": float(s.min()), "max": float(s.max())}


def price_comparison() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    index = _json(PEERS / "index.json")
    px = pd.DataFrame({r["name"]: gecko_daily(r["gecko_id"]).price for r in index})
    px = px[px.index <= AS_OF]
    px = px.dropna(axis=1, thresh=int(len(px) * 0.98)).ffill()  # keep names priced over the whole window
    groups = {g: [r["name"] for r in index if r["group"] == g and r["name"] in px.columns] for g in ["l1", "swap"]}
    groups["cross-chain"] = [n for n in groups["swap"] if n in CROSS_CHAIN]
    ret = np.log(px).diff().dropna()
    basket = pd.DataFrame({g: ret[names].mean(axis=1) for g, names in groups.items()})  # equal weight, rebalanced daily
    basket["NEAR"] = ret["NEAR"]

    idx = (100 * np.exp(basket.cumsum())).reset_index().rename(columns={"index": "date"})
    idx = idx.rename(columns={"NEAR": "near_index", "l1": "l1_basket_index", "swap": "swap_basket_index",
                              "cross-chain": "cross_chain_basket_index"})

    rows = []
    for label, (start, end) in PERIODS.items():
        part = basket[(basket.index > (start if start is not None else basket.index[0] - pd.Timedelta(days=1))) & (basket.index <= end)]
        row = {"period": label, "from": part.index[0].date().isoformat(), "to": part.index[-1].date().isoformat(), "days": len(part)}
        for col in ["NEAR", "l1", "swap", "cross-chain"]:
            row[f"{col}_change_pct"] = 100 * (np.exp(part[col].sum()) - 1)
        for col in ["l1", "swap", "cross-chain"]:
            row[f"corr_near_{col}"] = part["NEAR"].corr(part[col])
        # NEAR's daily return explained by both baskets at once
        X = np.column_stack([np.ones(len(part)), part["l1"], part["swap"]])
        beta, *_ = np.linalg.lstsq(X, part["NEAR"].to_numpy(), rcond=None)
        fitted = X @ beta
        row["beta_l1"], row["beta_swap"] = beta[1], beta[2]
        row["r2_both"] = 1 - ((part["NEAR"] - fitted) ** 2).sum() / ((part["NEAR"] - part["NEAR"].mean()) ** 2).sum()
        # the part of NEAR's move that neither basket explains (alpha, compounded over the period)
        row["unexplained_change_pct"] = 100 * (np.exp(beta[0] * len(part)) - 1)
        rows.append(row)
    return idx, pd.DataFrame(rows), {g: names for g, names in groups.items()}


def sum_of_parts(mult: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    near_mcap = float(mult[mult.group == "near"].mcap_usd.iloc[0])
    swap, cross, l1 = mult[mult.group == "swap"], mult[mult.subgroup == "cross-chain"], mult[mult.group == "l1"]
    rows, stats = [], {}
    for w, window in WINDOWS.items():
        t = near_tracker(window)
        q = {
            "swap_rev": quartiles(swap[f"mcap_to_revenue_{w}"]), "swap_fees": quartiles(swap[f"mcap_to_fees_{w}"]),
            "cross_rev": quartiles(cross[f"mcap_to_revenue_{w}"]), "cross_fees": quartiles(cross[f"mcap_to_fees_{w}"]),
            "l1_rev": quartiles(l1[f"mcap_to_revenue_{w}"]), "l1_fees": quartiles(l1[f"mcap_to_fees_{w}"]),
        }
        stats[w] = {"near_tracker": t, "peer_multiples": q}
        for case, k in [("low", "p25"), ("mid", "median"), ("high", "p75"), ("top peer", "max")]:
            intents = t["intents_revenue"] * q["swap_rev"][k]
            l1_value = t["l1_fees"] * q["l1_fees"][k]
            rows.append({
                "window": w, "case": case,
                "intents_revenue_usd": t["intents_revenue"], "swap_peer_mcap_to_revenue": q["swap_rev"][k], "intents_value_usd": intents,
                "l1_fees_usd": t["l1_fees"], "l1_peer_mcap_to_fees": q["l1_fees"][k], "l1_value_usd": l1_value,
                "sum_usd": intents + l1_value, "near_mcap_usd": near_mcap, "sum_pct_of_mcap": 100 * (intents + l1_value) / near_mcap,
                "intents_only_pct_of_mcap": 100 * intents / near_mcap,
            })
        # what the market is paying for Intents if the L1 is worth the L1-peer median on its fees
        l1_mid = t["l1_fees"] * q["l1_fees"]["median"]
        stats[w]["implied"] = {
            "near_mcap_usd": near_mcap,
            "l1_value_at_peer_median_usd": l1_mid,
            "left_for_intents_and_ai_usd": near_mcap - l1_mid,
            "implied_multiple_of_intents_revenue": (near_mcap - l1_mid) / t["intents_revenue"],
            "intents_revenue_growth_needed_at_swap_median_x": (near_mcap - l1_mid) / (t["intents_revenue"] * q["swap_rev"]["median"]),
            "near_value_at_l1_median_revenue_multiple_usd": t["revenue"] * q["l1_rev"]["median"],
            "buyback_and_burn_yield_pct": 100 * t["holders"] / near_mcap,
        }
    return pd.DataFrame(rows), stats


def fmt_usd(v: float) -> str:
    if v != v:
        return "n/a"
    return f"${v / 1e9:,.2f}B" if abs(v) >= 1e9 else f"${v / 1e6:,.1f}M"


def fmt_x(v: float) -> str:
    return "n/a" if v != v else (f"{v:,.0f}x" if v >= 10 else f"{v:,.1f}x")


def main() -> None:
    mult = multiples()
    save(mult, "valuation_multiples")
    idx, periods, groups = price_comparison()
    save(idx, "valuation_price_index")
    save(periods, "valuation_price_periods")
    sop, stats = sum_of_parts(mult)
    save(sop, "valuation_sum_of_parts")
    summary = {"as_of": AS_OF.date().isoformat(), "month": str(MONTH), "price_baskets": groups, "windows": stats}
    (DERIVED / "valuation_summary.json").write_text(json.dumps(summary, indent=1, default=float) + "\n", encoding="utf-8")

    for w in WINDOWS:
        print(f"\n=== Multiples, market cap on {AS_OF.date()} / annualised {w} to {MONTH} ===")
        print(f"{'':24s} {'mcap':>9s} {'fees':>10s} {'revenue':>10s} {'holders':>10s} {'mc/fees':>8s} {'mc/rev':>8s} {'mc/hold':>8s} {'fdv/mc':>6s}")
        for _, r in mult.sort_values(["group", f"mcap_to_revenue_{w}"]).iterrows():
            print(f"{r.group:5s} {r['name']:18s} {fmt_usd(r.mcap_usd):>9s} {fmt_usd(r[f'fees_{w}_usd']):>10s} {fmt_usd(r[f'revenue_{w}_usd']):>10s} "
                  f"{fmt_usd(r[f'holders_{w}_usd']):>10s} {fmt_x(r[f'mcap_to_fees_{w}']):>8s} {fmt_x(r[f'mcap_to_revenue_{w}']):>8s} "
                  f"{fmt_x(r[f'mcap_to_holders_{w}']):>8s} {r.fdv_to_mcap:6.2f}")
        for label, q in stats[w]["peer_multiples"].items():
            print(f"  {label:10s} n={q['n']:2d}  p25 {fmt_x(q['p25']):>7s}  median {fmt_x(q['median']):>7s}  p75 {fmt_x(q['p75']):>7s}  max {fmt_x(q['max']):>8s}")

    print("\n=== Price: NEAR against the baskets ===")
    print("baskets:", {g: len(n) for g, n in groups.items()})
    for _, r in periods.iterrows():
        print(f"{r.period:16s} {r['from']} to {r['to']}: NEAR {r.NEAR_change_pct:+.0f}%, L1 basket {r.l1_change_pct:+.0f}%, swap basket {r.swap_change_pct:+.0f}%, "
              f"cross-chain {r['cross-chain_change_pct']:+.0f}% | corr L1 {r.corr_near_l1:.2f}, swap {r.corr_near_swap:.2f}, cross-chain {r['corr_near_cross-chain']:.2f} "
              f"| beta L1 {r.beta_l1:.2f}, swap {r.beta_swap:.2f}, R2 {r.r2_both:.2f}, unexplained {r.unexplained_change_pct:+.0f}%")

    print("\n=== Sum of the parts (Intents revenue x swap-peer multiple + L1 fees x L1-peer multiple) ===")
    for _, r in sop.iterrows():
        print(f"{r.window} {r.case:9s} Intents {fmt_usd(r.intents_revenue_usd)} x {fmt_x(r.swap_peer_mcap_to_revenue)} = {fmt_usd(r.intents_value_usd)} | "
              f"L1 {fmt_usd(r.l1_fees_usd)} x {fmt_x(r.l1_peer_mcap_to_fees)} = {fmt_usd(r.l1_value_usd)} | sum {fmt_usd(r.sum_usd)} = "
              f"{r.sum_pct_of_mcap:.0f}% of {fmt_usd(r.near_mcap_usd)} (Intents alone {r.intents_only_pct_of_mcap:.0f}%)")
    for w in WINDOWS:
        i = stats[w]["implied"]
        print(f"{w}: L1 at peer median {fmt_usd(i['l1_value_at_peer_median_usd'])}; left for Intents and AI {fmt_usd(i['left_for_intents_and_ai_usd'])} = "
              f"{fmt_x(i['implied_multiple_of_intents_revenue'])} Intents revenue; revenue must grow {i['intents_revenue_growth_needed_at_swap_median_x']:.1f}x at the swap median; "
              f"NEAR at the L1 median revenue multiple {fmt_usd(i['near_value_at_l1_median_revenue_multiple_usd'])}; burn and buyback yield {i['buyback_and_burn_yield_pct']:.2f}%")


if __name__ == "__main__":
    main()
