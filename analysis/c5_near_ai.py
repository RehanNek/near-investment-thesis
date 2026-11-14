"""C5. NEAR AI is a working third layer.

NEAR AI's core is NEAR AI Cloud: private, verifiable inference (open-weight models run inside
TEEs; frontier models through an anonymising gateway), an OpenAI-compatible API, and Staking for
Inference (stake NEAR, staking rewards pay for credits). This script measures it four ways:

1. Usage: daily tokens NEAR AI serves as a provider on OpenRouter, by model (third-party,
   independent). NEAR AI Cloud's direct API usage and revenue are not published.
2. Staking for AI (first-party, on-chain): the stake.dao contract (House of Stake staking for
   NEAR AI products): NEAR staked in the "NEAR AI Cloud Credits" farm (100 NEAR x 1 month = $1
   of credits), "NEAR AI Agents" subscriptions (NEAR locked per month), one-off purchases paid in
   NEAR; plus the stake history of the validator it delegates to (nearai.pool.near).
3. Product breadth (first-party): the public NEAR AI Cloud model catalog (models, which are
   TEE-verifiable, who makes them, prices).
4. Developer adoption: GitHub stars and forks of NEAR AI's repositories (snapshot), and Agent
   Market listings (minor).

Outputs (data/derived/): c5_openrouter_tokens_daily.csv, c5_openrouter_tokens_weekly.csv,
c5_ai_staking_summary.csv, c5_ai_staking_positions_weekly.csv, c5_model_catalog.csv,
c5_nearai_pool_history.csv, c5_agents_monthly.csv, c5_summary.csv
"""
from __future__ import annotations

import json

import pandas as pd

from analysis.common import RAW, save

YOCTO = 1e24
FARM_USD_PER_NEAR_MONTH = 1 / 100  # "100 $NEAR x 1 month = $1 credit" (stake.dao price "Staking Farm")


def latest_dir(source: str):
    dirs = sorted(p for p in (RAW / source).iterdir() if p.is_dir())
    if not dirs:
        raise SystemExit(f"No {source} snapshot; run the matching fetcher.")
    return dirs[-1]


def j(path):
    return json.loads(path.read_text())


def openrouter() -> tuple[pd.DataFrame, pd.DataFrame]:
    chart = j(latest_dir("openrouter") / "near_ai_tokens_daily.json")
    d = pd.DataFrame([{"date": r["x"][:10], **r["ys"]} for r in chart]).fillna(0.0)
    d["date"] = pd.to_datetime(d.date)
    models = [c for c in d.columns if c != "date"]
    d["total_tokens"] = d[models].sum(axis=1)
    w = d.set_index("date")[models + ["total_tokens"]].resample("W-SUN").sum()
    w["days"] = d.set_index("date").total_tokens.resample("W-SUN").count()
    w = w.reset_index().rename(columns={"date": "week_ending"})
    w["complete_week"] = w.days == 7
    return d, w


def staking():
    D = latest_dir("nearai")
    products = {p["product_id"]: p["name"] for p in j(D / "stake_dao_products.json")}
    farm = pd.DataFrame(j(D / "stake_dao_farm_positions.json"))
    farm["near"] = farm.staked_near_amount.astype(float) / YOCTO
    farm["created"] = pd.to_datetime(farm.created_ns.astype("int64"), unit="ns")
    active = farm[farm.status == "Active"].sort_values("near", ascending=False)
    locks = pd.DataFrame(j(D / "stake_dao_locks.json"))
    locks["near"] = locks.amount_near.astype(float) / YOCTO
    active_locks = locks[locks.status == "Active"]
    purchases = pd.DataFrame(j(D / "stake_dao_purchases.json"))
    paid = purchases.amount_paid.astype(float).sum() / YOCTO if len(purchases) else 0.0
    validators = j(D / "stake_dao_validators.json")
    total_staked = sum(int(v["total_staked_balance"]) for v in validators) / YOCTO

    rows = [
        ("stake.dao total staked with validators (NEAR)", total_staked),
        ("NEAR AI Cloud Credits farm: NEAR staked (active)", active.near.sum()),
        ("NEAR AI Cloud Credits farm: active stakers", active.account_id.nunique()),
        ("NEAR AI Cloud Credits farm: positions ever opened", len(farm)),
        ("NEAR AI Cloud Credits farm: median active stake (NEAR)", active.near.median()),
        ("NEAR AI Cloud Credits farm: largest staker share (%)", 100 * active.near.iloc[0] / active.near.sum()),
        ("NEAR AI Cloud Credits farm: top-10 stakers share (%)", 100 * active.near.head(10).sum() / active.near.sum()),
        ("NEAR AI Cloud credits funded per month (USD, at 100 NEAR-month = $1)", active.near.sum() * FARM_USD_PER_NEAR_MONTH),
        ("NEAR AI Agents subscriptions: accounts ever subscribed", locks.account_id.nunique()),
        ("NEAR AI Agents subscriptions: active locks", len(active_locks)),
        ("NEAR AI Agents subscriptions: NEAR in active locks", active_locks.near.sum()),
        ("One-off credit purchases paid in NEAR: count", len(purchases)),
        ("One-off credit purchases paid in NEAR: total NEAR", paid),
        ("stake.dao registered accounts", len(j(D / "stake_dao_accounts.json"))),
    ]
    summary = pd.DataFrame(rows, columns=["metric", "value"])
    summary["source"] = "stake.dao contract views via NEAR RPC (" + D.name + ")"
    farm["week_ending"] = farm.created.dt.to_period("W-SUN").dt.end_time.dt.normalize()
    weekly = farm.groupby("week_ending").agg(positions_opened=("account_id", "size"),
                                             accounts=("account_id", "nunique")).reset_index()
    weekly["cumulative_positions"] = weekly.positions_opened.cumsum()
    return summary, weekly, products


