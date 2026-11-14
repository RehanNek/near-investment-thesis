"""Loaders for the raw data in data/raw/, returning tidy pandas DataFrames.

Every analysis script reads through these functions, so each number in the thesis traces
back to one file in data/raw/ (see data/raw/_manifest.json for when it was fetched).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"

L1_BURN_SHARE_DEFAULT = 0.70  # before HSP-027: 70% of gas burned, 30% to the called contract (revenue.near.org FAQ)


def gas_burn_switch() -> tuple[str | None, float]:
    """(first day all L1 gas was burned, share burned before that).

    HSP-027 removed the 30% gas rebate to called contracts. The day it took effect comes from the
    archival protocol-config history (data/raw/rpc/protocol_changes.json, fetch/protocol_history.py).
    Returns (None, 0.70) if that file hasn't been fetched.
    """
    p = RAW / "rpc" / "protocol_changes.json"
    if p.exists():
        for c in json.loads(p.read_text())["changes"]:
            if c["parameter"] == "burnt_gas_reward" and c["to"][0] == 0:
                return c["first_day_after"], 1 - c["from"][0] / c["from"][1]
    return None, L1_BURN_SHARE_DEFAULT


def l1_burn_share(dates: pd.Series) -> pd.Series:
    """Share of L1 gas fees that was burned on each date."""
    switch, before = gas_burn_switch()
    share = pd.Series(before, index=dates.index)
    if switch:
        share[pd.to_datetime(dates) >= pd.Timestamp(switch)] = 1.0
    return share


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(df: pd.DataFrame, name: str) -> Path:
    DERIVED.mkdir(parents=True, exist_ok=True)
    path = DERIVED / f"{name}.csv"
    df.to_csv(path, index=False, float_format="%.6g")
    return path


# ---------- NEAR Revenue Tracker (first-party) ----------

def tracker_dir() -> Path:
    dirs = sorted(p for p in (RAW / "revenue_tracker").iterdir() if p.is_dir())
    if not dirs:
        raise SystemExit("No revenue tracker snapshot; run `python -m fetch.revenue_tracker`.")
    return dirs[-1]


def tracker(series: str) -> pd.DataFrame:
    return pd.DataFrame(_json(tracker_dir() / f"{series}.json"))


def intents_revenue_monthly() -> pd.DataFrame:
    """NEAR's net Intents revenue (after partner payouts), monthly, USD and NEAR. From Aug 2025."""
    df = tracker("revenueSeries")
    df["month"] = pd.to_datetime(df.period_month).dt.to_period("M")
    return df[["month", "revenue_usd", "revenue_near"]].rename(
        columns={"revenue_usd": "intents_revenue_usd", "revenue_near": "intents_revenue_near"})


def intents_fees_daily() -> pd.DataFrame:
    """Gross NEAR Intents fees per day (USD and NEAR). From May 2025."""
    df = tracker("totalFeesSeries")
    df["date"] = pd.to_datetime(df.date_at)
    return df[["date", "fees_usd", "total_fees_near"]].rename(
        columns={"fees_usd": "intents_gross_fees_usd", "total_fees_near": "intents_gross_fees_near"})


def intents_volume_daily() -> pd.DataFrame:
    df = tracker("intentVolumeSeries")
    df["date"] = pd.to_datetime(df.date_at)
    return df[["date", "volume_usd"]].rename(columns={"volume_usd": "intents_volume_usd"})


def tracker_revenue_pct_of_emissions_monthly() -> pd.DataFrame:
    """The tracker's own monthly 'revenue as % of emissions' (Intents revenue only, no L1 burn)."""
    df = tracker("emissionsMonthly")
    df["month"] = pd.to_datetime(df.date).dt.to_period("M")
    return df[["month", "value"]].rename(columns={"value": "tracker_revenue_pct_of_emissions"})


# ---------- BigQuery (track prompt) ----------

def bq(name: str, **kw) -> pd.DataFrame:
    path = RAW / "bigquery" / f"{name}.csv"
    if not path.exists():
        raise SystemExit(f"Missing {path}; run `python -m fetch.bigquery {name}`.")
    return pd.read_csv(path, **kw)


def supply_flows_daily() -> pd.DataFrame:
    df = bq("supply_flows_daily", parse_dates=["block_date"]).rename(columns={"block_date": "date"})
    return df[["date", "burned_near", "minted_near", "mint_blocks"]]


def l1_daily() -> pd.DataFrame:
    df = bq("l1_activity")
    df = df[df.level == "daily"].copy()
    df["date"] = pd.to_datetime(df.block_date)
    return df[["date", "transactions", "signers", "tx_to_intents", "signers_to_intents", "tx_conversion_burnt_near"]]


def revenue_wallet_balances() -> pd.DataFrame:
    df = bq("revenue_wallet_balances", parse_dates=["epoch_date"])
    return df.rename(columns={"epoch_date": "date"})


# ---------- Prices (third-party, cross-checked) ----------

def near_price_daily() -> pd.DataFrame:
    """Daily NEAR/USD. Primary: NearBlocks (covers every day since 2020). Cross-check: CoinGecko."""
    nb = pd.DataFrame(_json(RAW / "nearblocks" / "charts.json"))
    nb["date"] = pd.to_datetime(nb.date.str[:10])
    nb["near_usd"] = nb.near_price.astype(float)
    out = nb[["date", "near_usd"]]
    out = out[out.near_usd > 0]
    return out


def coingecko_price_daily() -> pd.DataFrame:
    cg = _json(RAW / "coingecko" / "near_market_chart_365d.json")
    df = pd.DataFrame(cg["prices"], columns=["ms", "coingecko_usd"])
    df["date"] = pd.to_datetime(df.ms, unit="ms").dt.normalize()
    return df.groupby("date", as_index=False).coingecko_usd.last()


# ---------- DefiLlama (third-party cross-check) ----------

def defillama_daily(name: str, col: str) -> pd.DataFrame:
    d = _json(RAW / "defillama" / f"{name}.json")
    df = pd.DataFrame(d["totalDataChart"], columns=["ts", col])
    df["date"] = pd.to_datetime(df.ts, unit="s")
    return df[["date", col]]


def monthly(df: pd.DataFrame, date_col: str = "date") -> pd.Series:
    return df[date_col].dt.to_period("M")
