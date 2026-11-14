"""Build every chart, the dashboard and the headline numbers from data/derived/.

    make charts     (runs `make analysis` first; no keys, a few seconds)

Writes:
  site/index.html                     the dashboard (open it in a browser; no server needed)
  site/charts/<id>.svg                each chart as a standalone image, for THESIS.md
  THESIS.md                           the written thesis, from viz/thesis_template.md (see viz/thesis.py)
  METHODS.md                          methods, scenario detail and sources, from viz/methods_template.md
  data/derived/headline_numbers.json  every number quoted in the text

No number is typed by hand. Each sentence is computed from data/derived/ (built by analysis/) or
data/raw/; the few dated events come from data (the inflation cut, the start of AI staking), from a
fetched source (DefiLlama's methodology text for the buyback start) or from config.yaml (HSP-029).
"""
from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from analysis.common import gas_burn_switch, intents_volume_daily, supply_flows_daily
from viz import svg, thesis
from viz.svg import Event, Mark, Ref, Series, as_date, compact, fmt

ROOT = Path(__file__).resolve().parents[1]
DER, RAW, SITE = ROOT / "data" / "derived", ROOT / "data" / "raw", ROOT / "site"
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
MAN = json.loads((RAW / "_manifest.json").read_text())
FACTS = yaml.safe_load((ROOT / "data" / "manual" / "facts.yaml").read_text())
N: dict = {}  # headline numbers -> data/derived/headline_numbers.json


# ---------- helpers ----------

def csv(name: str) -> pd.DataFrame:
    return pd.read_csv(DER / f"{name}.csv")


def done(df: pd.DataFrame) -> pd.DataFrame:
    """Complete months only."""
    return df[~df.partial_month.astype(bool)].reset_index(drop=True)


def ml(m) -> str:
    d = as_date(m)
    return f"{svg.MON[d.month - 1]} {d.year}"


def dl(d) -> str:
    d = as_date(d)
    return f"{svg.MON[d.month - 1]} {d.day}, {d.year}"


def ql(q: str) -> str:
    return q.replace("Q", " Q")


def usd(v, digits=1) -> str:
    return fmt(v, "usd", digits)


def pct(v, digits=1) -> str:
    return fmt(v, "pct", digits)


def e(s) -> str:
    return html.escape(str(s))


def asof(key: str) -> str:
    return MAN[key]["fetched_at"][:10]


def protocol_change(param: str) -> dict | None:
    """A dated change in NEAR's protocol config (fetch/protocol_history.py), or None if not fetched."""
    p = RAW / "rpc" / "protocol_changes.json"
    if not p.exists():
        return None
    return next((c for c in json.loads(p.read_text())["changes"] if c["parameter"] == param), None)


def l1_note() -> str:
    switch, before = gas_burn_switch()
    if switch:
        return (f"L1 side: NEAR burned by gas fees, valued at the daily price. Gross L1 fees = burn ÷ {before:g} before "
                f"{dl(switch)} (when {100 * (1 - before):g}% of gas went to the called contract) and = burn after, when all "
                "gas is burned.")
    return f"L1 side: NEAR burned by gas fees, valued at the daily price. Gross L1 fees = burn ÷ {before:g}."


def month_volume() -> pd.DataFrame:
    v = intents_volume_daily()
    v["month"] = v.date.dt.to_period("M").astype(str)
    return v.groupby("month", as_index=False).intents_volume_usd.sum()


def direction(latest: float, earlier: float) -> str:
    if not (svg.isnum(latest) and svg.isnum(earlier)):
        return "–"
    if earlier == 0:
        return "↑ rising" if latest > 0 else "→ flat"
    ch = latest / earlier - 1
    return "↑ rising" if ch > 0.05 else "↓ falling" if ch < -0.05 else "→ flat"


BQ_THROUGH = pd.read_csv(RAW / "bigquery" / "blocks_daily.csv").block_date.max()
DL_METHOD = json.loads((RAW / "defillama" / "near_intents_revenue.json").read_text())
SRC = {
    "tracker": ("revenue.near.org", MAN["revenue_tracker"]["url"], f"fetched {asof('revenue_tracker')}"),
    "bq": (f"NEAR BigQuery public dataset ({MAN['bigquery']['dataset']})", None, f"data through {BQ_THROUGH}"),
    "explorer": ("NEAR Intents Explorer API", MAN["explorer"]["endpoint"], None),
    "defillama": ("DefiLlama", MAN["defillama"]["base"], f"fetched {asof('defillama')}"),
    "dl_method": ("DefiLlama NEAR Intents methodology", DL_METHOD.get("methodologyURL"), f"fetched {asof('defillama')}"),
    "nearblocks": ("NearBlocks (NEAR price)", MAN["nearblocks"]["url"], f"fetched {asof('nearblocks')}"),
    "openrouter": ("OpenRouter, NEAR AI provider page", MAN["openrouter"]["url"], f"fetched {asof('openrouter')}"),
    "stakedao": ("stake.dao contract views via NEAR RPC", None, f"fetched {asof('nearai')}"),
    "cloud": ("NEAR AI Cloud model list", MAN["nearai"]["cloud"] + "/v1/model/list", f"fetched {asof('nearai')}"),
    "rpc": ("NEAR archival RPC (validator stake)", None, f"fetched {asof('rpc')}"),
    "github": ("GitHub, nearai org", f"https://github.com/{MAN['github_repos']['org']}", f"fetched {asof('github_repos')}"),
    "config": ("config.yaml (scenario inputs)", None, None),
    "hsp": ("HSP-029 vote coverage (Crypto Briefing)", CFG["inflation"]["hsp_029"].get("source"), None),
    "protocol": ("NEAR archival RPC (protocol config history)", None,
                 f"fetched {asof('protocol_history')}" if "protocol_history" in MAN else "not fetched yet"),
}


@dataclass
class Card:
    id: str
    title: str
    sentence: str  # the detailed version, used as evidence in METHODS.md
    chart: svg.Chart | None = None
    table: str = ""
    sources: list = field(default_factory=list)
    code: list = field(default_factory=list)
    note: str = ""
    tiles: list = field(default_factory=list)
    badge: str = ""
    table_open: bool = False  # show the table on the card instead of behind "Table"
    plain: str = ""  # one plain sentence on what the chart shows (the dashboard)
    api: list = field(default_factory=list)  # keys into API: the requests behind the chart, besides any SQL in `code`
    claim: str = ""  # which claim the chart supports
    memo: str = ""  # a short caption for THESIS.md, where `sentence` is too long


@dataclass
class Claim:
    id: str
    title: str
    cards: list
    evidence: list = field(default_factory=list)  # evidence for, one sentence each
    against: list = field(default_factory=list)  # evidence against, one sentence each
    change: str = ""  # the result that would change our mind
    today: str = ""  # where that measure stands now
    scope: str = ""  # what the data covers, when it's narrower than the claim


# The requests behind each chart that doesn't come from SQL (the SQL is shown from queries/*.sql).
API = {
    "tracker": ("revenue.near.org", "GET https://revenue.near.org/  (the page embeds its data; fetch/revenue_tracker.py "
                "extracts the monthly revenue series and the daily fees-and-volume series)"),
    "dl_volume": ("DefiLlama", "GET https://api.llama.fi/overview/dexs   (daily volume per protocol: near-intents, "
                  "thorchain-dex,\n                                        chainflip-amm, maya-protocol, and the total)\n"
                  "GET https://api.llama.fi/overview/bridge-aggregators"),
    "explorer": ("NEAR Intents Explorer API", "GET https://explorer.near-intents.org/api/v0/transactions\n"
                 "    ?statuses=SUCCESS&numberOfTransactions=1000&direction=next\n"
                 "    &lastDepositAddress=…&lastDepositMemo=…        (cursor; Authorization: Bearer <JWT>)\n"
                 "    &startTimestampUnix=…&endTimestampUnix=…       (time-window refill of skipped ranges)"),
    "openrouter": ("OpenRouter", "GET https://openrouter.ai/provider/near-ai            (tokens per model per day)\n"
                   "GET https://openrouter.ai/api/v1/models/<model>/endpoints   (NEAR AI's price per token)"),
    "pool": ("NEAR RPC", "POST https://archival-rpc.mainnet.near.org\n"
             '  {"method": "query", "params": {"request_type": "call_function", "account_id": "nearai.pool.near",\n'
             '   "method_name": "get_total_staked_balance", "block_id": <height>}}'),
    "stakedao": ("NEAR RPC, stake.dao views", "POST https://free.rpc.fastnear.com\n"
                 '  {"method": "query", "params": {"request_type": "call_function", "account_id": "stake.dao",\n'
                 '   "method_name": "get_products" | "get_locks" | "get_subscriptions", "finality": "final"}}'),
    "protocol": ("NEAR archival RPC", "POST https://archival-rpc.mainnet.near.org\n"
                 '  {"method": "EXPERIMENTAL_protocol_config", "params": {"block_id": <first block of the day>}}\n'
                 "  (bisected by day to date each change in max_inflation_rate and burnt_gas_reward)"),
    "nearblocks": ("NearBlocks", "GET https://api.nearblocks.io/v1/charts   (daily NEAR price)"),
    "config": ("config.yaml", "Scenario inputs: issuance paths, growth window, half-life (no request)"),
}