def catalog() -> pd.DataFrame:
    m = j(latest_dir("nearai") / "cloud_v1_model_list.json")
    models = m if isinstance(m, list) else (m.get("models") or m.get("data"))
    price = lambda p: p["amount"] / 10 ** p["scale"] * 1e6  # USD per million tokens
    return pd.DataFrame([{
        "model_id": x["modelId"], "owned_by": x["metadata"].get("ownedBy"),
        "provider_type": x["metadata"].get("providerType"),
        "verifiable_tee": bool(x["metadata"].get("verifiable")),
        "input_usd_per_m_tokens": price(x["inputCostPerToken"]), "output_usd_per_m_tokens": price(x["outputCostPerToken"]),
    } for x in models]).sort_values(["verifiable_tee", "owned_by"], ascending=[False, True])


def openrouter_models() -> dict:
    """Per model NEAR AI serves: daily totals across all providers and NEAR AI's listed price."""
    D = latest_dir("openrouter")
    out = {}
    for f in sorted(D.glob("model_*_chart.json")):
        chart = pd.DataFrame(j(f))
        eps = j(f.with_name(f.name.replace("_chart.json", "_endpoints.json")))
        near = [e for e in eps if (e.get("provider_name") or "").lower().startswith("near")]
        if chart.empty or not near:
            continue
        chart = chart[chart.variant == "standard"] if "variant" in chart else chart
        chart["date"] = pd.to_datetime(chart.date.str[:10])
        g = chart.groupby(["date", "model_permaslug"])[["total_prompt_tokens", "total_completion_tokens"]].sum().reset_index()
        g["model_total_tokens"] = g.total_prompt_tokens + g.total_completion_tokens
        g["prompt_share"] = g.total_prompt_tokens / g.model_total_tokens
        p = near[0]["pricing"]
        out[g.model_permaslug.iloc[0]] = {"chart": g, "in_usd_per_token": float(p["prompt"]), "out_usd_per_token": float(p["completion"]),
                                          "providers": len(eps)}
    return out