def table(headers, rows) -> str:
    th = "".join(f"<th>{e(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def col(df, name, kind, digits=1):
    return [fmt(v, kind, digits) for v in df[name]]


# ---------- front page: follow the money ----------

def money_flow(c1, c6m, wallets, c2, vol_m) -> Card:
    """Where each layer's money went in the latest month with complete data for all three layers."""
    ai_m = csv("c5_openrouter_revenue_estimate_monthly")
    ok = set(done(c1).month) & set(done(c6m).month) & set(ai_m[ai_m.complete_month.astype(bool)].month)
    M = max(ok)
    r1_, r6 = c1.set_index("month").loc[M], c6m.set_index("month").loc[M]
    ra = ai_m.set_index("month").loc[M]
    vol = vol_m.set_index("month").intents_volume_usd[M]
    fees, rev, rev_near = r1_.intents_gross_fees_usd, r1_.intents_revenue_usd, r1_.intents_revenue_near
    l1_fees, burn_near = r1_.l1_gross_fees_usd, r1_.l1_burn_near
    burned_share = r1_.l1_burn_usd / l1_fees
    tx = c2.set_index("month").tx_per_day[M]
    minted, captured, ratio = r6.minted_near, r6.captured_near, r6.capture_ratio_pct
    ai_added, ai_staked, ratio_ai = r6.ai_stake_added_near, r6.ai_staked_month_end_near, r6.capture_ratio_incl_ai_stake_pct
    ai_tokens, ai_sales = ra.near_ai_tokens, ra.est_revenue_usd
    w = wallets.set_index("month")["buybacks.multisignature.near"]
    bb_added = w.get(M, float("nan")) - w.get(str(pd.Period(M, "M") - 1), 0.0)
    rate, share = 100 * fees / vol, 100 * rev / fees
    MM = ml(M)
    N["money_flow"] = dict(month=M, intents_volume_usd=vol, intents_fees_usd=fees, fee_rate_pct=rate,
                           near_share_usd=rev, near_share_pct_of_fees=share, near_share_near=rev_near,
                           l1_gas_fees_usd=l1_fees, l1_burn_near=burn_near, l1_tx_per_day=tx,
                           captured_near=captured, minted_near=minted, capture_ratio_pct=ratio,
                           ai_tokens=ai_tokens, ai_est_sales_usd=ai_sales, ai_staked_month_end_near=ai_staked,
                           ai_stake_added_near=ai_added, capture_ratio_incl_ai_stake_pct=ratio_ai,
                           buyback_wallet_added_near=bb_added)

    x, wd = [4, 188, 372, 556], [124, 124, 124, 160]
    rows_y, h = [34, 150, 266], 80
    cy = [y + h / 2 for y in rows_y]
    b = []
    for y, (t, tag) in zip(rows_y, [("NEAR Intents", "cross-chain swaps"), ("NEAR L1", "the base chain"),
                                    ("NEAR AI", "private AI")]):
        # one text element, so the tagline follows the name whatever font the viewer has
        b.append(f'<text x="{x[0]:.1f}" y="{y - 12:.1f}" class="c-head">{svg.esc(t)}'
                 f'<tspan class="c-sm" font-weight="400" dx="8">{svg.esc(tag)}</tspan></text>')
    b.append(svg.text(x[3], rows_y[0] - 12, "What reached the token", "c-head"))
    r_i, r_l, r_a = rows_y
    b.append(svg.node(x[0], r_i, wd[0], h, "intents", usd(vol, 2), ["swap volume"]))
    b.append(svg.node(x[1], r_i, wd[1], h, "intents", usd(fees), ["fees paid by users"]))
    b.append(svg.node(x[2], r_i, wd[2], h, "intents", usd(rev), ["NEAR's share"]))
    b.append(svg.node(x[0], r_l, wd[0], h, "l1", compact(tx), ["L1 transactions", "a day"]))
    b.append(svg.node(x[1], r_l, wd[1], h, "l1", usd(l1_fees), ["L1 gas fees"]))
    b.append(svg.node(x[2], r_l, wd[2], h, "l1", compact(burn_near), ["NEAR burned"]))
    b.append(svg.node(x[0], r_a, wd[0], h, "ai", compact(ai_tokens), ["AI tokens served", "on OpenRouter"]))
    b.append(svg.node(x[1], r_a, wd[1], h, "ai", usd(ai_sales, 0), ["inference sales", "(est.), to NEAR AI"]))
    b.append(svg.node(x[2], r_a, wd[2], h, "ai", compact(ai_staked), ["NEAR staked for", "AI credits"]))
    # Right column: what reached the token
    bx, by, bw, bh = x[3], r_i, wd[3], r_a + h - r_i
    b.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="8" class="c-node"/>')
    for k, c in enumerate(["intents", "l1", "ai"]):
        b.append(f'<rect x="{bx + 12 + k * 28}" y="{by + 12}" width="24" height="4" rx="2" class="f-{c}"/>')
    tx_ = bx + 12
    b += [svg.text(tx_, cy[0] + 4, compact(captured), "c-big"),
          svg.text(tx_, cy[0] + 24, "NEAR burned or", "c-lbl"), svg.text(tx_, cy[0] + 39, "bought back", "c-lbl"),
          svg.text(tx_, cy[0] + 59, f"= {ratio:.1f}% of the", "c-sm"),
          svg.text(tx_, cy[0] + 73, f"{compact(minted)} NEAR issued", "c-sm"),
          f'<line x1="{bx + 12}" y1="{r_a - 14}" x2="{bx + bw - 12}" y2="{r_a - 14}" class="c-arrow"/>',
          svg.text(tx_, cy[2] - 6, "+" + compact(ai_added), "c-big"),
          svg.text(tx_, cy[2] + 14, "NEAR newly locked", "c-lbl"), svg.text(tx_, cy[2] + 29, "by AI staking", "c-lbl")]
    b.append(svg.arrow(x[0] + wd[0], cy[0], x[1], [f"{rate:.2f}%", "in fees"]))
    b.append(svg.arrow(x[1] + wd[1], cy[0], x[2], [f"{share:.0f}% kept", "by NEAR"]))
    b.append(svg.arrow(x[2] + wd[2], cy[0], x[3], ["buys", compact(rev_near), "NEAR"]))
    b.append(svg.arrow(x[0] + wd[0], cy[1], x[1], ["gas"]))
    b.append(svg.arrow(x[1] + wd[1], cy[1], x[2], [f"{burned_share:.0%}", "burned"]))
    b.append(svg.arrow(x[2] + wd[2], cy[1], x[3]))
    b.append(svg.arrow(x[0] + wd[0], cy[2], x[1], ["at list", "prices"]))
    b.append(svg.arrow(x[1] + wd[1], cy[2], x[2], ["or pay by", "staking"]))
    b.append(svg.arrow(x[2] + wd[2], cy[2], x[3], ["new", "stake"]))
    title = f"Follow the money: what each layer earned in {MM}, and what reached the token"
    sentence = (f"In {MM}, users paid {usd(fees)} in fees on {usd(vol, 2)} of Intents swaps ({rate:.2f}%). NEAR kept "
                f"{usd(rev)} ({share:.0f}%; the rest went to partner apps and solvers), worth {compact(rev_near)} NEAR, which "
                f"funds buybacks. L1 gas fees burned another {compact(burn_near)} NEAR. Together that is {compact(captured)} "
                f"NEAR, {ratio:.1f}% of the {compact(minted)} NEAR issued in the month. NEAR AI sold an estimated "
                f"{usd(ai_sales, 0)} of inference on OpenRouter; that money goes to NEAR AI, and no published mechanism sends "
                f"it to the token. What reaches the token from NEAR AI is staking: customers staked {compact(ai_added)} more "
                f"NEAR for inference credits, which locks it without removing it.")
    plain = (f"In {MM}, burns and buybacks captured {compact(captured)} NEAR, {ratio:.1f}% of the NEAR issued that month, "
             f"and staking for NEAR AI locked another {compact(ai_added)} NEAR.")
    memo = (f"In {MM}, users paid {usd(fees)} in fees on {usd(vol, 2)} of Intents swaps. NEAR kept {usd(rev)} of that, "
            f"worth {compact(rev_near)} NEAR, which funds buybacks. L1 gas fees burned another {compact(burn_near)} NEAR. "
            f"Together that is {ratio:.1f}% of the {compact(minted)} NEAR issued in the month. NEAR AI's sales, an estimated "
            f"{usd(ai_sales, 0)} on OpenRouter, go to NEAR AI, and no published mechanism sends them to the token. What "
            f"reaches the token from NEAR AI is staking, which locked {compact(ai_added)} more NEAR.")
    chart = svg.Chart("money-flow", "".join(b), r_a + h + 12, title, sentence)
    rows = [("Intents swap volume", usd(vol, 2)), ("Intents fees paid by users", usd(fees, 2)),
            ("Fee rate", pct(rate, 3)), ("NEAR's share of fees (USD)", usd(rev, 2)),
            ("NEAR's share of fees (% of fees)", pct(share)), ("NEAR's share of fees (NEAR)", fmt(rev_near, "near", 2)),
            ("Buyback wallet, change over the month", fmt(bb_added, "near", 2)),
            ("L1 transactions per day (average)", compact(tx, 2)), ("L1 gas fees (USD)", usd(l1_fees, 2)),
            ("NEAR burned by L1 gas fees", fmt(burn_near, "near", 2)),
            ("NEAR AI tokens served on OpenRouter", compact(ai_tokens, 2)),
            ("NEAR AI inference sales on OpenRouter (estimate, list prices)", usd(ai_sales, 0)),
            ("NEAR staked with NEAR AI's validator, month end", fmt(ai_staked, "near", 2)),
            ("NEAR newly staked for NEAR AI (locked)", fmt(ai_added, "near", 2)),
            ("NEAR captured (burn + Intents revenue)", fmt(captured, "near", 2)),
            ("NEAR issued", fmt(minted, "near", 2)), ("Capture ratio", pct(ratio)),
            ("Capture ratio including new AI stake", pct(ratio_ai))]
    return Card("money-flow", title, sentence, chart, table(["Step", MM], rows),
                [SRC["tracker"], SRC["bq"], SRC["nearblocks"], SRC["openrouter"], SRC["rpc"]],
                ["analysis/c1_revenue_mix.py", "analysis/c5_near_ai.py", "analysis/c6_capture.py",
                 "queries/supply_flows_daily.sql", "queries/l1_activity.sql", "queries/revenue_wallet_balances.sql"],
                note="Latest month with complete data for all three layers. NEAR AI sales are an estimate: OpenRouter "
                     "tokens at NEAR AI's list prices. Staked NEAR is locked, not removed, and can be withdrawn.",
                plain=plain, api=["tracker", "openrouter", "pool", "nearblocks"], claim="C1, C5, C6", memo=memo)


# ---------- Part 1 ----------

def c1_claim(c1) -> Claim:
    d = done(c1)
    first_half = d[d.intents_share_net_pct > 50].month.iloc[0]
    t3 = d.tail(3)
    share3 = 100 * t3.intents_revenue_usd.sum() / (t3.intents_revenue_usd.sum() + t3.l1_burn_usd.sum())
    gross3 = 100 * t3.intents_gross_fees_usd.sum() / (t3.intents_gross_fees_usd.sum() + t3.l1_gross_fees_usd.sum())
    y3 = d[d.month.isin([str(pd.Period(m, "M") - 12) for m in t3.month])]
    share3_yago = 100 * y3.intents_revenue_usd.sum() / (y3.intents_revenue_usd.sum() + y3.l1_burn_usd.sum())
    since = d[d.month >= f"{as_date(first_half).year + 1}-01"]
    min_since = since.intents_share_net_pct.min()
    p3 = f"{ml(t3.month.iloc[0])}–{ml(t3.month.iloc[-1])}"
    N["c1"] = dict(intents_share_net_last3_pct=share3, intents_share_gross_last3_pct=gross3,
                   intents_share_net_last3_year_ago_pct=share3_yago, last3=p3, first_month_over_half=first_half,
                   first_month_over_half_pct=float(d[d.month == first_half].intents_share_net_pct.iloc[0]),
                   min_share_since=float(min_since), since=since.month.iloc[0])

    s1 = (f"NEAR's share of Intents fees overtook the L1 fee burn in {ml(first_half)}. Over the last three months "
          f"({p3}), Intents was {share3:.1f}% of the value the protocol kept ({gross3:.1f}% of all fees paid).")
    ch1 = svg.column_chart("c1-revenue", d.month, [Series("L1 fees burned", list(d.l1_burn_usd), "l1"),
                                                   Series("NEAR's share of Intents fees", list(d.intents_revenue_usd), "intents")],
                           kind="usd", gran="month", title="NEAR protocol revenue by source, monthly (USD)", desc=s1)
    t1 = table(["Month", "L1 fees burned", "NEAR's share of Intents fees", "Intents gross fees", "L1 gross fees"],
               zip(map(ml, d.month), col(d, "l1_burn_usd", "usd", 2), col(d, "intents_revenue_usd", "usd", 2),
                   col(d, "intents_gross_fees_usd", "usd", 2), col(d, "l1_gross_fees_usd", "usd", 2)))
    card1 = Card("c1-revenue", "NEAR protocol revenue by source, monthly (USD)", s1, ch1, t1,
                 [SRC["tracker"], SRC["bq"], SRC["nearblocks"]],
                 ["analysis/c1_revenue_mix.py", "queries/supply_flows_daily.sql"],
                 note=l1_note() + " Intents side: NEAR's net revenue after partner payouts. Complete months only.")

    s2 = (f"Since {ml(since.month.iloc[0])}, Intents has been above {min_since:.0f}% of protocol revenue every month.")
    ch2 = svg.line_chart("c1-share", d.month, [Series("Intents share of protocol revenue", list(d.intents_share_net_pct), "intents")],
                         kind="pct", gran="month", title="Intents share of NEAR's protocol revenue, monthly", desc=s2,
                         y_max=100, refs=[Ref(50, "Half")])
    t2 = table(["Month", "Intents share (net)", "Intents share (gross fees)"],
               zip(map(ml, d.month), col(d, "intents_share_net_pct", "pct"), col(d, "intents_share_gross_pct", "pct")))
    card2 = Card("c1-share", "Intents share of NEAR's protocol revenue, monthly", s2, ch2, t2,
                 [SRC["tracker"], SRC["bq"]], ["analysis/c1_revenue_mix.py"],
                 note="Net basis: NEAR's share of Intents fees vs L1 fees burned. The gross basis (all fees paid) is in the table.")

    first, mid = d.iloc[0], d[(d.month >= "2026-04") & (d.month <= "2026-08")]
    p0 = first.l1_burn_usd / first.l1_burn_near
    p1 = mid.l1_burn_usd.sum() / mid.l1_burn_near.sum()
    lst = d.iloc[-1]
    card1.plain = (f"NEAR now earns far more from its share of Intents fees than from L1 gas: {usd(lst.intents_revenue_usd)} "
                   f"against {usd(lst.l1_burn_usd, 0)} in {ml(lst.month)}.")
    always = d[d.month >= first_half].intents_share_net_pct.min() > 50
    card2.plain = (f"Intents has been more than half of NEAR's protocol revenue every month since {ml(first_half)}, and above "
                   f"{min_since:.0f}% every month since {ml(since.month.iloc[0])}." if always else s2)
    for c in (card1, card2):
        c.claim = "C1"
    card1.api, card2.api = ["tracker", "nearblocks"], ["tracker"]
    against = [f"Part of the shift is the L1 shrinking rather than Intents growing: L1 fees burned fell from "
               f"{usd(first.l1_burn_usd, 0)} in {ml(first.month)} to {usd(mid.l1_burn_usd.min(), 0)}–{usd(mid.l1_burn_usd.max(), 0)} "
               f"a month in {ml(mid.month.iloc[0])}–{ml(mid.month.iloc[-1])}, as the largest L1 app left (C2) and the NEAR price "
               f"fell from about ${p0:.2f} to ${p1:.2f}.",
               "L1 gas is cheap by design, so L1 revenue was never large, and a high Intents share is easy to reach."]
    change = "Intents' share of protocol revenue falling back below half."
    today = f"{share3:.0f}% of protocol revenue over {p3}, against {share3_yago:.0f}% a year earlier."
    return Claim("c1", "Most of NEAR's revenue now comes from beyond the L1.", [card1, card2], [s1, s2], against, change,
                 today=today)


def c2_claim(c2, vol_m) -> Claim:
    d = done(c2)
    d["ex_both_pct"] = 100 * d.intents_tx_per_day / (d.intents_tx_per_day + d.other_tx_per_day)
    k_prev = d.kaiching_tx_per_day.shift(1)
    stop = d[(k_prev > 1e6) & (d.kaiching_tx_per_day < 0.1 * k_prev)].month.iloc[0]
    jan = d[d.month == f"{as_date(stop).year}-01"].iloc[0]
    last = d.iloc[-1]
    s1 = (f"L1 transactions fell from {compact(d.tx_per_day.iloc[0])} a day in {ml(d.month.iloc[0])} to "
          f"{compact(last.tx_per_day)} in {ml(last.month)}, mostly as KaiChing and HOT wound down. Transactions to "
          f"intents.near rose from {compact(jan.intents_tx_per_day)} to {compact(last.intents_tx_per_day)} a day over "
          f"{ml(jan.month)}–{ml(last.month)}.")
    ch1 = svg.column_chart("c2-l1-tx", d.month, [
        Series("Transactions to intents.near", list(d.intents_tx_per_day), "intents"),
        Series("Everything else", list(d.other_tx_per_day), "rest"),
        Series("HOT (*.tg)", list(d.hot_tg_tx_per_day), "hot"),
        Series("KaiChing", list(d.kaiching_tx_per_day), "kaiching")],
        kind="count", gran="month", title="NEAR L1 transactions per day, by app (monthly average)", desc=s1,
        events=[Event(as_date(stop), "KaiChing stops")])
    t1 = table(["Month", "All L1", "To intents.near", "KaiChing", "HOT", "Everything else"],
               zip(map(ml, d.month), col(d, "tx_per_day", "count", 2), col(d, "intents_tx_per_day", "count", 2),
                   col(d, "kaiching_tx_per_day", "count", 2), col(d, "hot_tg_tx_per_day", "count", 2),
                   col(d, "other_tx_per_day", "count", 2)))
    card1 = Card("c2-l1-tx", "NEAR L1 transactions per day, by app (monthly average)", s1, ch1, t1, [SRC["bq"]],
                 ["analysis/c2_l1_settlement.py", "queries/l1_activity.sql", "queries/l1_app_split_daily.sql"],
                 note="KaiChing = transactions signed by *.kaiching accounts; HOT = *.tg accounts and hot.tg. Complete months only.")

    s2 = (f"Intents' share of L1 transactions rose from {jan.intents_share_of_l1_tx_pct:.1f}% in {ml(jan.month)} to "
          f"{last.intents_share_of_l1_tx_pct:.1f}% in {ml(last.month)}. Leaving out KaiChing and HOT, it went from "
          f"{jan.ex_both_pct:.1f}% to {last.ex_both_pct:.1f}%.")
    ch2 = svg.line_chart("c2-share", d.month, [
        Series("All L1 transactions", list(d.intents_share_of_l1_tx_pct), "o3"),
        Series("Without KaiChing", list(d.intents_share_ex_kaiching_pct), "o2"),
        Series("Without KaiChing and HOT", list(d.ex_both_pct), "o1")],
        kind="pct", gran="month", title="Intents share of NEAR L1 transactions, monthly", desc=s2)
    t2 = table(["Month", "All L1", "Without KaiChing", "Without KaiChing and HOT"],
               zip(map(ml, d.month), col(d, "intents_share_of_l1_tx_pct", "pct", 2),
                   col(d, "intents_share_ex_kaiching_pct", "pct", 2), col(d, "ex_both_pct", "pct", 2)))
    card2 = Card("c2-share", "Intents share of NEAR L1 transactions, monthly", s2, ch2, t2, [SRC["bq"]],
                 ["analysis/c2_l1_settlement.py", "queries/l1_app_split_daily.sql"])

    # Counterpoint numbers
    dr = csv("c2_drop_mar_apr_2026")
    k = dr[(dr.side == "receiver") & (dr.account_parent == "kaiching")].iloc[0]
    mar, apr = d[d.month == "2026-03"].iloc[0], d[d.month == "2026-04"].iloc[0]
    mar_total, apr_total = mar.tx_per_day * 31, apr.tx_per_day * 30
    k_share, k_drop = 100 * k.tx_2026_03 / mar_total, 100 * -k.change / (mar_total - apr_total)
    pk = d.loc[d.intents_tx_per_day.idxmax()]
    vm = vol_m.set_index("month").intents_volume_usd
    vol_x = vm.get(last.month) / vm.get(pk.month)
    N["c2"] = dict(intents_share_last_pct=last.intents_share_of_l1_tx_pct, intents_share_jan_pct=jan.intents_share_of_l1_tx_pct,
                   ex_both_last_pct=last.ex_both_pct, ex_both_jan_pct=jan.ex_both_pct, last=last.month, jan=jan.month,
                   kaiching_stop=stop, kaiching_share_mar_2026_pct=k_share, kaiching_share_of_april_drop_pct=k_drop,
                   intents_tx_peak_month=pk.month, intents_tx_peak_per_day=pk.intents_tx_per_day,
                   ex_both_at_peak_pct=pk.ex_both_pct, volume_ratio_last_vs_peak=vol_x,
                   intents_share_year_ago_pct=float(d[d.month == str(pd.Period(last.month, "M") - 12)].intents_share_of_l1_tx_pct.iloc[0]))
    card1.plain = (f"L1 transactions fell from {compact(d.tx_per_day.iloc[0])} a day in {ml(d.month.iloc[0])} to "
                   f"{compact(last.tx_per_day)} in {ml(last.month)}, mostly because two consumer apps, KaiChing and HOT, wound down.")
    card2.plain = (f"The share of L1 transactions going to Intents rose from {jan.intents_share_of_l1_tx_pct:.1f}% in "
                   f"{ml(jan.month)} to {last.intents_share_of_l1_tx_pct:.1f}% in {ml(last.month)}.")
    for c in (card1, card2):
        c.claim = "C2"
    against = [f"Most of the rising share is the rest of the L1 shrinking: KaiChing accounts sent {k_share:.0f}% of all L1 "
               f"transactions in March 2026, and their stop caused {k_drop:.0f}% of April's fall.",
               f"Transactions to intents.near were higher in {ml(pk.month)} ({compact(pk.intents_tx_per_day)} a day) than in "
               f"{ml(last.month)} ({compact(last.intents_tx_per_day)}), though Intents volume is {vol_x:.0f}× larger now, so "
               f"transaction counts don't track Intents' growth.",
               f"Leaving out KaiChing and HOT, Intents' share was {pk.ex_both_pct:.1f}% in {ml(pk.month)}, above today's "
               f"{last.ex_both_pct:.1f}%."]
    change = "Intents' share of L1 transactions no longer rising over a 12-month span."
    today = (f"{last.intents_share_of_l1_tx_pct:.1f}% of L1 transactions in {ml(last.month)}, against "
             f"{N['c2']['intents_share_year_ago_pct']:.1f}% a year earlier.")
    return Claim("c2", "The L1 is becoming Intents' settlement layer.", [card1, card2], [s1, s2], against, change,
                 today=today)


# ---------- Part 2 ----------

CHAINS = {"eth": "Ethereum", "tron": "Tron", "zec": "Zcash", "btc": "Bitcoin", "near": "NEAR", "sol": "Solana",
          "arb": "Arbitrum", "bsc": "BNB Chain", "base": "Base", "ltc": "Litecoin", "doge": "Dogecoin", "xrp": "XRP",
          "ton": "TON", "pol": "Polygon", "avax": "Avalanche", "op": "Optimism", "sui": "Sui", "stellar": "Stellar",
          "cardano": "Cardano", "bera": "Berachain", "gnosis": "Gnosis", "aptos": "Aptos", "bch": "Bitcoin Cash",
          "(other)": "All other chains"}


def c3_claim(vol_m) -> Claim:
    dd = csv("c3_daily")
    dd = dd[dd.complete_day.astype(bool)].reset_index(drop=True)
    m3 = csv("c3_monthly")
    mc = m3[m3.complete_month.astype(bool)]
    L = (mc if len(mc) else m3).iloc[-1]
    first_day = dd.date.min()
    vm = vol_m.set_index("month").intents_volume_usd
    oneclick_share = 100 * L.volume_usd / vm.get(L.month)
    preliminary = first_day > "2025-04-15"
    yr = m3[m3.month == str(pd.Period(L.month, "M") - 12)]
    Y = yr.iloc[0] if len(yr) else None
    # months inside the downloaded range that are flagged incomplete (download gaps), not the current month
    holes = [x for x in m3[~m3.complete_month.astype(bool)].month if mc.month.min() < x < mc.month.max()] if len(mc) else []
    note = (f"Covers the 1Click channel only, about {oneclick_share:.0f}% of Intents volume in {ml(L.month)}"
            + (f", from {dl(first_day)}. The full history back to 2025 is still downloading; this section updates "
               "when it finishes." if preliminary else f". The first 1Click swap in the data is on {dl(first_day)}.")
            + (f" Left out because of download gaps: {', '.join(map(ml, holes))}." if holes else ""))

    def was(cur, prev, f):
        """'up from X' / 'down from X' / 'as' a year earlier, worded from the data."""
        if prev is None or not svg.isnum(prev):
            return ""
        word = "up from" if cur > prev * 1.05 else "down from" if cur < prev * 0.95 else "about the same as"
        return f"{word} {f(prev)}"
    refs = csv("c3_referrers_monthly")
    rl = refs[(refs.month == L.month) & (refs.referral != "(none)")].sort_values("volume_usd", ascending=False).iloc[0]
    ch_ = csv("c3_chains_monthly")
    cl = ch_[ch_.month == L.month].copy()
    other = cl[cl.origin_chain == "(other)"]
    cl = pd.concat([cl[cl.origin_chain != "(other)"].sort_values("share_pct", ascending=False), other])
    zec = float(cl[cl.origin_chain == "zec"].share_pct.sum())
    N["c3"] = dict(month=L.month, swaps=L.swaps, volume_usd=L.volume_usd, unique_users=L.unique_users,
                   top10_share_pct=L.top10_users_share_of_volume_pct, referrers=L.active_referrers,
                   origin_chains=L.active_origin_chains, chain_pairs=L.active_chain_pairs,
                   non_near_both_sides_pct=L.non_near_both_sides_share_pct, stable_to_stable_pct=L.stable_to_stable_share_pct,
                   any_stable_pct=L.any_stable_share_pct, oneclick_share_of_intents_pct=oneclick_share,
                   top_referrer=rl.referral, top_referrer_share_pct=rl.share_pct, zcash_origin_share_pct=zec,
                   first_day=first_day, preliminary=bool(preliminary), gap_months=holes,
                   year_earlier=None if Y is None else dict(month=Y.month, unique_users=Y.unique_users,
                                                            referrers=Y.active_referrers, origin_chains=Y.active_origin_chains,
                                                            chain_pairs=Y.active_chain_pairs, volume_usd=Y.volume_usd,
                                                            top10_share_pct=Y.top10_users_share_of_volume_pct,
                                                            stable_to_stable_pct=Y.stable_to_stable_share_pct))

    s1 = (f"In {ml(L.month)}, 1Click handled {compact(L.swaps)} swaps worth {usd(L.volume_usd)} from "
          f"{compact(L.unique_users)} distinct users, through {L.active_referrers:.0f} referrer apps and "
          f"{L.active_chain_pairs:.0f} chain pairs.")
    if Y is not None:
        s1 += (f" A year earlier ({ml(Y.month)}): {compact(Y.unique_users)} users, {Y.active_referrers:.0f} apps and "
               f"{Y.active_chain_pairs:.0f} chain pairs.")
    ch1 = svg.line_chart("c3-volume", dd.date, [Series("Volume", list(dd.volume_usd), "intents")], kind="usd", gran="day",
                         title="NEAR Intents 1Click swap volume per day (USD)", desc=s1,
                         tooltip_extra=[[("Swaps", compact(s))] for s in dd.swaps])
    t1 = table(["Day", "Volume", "Swaps", "Distinct users"],
               zip(map(dl, dd.date), col(dd, "volume_usd", "usd", 2), col(dd, "swaps", "count", 2), col(dd, "unique_users", "count", 2)))
    tiles = [("Distinct users", compact(L.unique_users),
              ml(L.month) + (f"; {compact(Y.unique_users)} a year earlier" if Y is not None else "")),
             ("Referrer apps", f"{L.active_referrers:.0f}",
              f"{Y.active_referrers:.0f} a year earlier" if Y is not None else "apps that sent at least one swap"),
             ("Origin chains / chain pairs", f"{L.active_origin_chains:.0f} / {L.active_chain_pairs:.0f}",
              f"{Y.active_origin_chains:.0f} / {Y.active_chain_pairs:.0f} a year earlier" if Y is not None else ""),
             ("Between two non-NEAR chains", pct(L.non_near_both_sides_share_pct, 0), "share of volume"),
             ("Top 10 users", pct(L.top10_users_share_of_volume_pct, 0), "share of volume"),
             ("Top 100 users", pct(L.top100_users_share_of_volume_pct, 0), "share of volume")]
    card1 = Card("c3-volume", "NEAR Intents 1Click swap volume per day (USD)", s1, ch1, t1, [SRC["explorer"]],
                 ["analysis/c3_intents_breadth.py", "fetch/explorer.py"], note=note, tiles=tiles,
                 badge="Preliminary" if preliminary else "")

    pk = mc.loc[mc.unique_users.idxmax()]
    s2 = (f"{compact(L.unique_users)} distinct users in {ml(L.month)}"
          + (f", {was(L.unique_users, Y.unique_users, compact)} a year earlier" if Y is not None else "")
          + (f"; the peak was {compact(pk.unique_users)} in {ml(pk.month)}." if pk.month != L.month else ", the most in any month."))
    ch2 = svg.column_chart("c3-users", mc.month, [Series("Distinct users", list(mc.unique_users), "intents")], kind="count",
                           gran="month", title="Distinct 1Click users per month", desc=s2,
                           tooltip_extra=[[("Referrer apps", f"{r.active_referrers:.0f}"), ("Origin chains", f"{r.active_origin_chains:.0f}")]
                                          for r in mc.itertuples()])
    t2 = table(["Month", "Distinct users", "Swaps", "Volume", "Referrer apps", "Origin chains", "Chain pairs",
                "Top 10 users' share", "Stablecoin-to-stablecoin share"],
               zip(map(ml, mc.month), col(mc, "unique_users", "count", 2), col(mc, "swaps", "count", 2), col(mc, "volume_usd", "usd", 2),
                   [f"{v:.0f}" for v in mc.active_referrers], [f"{v:.0f}" for v in mc.active_origin_chains],
                   [f"{v:.0f}" for v in mc.active_chain_pairs], col(mc, "top10_users_share_of_volume_pct", "pct"),
                   col(mc, "stable_to_stable_share_pct", "pct")))
    card2 = Card("c3-users", "Distinct 1Click users per month", s2, ch2, t2, [SRC["explorer"]],
                 ["analysis/c3_intents_breadth.py"],
                 note="A user is the first sender address of a swap, or its refund address. Complete months only.",
                 badge="Preliminary" if preliminary else "")

    s3 = (f"{pct(L.non_near_both_sides_share_pct, 0)} of {ml(L.month)} volume moved between two chains other than NEAR. "
          f"Swaps started on {L.active_origin_chains:.0f} chains; the largest was {CHAINS.get(cl.origin_chain.iloc[0], cl.origin_chain.iloc[0])} "
          f"at {cl.share_pct.iloc[0]:.0f}%.")
    rows = [(CHAINS.get(c, c), s) for c, s in zip(cl.origin_chain, cl.share_pct)]
    ch3 = svg.hbar_chart("c3-chains", rows, kind="pct", color="intents",
                         title=f"Where 1Click swaps start: share of volume by origin chain, {ml(L.month)}", desc=s3)
    t3 = table(["Origin chain", "Volume", "Share"], zip([r[0] for r in rows], col(cl, "volume_usd", "usd", 2), col(cl, "share_pct", "pct")))
    card3 = Card("c3-chains", f"Where 1Click swaps start: share of volume by origin chain, {ml(L.month)}", s3, ch3, t3,
                 [SRC["explorer"]], ["analysis/c3_intents_breadth.py"], badge="Preliminary" if preliminary else "")

    p0 = lambda v: f"{v:.0f}%"
    yago = (lambda cur, prev: f" ({was(cur, prev, p0)} a year earlier)") if Y is not None else (lambda cur, prev: "")
    card1.plain = (f"1Click swap volume was {usd(L.volume_usd)} in {ml(L.month)}"
                   + (f", {L.volume_usd / Y.volume_usd:.1f}× its level a year earlier." if Y is not None else "."))
    card2.plain = s2
    top_chain = CHAINS.get(cl.origin_chain.iloc[0], cl.origin_chain.iloc[0])
    card3.plain = (f"Swaps started on {L.active_origin_chains:.0f} chains in {ml(L.month)}; the largest origin was {top_chain} "
                   f"at {cl.share_pct.iloc[0]:.0f}% of volume.")
    for c in (card1, card2, card3):
        c.claim, c.api = "C3", ["explorer"]
    against = [f"Much of the flow is trading: in {ml(L.month)}, {L.stable_to_stable_share_pct:.0f}% of 1Click volume was "
               f"stablecoin-to-stablecoin{yago(L.stable_to_stable_share_pct, Y.stable_to_stable_share_pct if Y is not None else None)} "
               f"and {L.any_stable_share_pct:.0f}% involved a stablecoin.",
               f"A few routes carry a lot of it: one referrer app ({rl.referral}) routed {rl.share_pct:.0f}% of volume, the top 10 "
               f"users {L.top10_users_share_of_volume_pct:.0f}%"
               f"{yago(L.top10_users_share_of_volume_pct, Y.top10_users_share_of_volume_pct if Y is not None else None)}, "
               f"and Zcash was {zec:.0f}% of origin volume."]
    if pk.month != L.month:
        against.append(f"Distinct users have eased since their peak: {compact(pk.unique_users)} in {ml(pk.month)}, "
                       f"{compact(L.unique_users)} in {ml(L.month)}.")
    change = "1Click volume or users falling over a 12-month span, or the top 10 users' share of volume rising above half."
    today = (f"{usd(L.volume_usd)} of 1Click volume and {compact(L.unique_users)} users in {ml(L.month)}"
             + (f", against {usd(Y.volume_usd)} and {compact(Y.unique_users)} a year earlier" if Y is not None else "")
             + f"; top 10 users at {L.top10_users_share_of_volume_pct:.0f}% of volume.")
    cl3 = Claim("c3", "Intents is a real, broad-based growth engine.", [card1, card2, card3], [s1, s3], against, change,
                today=today)
    cl3.scope = note
    return cl3


def c4_claim(c4) -> Claim:
    d = done(c4)
    last = d.iloc[-1]
    pk = d.loc[d.intents_share_of_peers_pct.idxmax()]
    base_m = str(pd.Period(last.month, "M") - 12)
    yago = d[d.month == base_m].iloc[0]
    s1 = (f"Among native cross-chain swap venues tracked by DefiLlama, Intents' share of volume rose from "
          f"{yago.intents_share_of_peers_pct:.0f}% in {ml(base_m)} to {last.intents_share_of_peers_pct:.0f}% in {ml(last.month)}, "
          f"after peaking at {pk.intents_share_of_peers_pct:.0f}% in {ml(pk.month)}.")
    ch1 = svg.line_chart("c4-share", d.month, [Series("NEAR Intents share", list(d.intents_share_of_peers_pct), "intents")],
                         kind="pct", gran="month", title="NEAR Intents share of native cross-chain swap volume, monthly",
                         desc=s1, y_max=100, marks=[Mark(as_date(pk.month), pk.intents_share_of_peers_pct, f"Peak {pk.intents_share_of_peers_pct:.0f}%", "intents")])
    t1 = table(["Month", "NEAR Intents", "THORChain", "Chainflip", "Maya", "Intents share"],
               zip(map(ml, d.month), col(d, "near_intents_usd", "usd", 2), col(d, "thorchain_dex_usd", "usd", 2),
                   col(d, "chainflip_amm_usd", "usd", 2), col(d, "maya_protocol_usd", "usd", 2), col(d, "intents_share_of_peers_pct", "pct")))
    card1 = Card("c4-share", "NEAR Intents share of native cross-chain swap volume, monthly", s1, ch1, t1, [SRC["defillama"]],
                 ["analysis/c4_market_share.py"], note="Peer set: NEAR Intents, THORChain, Chainflip, Maya Protocol. Complete months only.")

    sub = d[d.month >= base_m].reset_index(drop=True)
    idx = {c: 100 * sub[c] / sub[c].iloc[0] for c in ("near_intents_usd", "all_dex_usd", "bridge_aggregators_usd")}
    g = {c: idx[c].iloc[-1] - 100 for c in idx}
    s2 = (f"Over the 12 months to {ml(last.month)}, Intents volume rose {g['near_intents_usd']:.0f}% while total DEX volume "
          f"{'fell' if g['all_dex_usd'] < 0 else 'rose'} {abs(g['all_dex_usd']):.0f}% and bridge-aggregator volume rose "
          f"{g['bridge_aggregators_usd']:.0f}%.")
    ch2 = svg.line_chart("c4-index", sub.month, [
        Series("NEAR Intents", list(idx["near_intents_usd"]), "intents"),
        Series("Bridge aggregators", list(idx["bridge_aggregators_usd"]), "agg"),
        Series("All DEX volume", list(idx["all_dex_usd"]), "rest")],
        kind="index", gran="month", title=f"Monthly volume, indexed to {ml(base_m)} = 100", desc=s2,
        refs=[Ref(100, f"{ml(base_m)} = 100", "end")])
    t2 = table(["Month", "NEAR Intents", "Bridge aggregators", "All DEX", "Intents (USD)", "Aggregators (USD)", "All DEX (USD)"],
               zip(map(ml, sub.month), [fmt(v, "index") for v in idx["near_intents_usd"]],
                   [fmt(v, "index") for v in idx["bridge_aggregators_usd"]], [fmt(v, "index") for v in idx["all_dex_usd"]],
                   col(sub, "near_intents_usd", "usd", 2), col(sub, "bridge_aggregators_usd", "usd", 2), col(sub, "all_dex_usd", "usd", 2)))
    card2 = Card("c4-index", f"Monthly volume, indexed to {ml(base_m)} = 100", s2, ch2, t2, [SRC["defillama"]],
                 ["analysis/c4_market_share.py"])

    # Recent monthly swings: Intents vs bridge aggregators vs all DEX volume
    m = d.copy()
    for c, k in (("near_intents_usd", "i"), ("bridge_aggregators_usd", "a"), ("all_dex_usd", "x")):
        m[k] = m[c].pct_change() * 100
    recent = m.tail(6)
    big = recent.loc[recent.i.abs().idxmax()]

    def chg(v):
        return f"{'rose' if v >= 0 else 'fell'} {abs(v):.0f}%"
    jt = (f"in {ml(big.month)} Intents volume {chg(big.i)} while bridge aggregators {chg(big.a)} and all DEX volume "
          f"{chg(big.x)}")
    if big.month != last.month:
        lm_ = m.iloc[-1]
        jt += f"; in {ml(lm_.month)} the three moved {lm_.i:+.0f}%, {lm_.a:+.0f}% and {lm_.x:+.0f}%"
    N["c4"] = dict(share_last_pct=last.intents_share_of_peers_pct, share_year_ago_pct=yago.intents_share_of_peers_pct,
                   last=last.month, year_ago=base_m, peak_pct=pk.intents_share_of_peers_pct, peak_month=pk.month,
                   intents_growth_12m_pct=g["near_intents_usd"], dex_growth_12m_pct=g["all_dex_usd"],
                   aggregators_growth_12m_pct=g["bridge_aggregators_usd"])
    card1.plain = (f"Intents' share of native cross-chain swap volume rose from {yago.intents_share_of_peers_pct:.0f}% to "
                   f"{last.intents_share_of_peers_pct:.0f}% over the year to {ml(last.month)}.")
    card2.plain = (f"Over the same 12 months, Intents volume rose {g['near_intents_usd']:.0f}% while total DEX volume "
                   f"{'fell' if g['all_dex_usd'] < 0 else 'rose'} {abs(g['all_dex_usd']):.0f}%.")
    for c in (card1, card2):
        c.claim, c.api = "C4", ["dl_volume"]
    against = [f"The share has eased since its {ml(pk.month)} peak ({pk.intents_share_of_peers_pct:.0f}% → "
               f"{last.intents_share_of_peers_pct:.0f}%).",
               "The peer set leaves out large bridges whose data is paid (Relay, deBridge, Across, Mayan), so the level is "
               "overstated.",
               f"Bridge aggregators grew {g['bridge_aggregators_usd']:.0f}% over the same 12 months, close to Intents' "
               f"{g['near_intents_usd']:.0f}%.",
               f"Recent swings move with the market: {jt}."]
    change = "Intents' share of native cross-chain swap volume falling over a 12-month span."
    today = (f"{last.intents_share_of_peers_pct:.0f}% of native cross-chain swap volume in {ml(last.month)}, against "
             f"{yago.intents_share_of_peers_pct:.0f}% a year earlier.")
    return Claim("c4", "Intents is gaining share, not just moving with the market.", [card1, card2], [s1, s2], against, change,
                 today=today)


def short_model(m: str) -> str:
    return re.sub(r"-20\d{6}$", "", m.split("/", 1)[-1])


def c5_claim() -> Claim:
    tw = csv("c5_openrouter_tokens_weekly")
    tw = tw[tw.complete_week.astype(bool)].reset_index(drop=True)
    models = [c for c in tw.columns if "/" in c]
    rv = csv("c5_openrouter_revenue_estimate_weekly").set_index("week_ending").est_revenue_usd
    summ = csv("c5_summary").set_index("metric").value
    first, last = tw.iloc[0], tw.iloc[-1]
    rev_last = rv.get(last.week_ending)
    annual = rev_last * 52
    s1 = (f"NEAR AI served {compact(last.total_tokens)} tokens through OpenRouter in the week to {dl(last.week_ending)}, "
          f"up from {compact(first.total_tokens)} in its first full week (to {dl(first.week_ending)}). At list prices that "
          f"week was worth about {usd(rev_last, 0)}, or {usd(annual)} a year.")
    extra = [[(short_model(mo), compact(r[mo])) for mo in models if r[mo] > 0] + [("Est. revenue", usd(rv.get(r.week_ending), 0))]
             for _, r in tw.iterrows()]
    ch1 = svg.column_chart("c5-tokens", tw.week_ending, [Series("Tokens served", list(tw.total_tokens), "ai")], kind="count",
                           gran="week", title="Tokens NEAR AI serves on OpenRouter, per week", desc=s1, tooltip_extra=extra)
    t1 = table(["Week ending", "Total tokens"] + [short_model(m) for m in models] + ["Est. revenue"],
               [[dl(r.week_ending), compact(r.total_tokens, 2)] + [compact(r[m], 2) for m in models]
                + [usd(rv.get(r.week_ending), 0)] for _, r in tw.iterrows()])
    card1 = Card("c5-tokens", "Tokens NEAR AI serves on OpenRouter, per week", s1, ch1, t1, [SRC["openrouter"]],
                 ["analysis/c5_near_ai.py", "fetch/openrouter.py"],
                 note="Complete weeks only. Revenue estimate: NEAR AI's list prices on OpenRouter applied to its "
                      "prompt and completion tokens for each model.")

    ph = csv("c5_nearai_pool_history").dropna(subset=["total_staked_near"])
    act = pd.read_csv(RAW / "bigquery" / "nearai_staking_activity_daily.csv")
    ai_open = act[act.function_calls >= 10].block_date.iloc[0]
    jul = ph[ph.date <= ai_open].iloc[-1]
    pl = ph.iloc[-1]
    stakers = summ["NEAR AI Cloud Credits farm: active stakers"]
    subs = summ["NEAR AI Agents subscriptions: accounts ever subscribed"]
    s2 = (f"NEAR staked with NEAR AI's validator rose from {compact(jul.total_staked_near)} on {dl(jul.date)} to "
          f"{compact(pl.total_staked_near)} on {dl(pl.date)}. {stakers:.0f} accounts stake for NEAR AI Cloud credits, "
          f"and {subs:.0f} have subscribed to NEAR AI Agents.")
    ch2 = svg.line_chart("c5-stake", ph.date, [Series("NEAR staked", list(ph.total_staked_near), "ai")], kind="near",
                         gran="day", title="NEAR staked with NEAR AI's validator (nearai.pool.near)", desc=s2,
                         events=[Event(as_date(ai_open), "Staking for NEAR AI opens")])
    t2 = table(["Date", "NEAR staked"], zip(map(dl, ph.date), col(ph, "total_staked_near", "near", 2)))
    card2 = Card("c5-stake", "NEAR staked with NEAR AI's validator (nearai.pool.near)", s2, ch2, t2,
                 [SRC["rpc"], SRC["stakedao"], SRC["bq"]],
                 ["analysis/c5_near_ai.py", "fetch/nearai.py", "queries/nearai_pool_stake.sql",
                  "queries/nearai_staking_activity_daily.sql"],
                 note="About 99% of this stake comes through stake.dao, NEAR AI's staking contract "
                      "(Cloud Credits farm and Agents subscriptions).")

    credits = summ["NEAR AI Cloud credits funded per month (USD, at 100 NEAR-month = $1)"]
    tiles = [("NEAR AI Cloud models", f"{summ['NEAR AI Cloud models in catalog']:.0f}",
              f"{summ['  of which TEE-verifiable (private inference)']:.0f} run in TEEs (verifiable private inference)"),
             ("OpenRouter models", f"{summ['OpenRouter models served by NEAR AI']:.0f}", "served by NEAR AI"),
             ("Est. OpenRouter revenue", f"{usd(annual)} a year", "last full week × 52, at list prices"),
             ("NEAR staked for credits", compact(summ["NEAR AI Cloud Credits farm: NEAR staked (active)"]), f"{stakers:.0f} active stakers"),
             ("Credits funded by staking", f"{usd(credits)} a month", "100 NEAR staked for a month = $1"),
             ("IronClaw GitHub stars", compact(summ["IronClaw GitHub stars"]), "github.com/nearai/ironclaw")]
    cat = csv("c5_model_catalog")
    t3 = table(["Model", "Provider", "TEE-verifiable", "Input $/M tokens", "Output $/M tokens"],
               [[r.model_id, r.provider_type, "yes" if r.verifiable_tee else "no",
                 "–" if pd.isna(r.input_usd_per_m_tokens) else f"{r.input_usd_per_m_tokens:g}",
                 "–" if pd.isna(r.output_usd_per_m_tokens) else f"{r.output_usd_per_m_tokens:g}"] for r in cat.itertuples()])
    card3 = Card("c5-product", "NEAR AI at a glance", "NEAR AI Cloud sells private, verifiable inference on open models "
                 "through an OpenAI-compatible API, and lets holders stake NEAR for inference credits.",
                 None, t3, [SRC["cloud"], SRC["openrouter"], SRC["stakedao"], SRC["github"]],
                 ["analysis/c5_near_ai.py", "fetch/nearai.py", "fetch/github_stars.py"], tiles=tiles)

    top = summ["NEAR AI Cloud Credits farm: largest staker share (%)"]
    top10 = summ["NEAR AI Cloud Credits farm: top-10 stakers share (%)"]
    aw = csv("c5_ai_staking_activity_weekly")
    N["c5"] = dict(tokens_last_week=last.total_tokens, tokens_first_week=first.total_tokens, last_week=last.week_ending,
                   first_week=first.week_ending, peak_week_tokens=float(tw.total_tokens.max()),
                   est_revenue_last_week_usd=rev_last, est_revenue_annual_usd=annual,
                   ai_stake_near=pl.total_staked_near, ai_stake_date=pl.date, ai_stake_at_open_near=jul.total_staked_near,
                   ai_staking_open=ai_open, stakers=stakers, agents_subscribers=subs, largest_staker_pct=top,
                   top10_stakers_pct=top10, credits_usd_per_month=credits)
    card1.plain = (f"NEAR AI's weekly tokens on OpenRouter grew {last.total_tokens / first.total_tokens:.0f}× from its first "
                   f"full week (to {dl(first.week_ending)}) to {compact(last.total_tokens)} in the week to {dl(last.week_ending)}.")
    card2.plain = (f"NEAR staked with NEAR AI's validator rose from {compact(jul.total_staked_near)} before staking for NEAR AI "
                   f"opened to {compact(pl.total_staked_near)} on {dl(pl.date)}.")
    card1.claim, card1.api = "C5", ["openrouter"]
    card2.claim, card2.api = "C5", ["pool", "stakedao"]
    f = FACTS
    customers = [("the " + c if c.startswith("Government") else c) for c in f["near_ai_customers"]["value"] if c != "Brave"]
    evidence = [f"**Usage.** {s1}", f"**Staking.** {s2}",
                f"**Product.** {summ['NEAR AI Cloud models in catalog']:.0f} models in the NEAR AI Cloud catalog, "
                f"{summ['  of which TEE-verifiable (private inference)']:.0f} of them running in TEEs for verifiable private inference.",
                f"**Distribution.** Since {dl(f['brave_leo']['date'])}, Brave's AI assistant Leo runs {f['brave_leo']['model']} on "
                f"NEAR AI Cloud in the production browser. Brave has over {f['brave_leo']['brave_monthly_users']} monthly users, "
                f"though only Leo users who pick that model use NEAR AI Cloud. NEAR AI also names "
                f"{', '.join(customers[:-1])} and {customers[-1]} as customers.",
                f"**Developers.** IronClaw, NEAR AI's open-source agent OS, has {compact(summ['IronClaw GitHub stars'])} GitHub stars."]
    against = [f"NEAR AI doesn't publish revenue. Our OpenRouter estimate is about {usd(annual)} a year, and OpenRouter is one "
               f"channel among several.",
               f"Staking is concentrated: the largest staker holds {top:.0f}% of the credits farm and the top 10 hold {top10:.0f}%.",
               f"Staking funds about {usd(credits)} of credits a month, and contract activity has been flat at "
               f"{aw.function_calls.min():.0f}–{aw.function_calls.max():.0f} calls a week."]
    change = "Weekly tokens on OpenRouter falling for a sustained period, or AI staking shrinking."
    today = (f"{compact(last.total_tokens)} tokens on OpenRouter in the week to {dl(last.week_ending)}; "
             f"{compact(pl.total_staked_near)} NEAR staked on {dl(pl.date)}.")
    return Claim("c5", "NEAR AI is a working third layer.", [card1, card2, card3], evidence, against, change, today=today)


# ---------- Part 3 ----------

def inflation_cut_date() -> date:
    s = supply_flows_daily().sort_values("date").reset_index(drop=True)
    prior = s.minted_near.rolling(14).median().shift(1)
    after = s.minted_near[::-1].rolling(7).median()[::-1]
    hit = s[(s.date >= "2025-06-01") & (after < 0.7 * prior)]
    return hit.date.iloc[0].date()


def timeline(c6m, sm) -> Card:
    d = done(c6m)
    infl = protocol_change("max_inflation_rate")
    cut = as_date(infl["first_day_after"]) if infl else inflation_cut_date()
    gas_switch, _ = gas_burn_switch()
    bb = re.search(r"(\d{4}-\d{2}-\d{2})", DL_METHOD["methodology"]["HoldersRevenue"]).group(1)
    act = pd.read_csv(RAW / "bigquery" / "nearai_staking_activity_daily.csv")
    ai_open = act[act.function_calls >= 10].block_date.iloc[0]
    h = CFG["inflation"]["hsp_029"]
    ramp = pd.Period(h["ramp_start"], "M")
    ramp_end = ramp + h["ramp_months"] - 1
    proj = sm[(sm.policy == "hsp_029") & (sm.scenario == "base")]
    proj = proj[proj.month <= str(ramp_end + 6)]
    months = sorted(set(d.month) | set(proj.month))
    a = dict(zip(d.month, d.annualised_mint_rate_pct))
    p = dict(zip(proj.month, proj.inflation_rate * 100))
    cutm = f"{cut:%Y-%m}"
    before = d[d.month < cutm].tail(3).annualised_mint_rate_pct.mean()
    after = d[d.month > cutm].annualised_mint_rate_pct.mean()
    since = [(as_date(bb), f"buybacks on {dl(bb)}"), (as_date(ai_open), f"staking for NEAR AI on {dl(ai_open)}")]
    if gas_switch:
        since.append((as_date(gas_switch), f"burning all L1 gas on {dl(gas_switch)}"))
    since = [t for _, t in sorted(since)]
    sentence = (f"NEAR's issuance fell from {before:.1f}% to {after:.1f}% a year at the {ml(cutm)} cut. Every mechanism "
                f"that sends value to the token has switched on since: {', '.join(since[:-1])} and {since[-1]}. HSP-029 (passed "
                f"{dl(h['vote_passed'])}) would lower issuance to {100 * h['target_rate']:.1f}% by {ml(str(ramp_end))}.")
    rate = (lambda f: f"{100 * f[0] / f[1]:g}%")
    infl_label = f"Inflation {rate(infl['from'])} → {rate(infl['to'])}" if infl else "Inflation cut"
    events = [Event(cut, infl_label), Event(as_date(bb), "Buybacks start"),
              Event(as_date(ai_open), "AI staking opens"), Event(as_date(h["vote_passed"]), "HSP-029 passes"),
              Event(ramp.start_time.date(), f"Cut to {100 * h['target_rate']:g}% begins (assumed)")]
    if gas_switch:
        events.append(Event(as_date(gas_switch), "All gas burned"))
    ch = svg.line_chart("timeline", months, [
        Series("Actual, from NEAR minted", [a.get(m) for m in months], "ink", kind="rate"),
        Series("HSP-029 path (projection)", [p.get(m) for m in months], "ink", dashed=True, kind="rate")],
        kind="pct", gran="month", title="When each value-capture mechanism switched on, over NEAR's annual issuance rate",
        desc=sentence, y_max=6, events=events, height=320)
    rows = [(ml(m), "–" if a.get(m) is None else f"{a[m]:.2f}%", "–" if p.get(m) is None else f"{p[m]:.2f}%") for m in months]
    N["timeline"] = dict(inflation_cut=str(cut), gas_burn_all=gas_switch, issuance_before_pct=before, issuance_after_pct=after, buybacks_start=bb,
                         ai_staking_open=ai_open, hsp_029_passed=h["vote_passed"], hsp_029_ramp_start=h["ramp_start"],
                         hsp_029_ramp_end=str(ramp_end), hsp_029_target_pct=100 * h["target_rate"])
    plain = (f"Issuance was halved in {ml(cutm)}, and " + ", ".join(t.split(" on ")[0] for t in since[:-1])
             + f" and {since[-1].split(' on ')[0]} have all switched on since.")
    return Card("timeline", "When each value-capture mechanism switched on", sentence, ch,
                table(["Month", "Issuance, actual (annualised)", "HSP-029 path"], rows),
                [SRC["bq"], SRC["protocol"], SRC["dl_method"], SRC["hsp"], SRC["config"]],
                ["analysis/c6_capture.py", "analysis/scenarios.py", "config.yaml", "fetch/protocol_history.py",
                 "queries/supply_flows_daily.sql"],
                note="Issuance cap and gas-burn dates come from NEAR's protocol config at past blocks. The HSP-029 start "
                     "date is an assumption: vote end plus the 90-day grace period.",
                plain=plain, api=["protocol", "config"], claim="C6")


def c6_claim(c6m, c6q, wallets) -> Claim:
    d = done(c6m)
    q = c6q[c6q.months == 3].reset_index(drop=True)
    qL = q.iloc[-1]
    qY = q[q.quarter == str(pd.Period(qL.quarter, "Q") - 4)].iloc[0]
    cut_m = f"{inflation_cut_date():%Y-%m}"
    m_before = d[d.month < cut_m].tail(3).minted_near.mean()
    m_after = d[d.month > cut_m].minted_near.mean()
    last = d.iloc[-1]
    ai = d[d.ai_stake_added_near > 1e5]
    ai_txt = " and ".join(f"{compact(r.ai_stake_added_near)} in {ml(r.month)}" for r in ai.itertuples())
    s1 = (f"NEAR issued per month fell from about {compact(m_before)} to {compact(m_after)} after the cut, while NEAR "
          f"captured by the L1 burn and Intents revenue rose to {compact(last.captured_near)} in {ml(last.month)}. "
          f"New stake for NEAR AI added another {ai_txt}.")
    ch1 = svg.column_chart("c6-flows", d.month, [
        Series("L1 fees burned", list(d.l1_burned_near), "l1"),
        Series("NEAR captured as Intents revenue", list(d.intents_revenue_near), "intents"),
        Series("Newly staked for NEAR AI (locked)", [max(0.0, v) for v in d.ai_stake_added_near], "ai")],
        lines=[Series("NEAR issued", list(d.minted_near), "ink")], kind="near", gran="month", label_last=False,
        title="NEAR issued vs NEAR captured, monthly", desc=s1, total_label="Captured incl. AI stake")
    t1 = table(["Month", "NEAR issued", "L1 burned", "Intents revenue (NEAR)", "New AI stake", "Capture ratio", "Incl. AI stake"],
               zip(map(ml, d.month), col(d, "minted_near", "near", 2), col(d, "l1_burned_near", "near", 2),
                   col(d, "intents_revenue_near", "near", 2), col(d, "ai_stake_added_near", "near", 2),
                   col(d, "capture_ratio_pct", "pct"), col(d, "capture_ratio_incl_ai_stake_pct", "pct")))
    card1 = Card("c6-flows", "NEAR issued vs NEAR captured, monthly", s1, ch1, t1, [SRC["bq"], SRC["tracker"], SRC["rpc"]],
                 ["analysis/c6_capture.py", "queries/supply_flows_daily.sql"],
                 note="Issued and burned come from block-to-block changes in total supply. New AI stake is the month's net "
                      "change in NEAR staked with nearai.pool.near: locked, not removed, and withdrawable.")

    incl = [v if m >= ai.month.iloc[0] or a > 0 else None for m, v, a in
            zip(d.month, d.capture_ratio_incl_ai_stake_pct, d.ai_stake_added_near)]
    first_ai = next(i for i, v in enumerate(incl) if v is not None)
    incl = [None] * first_ai + list(d.capture_ratio_incl_ai_stake_pct[first_ai:])
    early = q[q.quarter < "2025Q4"].capture_ratio_pct.mean()
    s2 = (f"The capture ratio rose from about {early:.0f}% a quarter in 2025 Q1–Q3 to {qL.capture_ratio_pct:.1f}% in "
          f"{ql(qL.quarter)}. Counting new AI stake, " + " and ".join(
              f"{ml(r.month)} reaches {r.capture_ratio_incl_ai_stake_pct:.0f}%" for r in ai.itertuples()) + ".")
    ch2 = svg.line_chart("c6-ratio", d.month, [
        Series("Capture ratio", list(d.capture_ratio_pct), "intents"),
        Series("Including new AI stake", incl, "ai")],
        kind="pct", gran="month", title="Capture ratio: share of new NEAR offset each month", desc=s2)
    t2 = table(["Quarter", "NEAR issued", "L1 burned", "Intents revenue (NEAR)", "Capture ratio"],
               zip(map(ql, q.quarter), col(q, "minted_near", "near", 2), col(q, "l1_burned_near", "near", 2),
                   col(q, "intents_revenue_near", "near", 2), col(q, "capture_ratio_pct", "pct")))
    card2 = Card("c6-ratio", "Capture ratio: share of new NEAR offset each month", s2, ch2, t2,
                 [SRC["bq"], SRC["tracker"], SRC["rpc"]], ["analysis/c6_capture.py"],
                 note="Capture ratio = (L1 burn + NEAR captured as Intents revenue) ÷ NEAR issued. The table shows complete quarters.")

    w = wallets[wallets.month < c6m[c6m.partial_month.astype(bool)].month.min()].reset_index(drop=True) \
        if c6m.partial_month.any() else wallets
    wl = w.iloc[-1]
    wcols = [c for c in w.columns if c.endswith(".near")]
    bbw = "buybacks.multisignature.near"
    s3 = (f"{compact(wl.total_held_near)} of the {compact(wl.cumulative_intents_revenue_near)} NEAR captured as Intents revenue "
          f"is still in NEAR's three revenue wallets at the end of {ml(wl.month)} ({compact(wl[bbw])} in the buyback wallet). "
          f"Bought-back NEAR is held, not burned.")
    ch3 = svg.column_chart("c6-wallets", w.month, [Series("NEAR held in the revenue and buyback wallets", list(w.total_held_near), "intents")],
                           lines=[Series("Cumulative NEAR captured as Intents revenue", list(w.cumulative_intents_revenue_near), "ink")],
                           kind="near", gran="month", title="Where captured NEAR sits: revenue-wallet balances, month end",
                           desc=s3, tooltip_extra=[[(c, compact(r[c], 2)) for c in wcols] for _, r in w.iterrows()])
    t3 = table(["Month"] + wcols + ["Total held", "Cumulative Intents revenue"],
               [[ml(r.month)] + [fmt(r[c], "near", 2) for c in wcols] + [fmt(r.total_held_near, "near", 2),
                                                                         fmt(r.cumulative_intents_revenue_near, "near", 2)]
                for _, r in w.iterrows()])
    card3 = Card("c6-wallets", "Where captured NEAR sits: revenue-wallet balances, month end", s3, ch3, t3,
                 [SRC["bq"], SRC["tracker"]], ["analysis/c6_capture.py", "queries/revenue_wallet_balances.sql"])

    alt = 100 * (qL.l1_burned_near + qL.intents_revenue_near) / qY.minted_near
    cut_part = 100 * (qL.capture_ratio_pct - alt) / (qL.capture_ratio_pct - qY.capture_ratio_pct)
    l1pct = 100 * qL.l1_burned_near / qL.minted_near
    N["c6"] = dict(quarter=qL.quarter, capture_ratio_pct=qL.capture_ratio_pct, year_ago_quarter=qY.quarter,
                   capture_ratio_year_ago_pct=qY.capture_ratio_pct, ratio_at_year_ago_issuance_pct=alt,
                   share_of_rise_from_cut_pct=cut_part, l1_burn_pct_of_issuance=l1pct,
                   peak_month=d.loc[d.capture_ratio_pct.idxmax(), "month"], peak_pct=d.capture_ratio_pct.max(),
                   held_near=wl.total_held_near, cumulative_revenue_near=wl.cumulative_intents_revenue_near,
                   buyback_wallet_near=wl[bbw], wallets_month=wl.month,
                   ai_months={r.month: dict(added=r.ai_stake_added_near, incl_ratio=r.capture_ratio_incl_ai_stake_pct)
                              for r in ai.itertuples()})
    card1.plain = (f"NEAR captured by burns and buybacks rose to {compact(last.captured_near)} in {ml(last.month)} while NEAR "
                   f"issued halved to about {compact(m_after)} a month, but issuance is still the larger number.")
    card2.plain = (f"The share of new NEAR offset by burns and buybacks rose from about {early:.0f}% a quarter in 2025 Q1–Q3 to "
                   f"{qL.capture_ratio_pct:.1f}% in {ql(qL.quarter)}.")
    card3.plain = (f"Most NEAR captured as Intents revenue is still held in NEAR's revenue wallets "
                   f"({compact(wl.total_held_near)} of {compact(wl.cumulative_intents_revenue_near)} NEAR at the end of "
                   f"{ml(wl.month)}), not burned.")
    for c in (card1, card2, card3):
        c.claim = "C6"
    card1.api, card2.api, card3.api = ["tracker", "pool"], ["tracker"], ["tracker"]
    against = [f"The ratio is still small: in {ql(qL.quarter)}, {100 - round(qL.capture_ratio_pct, 1):.1f}% of new NEAR was not offset.",
               f"About {cut_part:.0f}% of the rise comes from the inflation cut rather than more revenue: at "
               f"{ql(qY.quarter)}'s issuance, {ql(qL.quarter)}'s captured NEAR would have offset only {alt:.1f}%.",
               f"The L1 burn is only {l1pct:.1f}% of issuance.",
               f"Bought-back NEAR is held, not burned: {compact(wl.total_held_near)} of the "
               f"{compact(wl.cumulative_intents_revenue_near)} NEAR captured as Intents revenue is still in NEAR's revenue wallets.",
               "These mechanisms are governance decisions that can change, and NEAR staked for NEAR AI is locked, not removed, "
               "and can be withdrawn."]
    change = "The share of new NEAR offset by burns and buybacks no longer rising, now that the fee switch is on."
    today = (f"{qL.capture_ratio_pct:.1f}% of new NEAR offset in {ql(qL.quarter)}, against {qY.capture_ratio_pct:.1f}% a year "
             f"earlier.")
    return Claim("c6", "The share of value reaching the token is rising.", [card1, card2, card3], [s1, s2], against, change,
                 today=today)


def be_label(m) -> str:
    return ml(m) if re.match(r"\d{4}-\d{2}$", str(m)) else str(m)


def win_label(w: str) -> str:
    return " → ".join(ql(x) for x in str(w).split(" -> "))


def scenario_label(r) -> str:
    name = r.scenario.capitalize()
    if r.start_growth_per_year == 0:
        return f"{name}: no growth"
    g = f"+{100 * r.start_growth_per_year:.0f}% a year"
    return f"{name}: {g}, halving every {r.half_life_years:g} years" if pd.notna(r.half_life_years) else f"{name}: {g}, held"


def scenarios(sm, ss) -> Card:
    policies = list(dict.fromkeys(ss.policy))  # hsp_029 first: the main path
    names = list(CFG["scenarios"])
    colors = dict(zip(names, ["o1", "o2", "o3"]))
    S = ss.set_index(["policy", "scenario"])
    labels = {r.scenario: scenario_label(r) for r in ss[ss.policy == policies[0]].itertuples()}
    cur, tgt = 100 * CFG["inflation"]["current_rate"], 100 * CFG["inflation"]["hsp_029"]["target_rate"]
    titles = {"hsp_029": f"With HSP-029 ({cur:g}% → {tgt:g}%): main path",
              "no_cut": f"If HSP-029 isn't implemented ({cur:g}%)"}
    panels = []
    for pol in policies:
        sub = sm[sm.policy == pol]
        dates = sorted(sub.month.unique())
        ss_, marks = [], []
        for n in names:
            v = sub[sub.scenario == n].set_index("month").capture_ratio_pct
            ss_.append(Series(labels[n], [v.get(m) for m in dates], colors[n], show_end=False))
            be = S.loc[(pol, n), "breakeven_month"]
            if re.match(r"\d{4}-\d{2}$", str(be)):
                marks.append(Mark(as_date(be), 100, ml(be), colors[n], dy=-8 if n == "bull" else 16,
                                  dx=-7 if n == "bull" else 7, anchor="end" if n == "bull" else "start"))
        panels.append((titles[pol], dates, ss_, marks))
    base, bull = S.loc[("hsp_029", "base")], S.loc[("hsp_029", "bull")]
    base_nc = S.loc[("no_cut", "base")]
    q_last = csv("c6_capture_quarterly").query("months == 3").quarter.iloc[-1]
    switch, _ = gas_burn_switch()
    sentence = (f"Intents revenue in NEAR grew {100 * base.start_growth_per_year:.0f}% a year over "
                f"{win_label(base.trend_window)}. If that growth halves every {base.half_life_years:g} years (base case), "
                f"burns and revenue fully offset new supply by {be_label(base.breakeven_month)} with HSP-029, or "
                f"{be_label(base_nc.breakeven_month)} if issuance stays at {cur:g}%. If it holds (bull), by "
                f"{be_label(bull.breakeven_month)}; with no growth (bear), not within {CFG['horizon_years']} years.")
    ch = svg.panel_line_chart("scenarios", panels, kind="pct", gran="month", height=330, y_max=200,
                              title="Scenarios: capture ratio, projected monthly", desc=sentence,
                              refs=[Ref(100, "Breakeven", "end")],
                              legend_items=[(labels[n], colors[n], "line", False) for n in names])
    rows = [[r.policy_label, r.scenario, pct(100 * r.start_growth_per_year, 0),
             "–" if r.start_growth_per_year == 0 else
             (f"halves every {r.half_life_years:g} years" if pd.notna(r.half_life_years) else "held"),
             pct(r.ratio_after_1y_pct), pct(r.ratio_after_3y_pct), f"{r.supply_after_6y_bn:.3f}B",
             be_label(r.breakeven_month),
             "–" if pd.isna(r.revenue_vs_start_at_breakeven) else f"{r.revenue_vs_start_at_breakeven:.1f}×"]
            for r in ss.itertuples()]
    N["scenarios"] = ss.to_dict(orient="records")
    note = (f"Projections, not findings. Starting point: {ql(q_last)}'s Intents revenue and L1 burn (a capture ratio of "
            f"{base.start_capture_ratio_pct:.1f}% in {ml(base.start_month)}). Growth is in NEAR terms, so a rising NEAR price "
            f"slows it. L1 burn is held at {ql(q_last)}'s level"
            + (f", scaled to 100% burned from {dl(switch)}" if switch else "") + ". Lines leave the chart above 200%.")
    plain = (f"If Intents revenue growth halves every {base.half_life_years:g} years, burns and buybacks offset all new NEAR "
             f"by {be_label(base.breakeven_month)} with HSP-029; if growth holds, by {be_label(bull.breakeven_month)}; with no "
             f"growth, not within {CFG['horizon_years']} years.")
    return Card("scenarios", "Scenarios: capture ratio, projected monthly", sentence, ch,
                table(["Issuance path", "Scenario", "Revenue growth a year at start (NEAR terms)", "Growth then",
                       "After 1 year", "After 3 years", "Supply after 6 years", "Breakeven",
                       "Revenue at breakeven vs today"], rows),
                [SRC["config"]], ["analysis/scenarios.py", "config.yaml"], note=note, plain=plain, api=["config"], claim="C6")


def window_card(ws) -> Card:
    """How much the breakeven date depends on the window used for the trailing growth rate."""
    rows = [[win_label(r.window), pct(100 * r.growth_per_year, 0), be_label(r.breakeven_fading_hsp_029),
             be_label(r.breakeven_held_hsp_029), be_label(r.breakeven_fading_no_cut), be_label(r.breakeven_held_no_cut)]
            for r in ws.itertuples()]
    hsp = [m for c in ("breakeven_fading_hsp_029", "breakeven_held_hsp_029") for m in ws[c]
           if re.match(r"\d{4}-\d{2}$", str(m))]
    used = ws[ws.quarters == CFG["trend"]["quarters"]].iloc[0]
    sentence = (f"Measured over different recent windows, Intents' revenue growth ranges from "
                f"{100 * ws.growth_per_year.min():.0f}% to {100 * ws.growth_per_year.max():.0f}% a year. With HSP-029, that "
                f"puts breakeven between {ml(min(hsp))} and {ml(max(hsp))}, depending on the window and on whether growth "
                f"holds or fades. The scenarios use {win_label(used.window)} ({100 * used.growth_per_year:.0f}% a year).")
    N["scenario_windows"] = ws.to_dict(orient="records")
    return Card("scenario-windows", "How much depends on the growth window", sentence, None,
                table(["Window", "Growth a year", "HSP-029: fades", "HSP-029: holds", "2.5%: fades", "2.5%: holds"], rows),
                [SRC["config"]], ["analysis/scenarios.py", "config.yaml"], table_open=True)


# ---------- Risks: the evidence against the thesis, in one place (THESIS.md) ----------

def risks() -> list:
    """(heading, text). Each claim's full list of caveats is in METHODS.md."""
    n2, n3, n4, n5, n6 = (N[k] for k in ("c2", "c3", "c4", "c5", "c6"))
    stop = pd.Period(n2["kaiching_stop"], "M")
    m3 = csv("c3_monthly")
    m3 = m3[m3.complete_month.astype(bool)]
    pk = m3.loc[m3.unique_users.idxmax()]
    users = (f" Distinct users fell from {compact(pk.unique_users)} in {ml(pk.month)} to {compact(n3['unique_users'])}."
             if pk.month != n3["month"] else "")
    return [
        ("Part of the shift is the L1 shrinking",
         f"Intents' share rose partly because the rest of the L1 fell. One app, KaiChing, sent "
         f"{n2['kaiching_share_mar_2026_pct']:.0f}% of all L1 transactions in {ml(str(stop - 1))}, and its stop caused "
         f"{n2['kaiching_share_of_april_drop_pct']:.0f}% of the fall in {ml(str(stop))}. L1 fees are cheap by design, so a "
         f"high Intents share of revenue is easy to reach."),
        ("Intents' activity is concentrated and led by trading",
         f"On 1Click in {ml(n3['month'])}, {n3['any_stable_pct']:.0f}% of volume involved a stablecoin and one app "
         f"({n3['top_referrer']}) routed {n3['top_referrer_share_pct']:.0f}% of it.{users} Flow like this can leave as quickly "
         f"as it came."),
        ("Market share is off its peak, and rivals are growing too",
         f"Intents' share of native cross-chain swap volume peaked at {n4['peak_pct']:.0f}% in {ml(n4['peak_month'])} and was "
         f"{n4['share_last_pct']:.0f}% in {ml(n4['last'])}. Bridge aggregators grew {n4['aggregators_growth_12m_pct']:.0f}% "
         f"over the same twelve months, close to Intents' {n4['intents_growth_12m_pct']:.0f}%. Our peer set leaves out large "
         f"bridges whose data is paid, and wallets can switch routes cheaply."),
        ("NEAR AI is early and unproven",
         f"It publishes no revenue. Our estimate from OpenRouter, one of its sales channels, is about "
         f"{usd(n5['est_revenue_annual_usd'])} a year, and no published mechanism sends that money to the token. Staking "
         f"for AI credits is concentrated: the largest staker holds {n5['largest_staker_pct']:.0f}% of the credits farm."),
        ("The token captures little so far",
         f"In {ql(n6['quarter'])}, {100 - round(n6['capture_ratio_pct'], 1):.1f}% of new NEAR was not offset. About "
         f"{n6['share_of_rise_from_cut_pct']:.0f}% of the year's rise in the offset came from cutting issuance, not from more "
         f"revenue. The NEAR bought back is held, not burned, and NEAR staked for AI can be withdrawn."),
        ("Governance and regulation",
         f"Buybacks, the fee split and HSP-029 are governance decisions that can be changed or reversed, and HSP-029 still "
         f"needs a protocol upgrade. Much of Intents' flow is stablecoins and privacy coins (Zcash was "
         f"{n3['zcash_origin_share_pct']:.0f}% of 1Click volume by origin in {ml(n3['month'])}), so rules on cross-chain "
         f"swaps or privacy assets could restrict it."),
    ]


# ---------- Dashboard: DASHBOARD.md and site/index.html, from the same cards ----------

def sections(flow, claims, tl, sc) -> list:
    c = {cl.id: cl for cl in claims}

    def charts(*ids):
        return [card for i in ids for card in c[i].cards if card.chart]
    return [
        ("follow-the-money", "Follow the money",
         "What each layer earned in the latest complete month, and how much of it reached the token.", [flow]),
        ("near-l1", "NEAR L1", "The base chain: how much it is used, and how much of that use is Intents.", charts("c2")),
        ("near-intents", "NEAR Intents",
         "Cross-chain swaps settled on NEAR: volume, users, where swaps start, and share of the market.", charts("c3", "c4")),
        ("near-ai", "NEAR AI", "Private AI inference: usage on OpenRouter and NEAR staked to pay for it.", charts("c5")),
        ("revenue-and-the-token", "Revenue and the token",
         "Where NEAR's protocol revenue comes from, and how much new NEAR it offsets.", charts("c1") + [tl] + charts("c6")),
        ("scenarios", "Scenarios", "Projections from the trend so far, not findings.", [sc]),
    ]


def query_blocks(c: Card) -> list:
    """(label, text, language) for every query behind a chart: its SQL files, then its API requests."""
    out = [(f"{q} (NEAR BigQuery)", (ROOT / q).read_text().strip(), "sql") for q in c.code if q.endswith(".sql")]
    out += [(API[k][0], API[k][1], "text") for k in c.api]
    return out


def src_html(sources) -> str:
    out = []
    for label, url, when in sources:
        s = f'<a href="{e(url)}">{e(label)}</a>' if url else e(label)
        out.append(s + (f" ({e(when)})" if when else ""))
    return "; ".join(out)


def src_md(sources) -> str:
    return "; ".join((f"[{l}]({u})" if u else l) + (f" ({w})" if w else "") for l, u, w in sources)


def code_html(paths) -> str:
    return ", ".join(f'<a href="../{e(p)}"><code>{e(p)}</code></a>' for p in paths)


def card_html(c: Card) -> str:
    p = [f'<article class="card" id="{c.id}">', '<div class="card-head">', f"<h3>{e(c.title)}</h3>"]
    if c.claim:
        p.append(f'<span class="badge">Supports {e(c.claim)}</span>')
    p.append("</div>")
    p.append(f'<p class="sentence">{e(c.plain or c.sentence)}</p>')
    if c.chart:
        p.append(f'<div class="chart-wrap">{c.chart.inline()}</div>')
        if c.chart.hover:
            blob = json.dumps(c.chart.hover, separators=(",", ":")).replace("</", "<\\/")
            p.append(f'<script type="application/json" id="hover-{c.chart.id}">{blob}</script>')
    if c.note:
        p.append(f'<p class="note">{e(c.note)}</p>')
    p.append(f'<p class="meta"><span>Source: {src_html(c.sources)}</span><span>Code: {code_html(c.code)}</span></p>')
    qb = query_blocks(c)
    if qb:
        p.append("<details><summary>Query behind this chart</summary>" + "".join(
            f'<p class="q-label">{e(l)}</p><pre><code>{e(t)}</code></pre>' for l, t, _ in qb) + "</details>")
    if c.table:
        p.append(f'<details><summary>Table</summary><div class="table-wrap">{c.table}</div></details>')
    p.append("</article>")
    return "".join(p)


def card_md(c: Card) -> list:
    code = ", ".join(f"[`{x}`]({x})" for x in c.code)
    meta = (f"{c.note} " if c.note else "") + f"Source: {src_md(c.sources)}. Code: {code}." \
        + (f" Supports {c.claim}." if c.claim else "")
    out = [f'<a id="{c.id}"></a>', "", f"### {c.title}", "", c.plain or c.sentence, "",
           f"![{c.title}](site/charts/{c.chart.id}.svg)", "", f"<sub>{meta}</sub>", ""]
    qb = query_blocks(c)
    if qb:
        out += ["<details><summary>Query behind this chart</summary>", ""]
        for label, text, lang in qb:
            out += [f"**{label}**", "", f"```{lang}", text, "```", ""]
        out += ["</details>", ""]
    return out


INTRO = ("Every chart behind the thesis, with one plain sentence on what it shows and the query behind it. "
         "Every number is computed from the files in <code>data/</code> by <code>make charts</code>.")


def page(secs, data_asof) -> str:
    css = (f":root{{color-scheme:light;{svg.css_vars(0)}}}"
           f"@media (prefers-color-scheme: dark){{:root:not([data-theme=\"light\"]){{color-scheme:dark;{svg.css_vars(1)}}}}}"
           f":root[data-theme=\"dark\"]{{color-scheme:dark;{svg.css_vars(1)}}}" + svg.CHART_CSS)
    body = [f'<header class="hero"><p class="kicker">Dashboard · NEAR HACKATHON, Investment Thesis track</p>'
            f"<h1>NEAR: three layers, one token</h1>"
            f"<p class=\"thesis\">NEAR isn't just an L1 anymore. It's a three-layer business, and the token is only beginning "
            f"to capture that value.</p>"
            f'<p class="asof">{INTRO} Data as of {e(data_asof)}. The argument is in '
            f'<a href="../THESIS.md">THESIS.md</a> and the methods in <a href="../METHODS.md">METHODS.md</a>. '
            f"Hover a chart for values, or open its table.</p></header>",
            '<nav class="toc">' + "".join(f'<a href="#{sid}">{e(t)}</a>' for sid, t, _, _ in secs) + "</nav>"]
    for sid, title, intro, cards in secs:
        body.append(f'<section class="part" id="{sid}"><h2>{e(title)}</h2><p class="lede">{e(intro)}</p>'
                    + "".join(card_html(c) for c in cards) + "</section>")
    srcs = sorted({(l, u, w) for l, u, w in SRC.values()}, key=lambda s: s[0].lower())
    body.append('<section class="part" id="sources"><h2>Sources</h2><ul class="sources">'
                + "".join(f"<li>{src_html([s])}</li>" for s in srcs) + "</ul>"
                "<p class=\"note\">Rebuild everything on this page with <code>make charts</code> (no keys needed). "
                "Check the committed data against the live sources with <code>make verify</code> (about a minute, no keys). "
                "Refresh the data with <code>make fetch</code>; see the README.</p></section>")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>NEAR Thesis Dashboard</title>"
            "<meta name=\"description\" content=\"Every chart behind the NEAR three-layer thesis, with the query behind it.\">"
            f"<link rel=\"stylesheet\" href=\"style.css\"><style>{css}</style></head><body><main>"
            + "".join(body) + "</main><script src=\"app.js\"></script></body></html>\n")


def dashboard_md(secs, data_asof) -> str:
    out = ["<!-- Generated by `make charts` (viz/build.py). Edit the code, not DASHBOARD.md. -->", "",
           "# Dashboard: NEAR, three layers, one token", "",
           INTRO.replace("<code>", "`").replace("</code>", "`") + f" Data as of {dl(data_asof)}. The argument is in "
           "[THESIS.md](THESIS.md) and the methods in [METHODS.md](METHODS.md). For hover readouts and a data table "
           "under every chart, open `site/index.html` in a browser (no server needed).", "",
           "**Sections:** " + " · ".join(f"[{t}](#{sid})" for sid, t, _, _ in secs), ""]
    for sid, title, intro, cards in secs:
        out += [f"## {title}", "", intro, ""]
        for c in cards:
            out += card_md(c)
    srcs = sorted({(l, u, w) for l, u, w in SRC.values()}, key=lambda s: s[0].lower())
    out += ["## Sources", ""] + [f"- {src_md([x])}" for x in srcs] + [""]
    return "\n".join(out)


def main() -> None:
    c1, c2, c4 = csv("c1_revenue_mix_monthly"), csv("c2_l1_monthly"), csv("c4_market_share_monthly")
    c6m, c6q, wallets = csv("c6_capture_monthly"), csv("c6_capture_quarterly"), csv("c6_revenue_wallets_monthly")
    sm, ss, ws = csv("scenarios_monthly"), csv("scenarios_summary"), csv("scenarios_window_sensitivity")
    vol_m = month_volume()

    flow = money_flow(c1, c6m, wallets, c2, vol_m)
    claims = [c1_claim(c1), c2_claim(c2, vol_m), c3_claim(vol_m), c4_claim(c4), c5_claim()]
    tl = timeline(c6m, sm)
    claims.append(c6_claim(c6m, c6q, wallets))
    sc = scenarios(sm, ss)
    wc = window_card(ws)
    data_asof = max([m["fetched_at"][:10] for m in MAN.values()] + [str(BQ_THROUGH)])
    N["data_asof"] = data_asof

    secs = sections(flow, claims, tl, sc)
    charts = [c.chart for _, _, _, cards in secs for c in cards]
    (SITE / "charts").mkdir(parents=True, exist_ok=True)
    for ch in charts:
        (SITE / "charts" / f"{ch.id}.svg").write_text(ch.standalone())
    (SITE / "index.html").write_text(page(secs, data_asof))
    (ROOT / "DASHBOARD.md").write_text(dashboard_md(secs, data_asof))
    ctx = dict(claims=claims, flow=flow, tl=tl, sc=sc, wc=wc, vol_m=vol_m, c1=c1, c4=c4, c6m=c6m)
    thesis.write(N, ctx, SRC, risks(), ss, CFG, ws)
    (DER / "headline_numbers.json").write_text(json.dumps(N, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
    print(f"Built THESIS.md, METHODS.md, DASHBOARD.md, site/index.html and {len(charts)} charts in site/charts/ "
          f"(data as of {data_asof}).")
    for t in N["key_points"]:
        print(" -", t)


if __name__ == "__main__":
    main()