def market_share_and_revenue(daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """NEAR AI's share of each model's OpenRouter traffic, and revenue at NEAR AI's OpenRouter prices.

    Revenue uses each model's actual prompt/completion split on OpenRouter for that day (all providers;
    the model-level split stands in for NEAR AI's own split). Before the ~30 days the model pages
    cover, the model's average split is used. An estimate of gross revenue, not a reported figure.
    """
    models = openrouter_models()
    shares, rev = [], []
    for slug, m in models.items():
        if slug not in daily.columns:
            continue
        c = m["chart"].set_index("date")
        avg_prompt = c.prompt_share.mean()
        for _, r in daily[["date", slug]].iterrows():
            tok = r[slug]
            ps = c.prompt_share.get(r.date, avg_prompt)
            usd = tok * (ps * m["in_usd_per_token"] + (1 - ps) * m["out_usd_per_token"])
            rev.append({"date": r.date, "model": slug, "near_ai_tokens": tok, "prompt_share": ps, "est_revenue_usd": usd})
            if r.date in c.index:
                total = c.model_total_tokens[r.date]
                shares.append({"date": r.date, "model": slug, "near_ai_tokens": tok, "model_total_tokens": total,
                               "near_ai_share_pct": 100 * tok / total if total else None, "providers": m["providers"]})
    share = pd.DataFrame(shares)
    rev = pd.DataFrame(rev)
    weekly = rev.set_index("date").groupby(pd.Grouper(freq="W-SUN")).agg(
        near_ai_tokens=("near_ai_tokens", "sum"), est_revenue_usd=("est_revenue_usd", "sum")).reset_index()
    weekly = weekly.rename(columns={"date": "week_ending"})
    monthly = rev.assign(month=pd.to_datetime(rev.date).dt.to_period("M").astype(str)).groupby("month").agg(
        near_ai_tokens=("near_ai_tokens", "sum"), est_revenue_usd=("est_revenue_usd", "sum"),
        days=("date", "nunique")).reset_index()
    monthly["complete_month"] = monthly.days == pd.PeriodIndex(monthly.month, freq="M").days_in_month
    return share, weekly, monthly


def pool_history() -> pd.DataFrame:
    h = pd.read_csv(RAW / "rpc" / "nearai_pool_history.csv")
    h = h[h.total_staked_near.notna()][["date", "total_staked_near", "delegators"]]
    snap = j(sorted((RAW / "rpc").glob("snapshot_*.json"))[-1]).get("nearai_pool", {})
    now = pd.DataFrame([{"date": sorted((RAW / "rpc").glob("snapshot_*.json"))[-1].stem[-10:],
                         "total_staked_near": snap.get("total_staked_near"), "delegators": snap.get("delegators")}])
    return pd.concat([h, now], ignore_index=True)


def agents_monthly() -> pd.DataFrame:
    files = sorted((RAW / "agent_market").glob("agents_*.json"))
    a = pd.DataFrame(j(files[-1]))
    a["month"] = pd.to_datetime(a.created_at, utc=True).dt.tz_localize(None).dt.to_period("M").astype(str)
    m = a.groupby("month").agg(agents_listed=("agent_id", "size")).reset_index()
    m["cumulative_agents_listed"] = m.agents_listed.cumsum()
    return m


def main() -> None:
    daily, weekly = openrouter()
    save(daily, "c5_openrouter_tokens_daily")
    save(weekly, "c5_openrouter_tokens_weekly")
    stake_summary, positions_weekly, _ = staking()
    save(stake_summary, "c5_ai_staking_summary")
    save(positions_weekly, "c5_ai_staking_positions_weekly")
    cat = catalog()
    save(cat, "c5_model_catalog")
    share, rev, rev_m = market_share_and_revenue(daily)
    save(share, "c5_openrouter_share_daily")
    save(rev, "c5_openrouter_revenue_estimate_weekly")
    save(rev_m, "c5_openrouter_revenue_estimate_monthly")
    print("Estimated OpenRouter revenue at NEAR AI's OpenRouter prices, by week (USD):",
          {str(r.week_ending.date()): f"{r.est_revenue_usd:,.0f}" for r in rev.itertuples()})
    if not share.empty:
        last7 = share[share.date > share.date.max() - pd.Timedelta(days=7)]
        g = last7.groupby("model")[["near_ai_tokens", "model_total_tokens"]].sum()
        g["share_pct"] = 100 * g.near_ai_tokens / g.model_total_tokens
        print("NEAR AI share of each model's OpenRouter traffic, last 7 days:", g.share_pct.round(1).to_dict())
        first7 = share[share.date < share.date.min() + pd.Timedelta(days=7)]
        g0 = first7.groupby("model")[["near_ai_tokens", "model_total_tokens"]].sum()
        print("  first 7 days covered:", (100 * g0.near_ai_tokens / g0.model_total_tokens).round(1).to_dict())
    pool = pool_history()
    save(pool, "c5_nearai_pool_history")
    act_path = RAW / "bigquery" / "nearai_staking_activity_daily.csv"
    if act_path.exists():
        act = pd.read_csv(act_path, parse_dates=["block_date"])
        wk = act.set_index("block_date").resample("W-SUN").agg(
            function_calls=("function_calls", "sum"), max_daily_calling_accounts=("calling_accounts", "max")).reset_index()
        save(wk.rename(columns={"block_date": "week_ending"}), "c5_ai_staking_activity_weekly")
    save(agents_monthly(), "c5_agents_monthly")

    repos = j(sorted((RAW / "github").glob("nearai_repos_*.json"))[-1])
    full = weekly[weekly.complete_week]
    summary = pd.DataFrame([
        ("OpenRouter tokens, first complete week (B)", full.total_tokens.iloc[0] / 1e9, f"week ending {full.week_ending.iloc[0].date()}"),
        ("OpenRouter tokens, last complete week (B)", full.total_tokens.iloc[-1] / 1e9, f"week ending {full.week_ending.iloc[-1].date()}"),
        ("OpenRouter tokens, peak complete week (B)", full.total_tokens.max() / 1e9, f"week ending {full.loc[full.total_tokens.idxmax(), 'week_ending'].date()}"),
        ("OpenRouter models served by NEAR AI", len([c for c in daily.columns if c not in ('date', 'total_tokens')]), "openrouter.ai/provider/near-ai"),
        ("NEAR AI Cloud models in catalog", len(cat), "cloud-api.near.ai/v1/model/list"),
        ("  of which TEE-verifiable (private inference)", int(cat.verifiable_tee.sum()), "cloud-api.near.ai/v1/model/list"),
        ("IronClaw GitHub stars", repos[0]["stargazers_count"] if repos else None, "github.com/nearai/ironclaw (snapshot)"),
    ] + [(r.metric, r.value, "stake.dao via NEAR RPC") for r in stake_summary.itertuples()],
        columns=["metric", "value", "note"])
    save(summary, "c5_summary")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
    print("\nWeekly OpenRouter tokens (B):", {str(r.week_ending.date()): round(r.total_tokens / 1e9, 1) for r in weekly.itertuples()})
    print("nearai.pool.near stake:", pool.to_dict("records"))


if __name__ == "__main__":
    main()
