"""Write THESIS.md and METHODS.md from their templates (called by viz/build.py, so `make charts` rebuilds both).

THESIS.md (viz/thesis_template.md) is the short page: the thesis in one paragraph, the three businesses, how each one
reaches the token, and one table that sets each claim's evidence for it against the evidence against it and names the
result that would change our mind. METHODS.md (viz/methods_template.md) is the reference behind
it: how each number is computed, what we couldn't compute, each claim's evidence and caveats in detail, the scenario
tables and the sources.

The templates hold the prose. Every number enters through a {placeholder} filled here from what viz/build.py
computed (headline numbers, chart sentences, each claim's evidence), from data/derived/ and data/raw/, and from
data/manual/facts.yaml (sourced facts that no API exposes).

check_template() stops the build if a template's own text contains a digit outside a short list of labels (C1-C6,
L1, 1Click, HSP-0xx, Part n, list numbering, code spans, chart paths), so a hand-typed figure can't slip into
either document.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import yaml

from viz.svg import as_date, compact, fmt

ROOT = Path(__file__).resolve().parents[1]
# output file -> its template
TEMPLATES = {"THESIS.md": ROOT / "viz" / "thesis_template.md", "METHODS.md": ROOT / "viz" / "methods_template.md"}
FACTS = ROOT / "data" / "manual" / "facts.yaml"
DER, RAW = ROOT / "data" / "derived", ROOT / "data" / "raw"

ALLOWED = [r"<!--.*?-->", r"`[^`\n]*`", r"site/charts/[\w-]+\.svg", r"\bC[1-6]\b", r"\bL1\b", r"1Click",
           r"HSP-0\d\d", r"\bPart [1-4]\b", r"^\d+\. "]


def check_template(text: str, name: str = "the template") -> None:
    body = re.sub(r"\{[a-z0-9_]+\}", "", text)
    for pat in ALLOWED:
        body = re.sub(pat, "", body, flags=re.M)
    bad = [m.group(0).strip() for m in re.finditer(r"[^\n]{0,30}\d[^\n]{0,30}", body)]
    if bad:
        raise SystemExit(f"{name} has hand-typed figures; use a {{placeholder}} instead:\n  "
                         + "\n  ".join(bad))


def ml(m) -> str:
    d = as_date(m)
    return f"{'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()[d.month - 1]} {d.year}"


def dl(d) -> str:
    d = as_date(d)
    return f"{'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()[d.month - 1]} {d.day}, {d.year}"


def pct(v, digits=0) -> str:
    return fmt(v, "pct", digits)


def md_table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
    return "\n".join(out)


def link(label, url, when=None) -> str:
    s = f"[{label}]({url})" if url else label
    return s + (f" ({when})" if when else "")


def frac(x) -> float:
    return x[0] / x[1]


def signed(v, unit, digits=0) -> str:
    return f"{'+' if v >= 0 else '−'}{abs(v):.{digits}f}{unit}"


def and_list(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def protocol_changes() -> dict:
    """{parameter: change} from fetch/protocol_history.py, or {} if it hasn't been fetched."""
    p = RAW / "rpc" / "protocol_changes.json"
    if not p.exists():
        return {}
    return {c["parameter"]: c for c in json.loads(p.read_text())["changes"]}


def crosschecks() -> str:
    d = pd.read_csv(DER / "crosschecks_monthly.csv")
    out = []
    p = d[(d.check == "price_usd") & (d.source == "CoinGecko")]
    if len(p):
        out.append(f"NEAR price: within {p.pct_diff.abs().max():.1f}% of CoinGecko in every month.")
    m = d[d.check == "minted_near"]
    if len(m):
        out.append(f"NEAR issued: median gap of {m.pct_diff.abs().median():.1f}% to the protocol rule "
                   "(issuance rate × supply).")
    r = d[(d.check == "intents_revenue_usd") & (d.source == "DefiLlama")].tail(6)
    if len(r):
        out.append(f"Intents revenue: DefiLlama records NEAR when it is swept into the revenue wallets, in batches, "
                   f"so single months differ; over the last six months the median gap is {r.pct_diff.median():+.0f}%.")
    g = d[d.check == "l1_gross_fees_usd"]
    if len(g):
        parts = [f"{src} {grp.pct_diff.median():+.0f}%" for src, grp in g.groupby("source")]
        out.append("L1 gross fees, ours vs " + " and ".join(parts) + " (median monthly gap).")
    return " ".join(out)


def values(N: dict, ctx: dict, SRC: dict, AGAINST: dict, ss: pd.DataFrame, cfg: dict, ws: pd.DataFrame) -> dict:
    """AGAINST: claim id -> the evidence against it (viz/build.py `against`)."""
    facts = yaml.safe_load(FACTS.read_text())
    pc = protocol_changes()
    c2 = pd.read_csv(DER / "c2_l1_monthly.csv")
    c2 = c2[~c2.partial_month.astype(bool)]
    summ = pd.read_csv(DER / "c5_summary.csv").set_index("metric").value
    mf, n1, n2, n3, n4, n5, n6, tl = (N[k] for k in ("money_flow", "c1", "c2", "c3", "c4", "c5", "c6", "timeline"))
    claims, flow, tlc, sc, wc = ctx["claims"], ctx["flow"], ctx["tl"], ctx["sc"], ctx["wc"]
    asof = N["data_asof"]
    h = cfg["inflation"]["hsp_029"]

    # Mechanisms, dated from data wherever possible
    infl = pc.get("max_inflation_rate")
    gas = pc.get("burnt_gas_reward")
    infl_date = infl["first_day_after"] if infl else tl["inflation_cut"]
    infl_from, infl_to = (100 * frac(infl["from"]), 100 * frac(infl["to"])) if infl else (tl["issuance_before_pct"], tl["issuance_after_pct"])
    rows = [(f"Issuance cap cut from {infl_from:.3g}% to {infl_to:.3g}%", dl(infl_date),
             "Halves the NEAR issued each year" if abs(infl_to / infl_from - 0.5) < 0.01 else "Lowers the NEAR issued each year",
             "Protocol config via archival RPC; visible in BigQuery supply flows" if infl else "BigQuery supply flows")]
    if gas:
        rows.append((f"All L1 gas burned (HSP-027; the {100 * frac(gas['from']):g}% rebate to called contracts ends)",
                     dl(gas["first_day_after"]), "Every unit of gas paid is destroyed",
                     f"Protocol config via archival RPC; {link('vote coverage', facts['hsp_027']['source'])}"))
    else:
        rows.append(("All L1 gas burned (HSP-027; the rebate to called contracts ends)", f"live on {dl(asof)}",
                     "Every unit of gas paid is destroyed",
                     f"Protocol config via RPC; {link('vote coverage', facts['hsp_027']['source'])}"))
    rows += [("Intents revenue buys back NEAR", dl(tl["buybacks_start"]),
              "NEAR's share of Intents fees buys NEAR on the market; it is held in `buybacks.multisignature.near`",
              link("DefiLlama methodology", SRC["dl_method"][1])),
             ("Staking for NEAR AI", dl(tl["ai_staking_open"]),
              "Holders lock NEAR with NEAR AI's validator and receive inference credits", "BigQuery (`stake.dao` activity)"),
             (f"HSP-029: issuance cap {100 * cfg['inflation']['current_rate']:g}% → {100 * h['target_rate']:g}%",
              f"passed {dl(h['vote_passed'])}; phase-in assumed from {ml(h['ramp_start'])}",
              f"Lowers the cap evenly over {h['ramp_months']} months; not yet in force", link("vote coverage", h["source"]))]
    mech_table = md_table(["Mechanism", "Since", "What it does", "Evidence"], rows)

    first_mech = min(as_date(infl_date), as_date(tl["buybacks_start"]))
    mech_months = round((as_date(asof) - first_mech).days / 30.44)

    if gas:
        share_before = 1 - frac(gas["from"])
        l1_method = (f"L1 gross fees = burn ÷ {share_before:g} before {dl(gas['first_day_after'])}, while "
                     f"{100 * frac(gas['from']):g}% of gas went to the called contract, and = burn from that day, when all "
                     "gas is burned. Before the switch this is an upper bound, because some gas was always burned in full, "
                     "so C1's Intents share is conservative.")
        gas_txt = (f"Until {dl(gas['first_day_after'])}, {100 * frac(gas['from']):g}% of each L1 fee went to the contract "
                   f"being called and the rest was burned. Since then, all of it is burned.")
    else:
        l1_method = "L1 gross fees = burn ÷ the burned share of gas set in the protocol config."
        gas_txt = "Part of each L1 fee is burned, and an approved upgrade burns all of it."

    def is_month(m):
        return bool(re.match(r"\d{4}-\d{2}$", str(m)))

    def be(m):
        return ml(m) if is_month(m) else str(m)

    S = ss.set_index(["policy", "scenario"])
    base, bull, bear = S.loc[("hsp_029", "base")], S.loc[("hsp_029", "bull")], S.loc[("hsp_029", "bear")]
    scen_rows = [[r.policy_label, r.scenario, pct(100 * r.start_growth_per_year),
                  "–" if r.start_growth_per_year == 0 else
                  (f"halves every {r.half_life_years:g} years" if pd.notna(r.half_life_years) else "held"),
                  pct(r.ratio_after_1y_pct, 1), pct(r.ratio_after_3y_pct, 1), f"{r.supply_after_6y_bn:.3f}B",
                  be(r.breakeven_month),
                  "–" if pd.isna(r.revenue_vs_start_at_breakeven) else f"{r.revenue_vs_start_at_breakeven:.1f}×"]
                 for r in ss.itertuples()]

    def win(w):
        return " → ".join(x.replace("Q", " Q") for x in str(w).split(" -> "))

    win_rows = [[win(r.window), pct(100 * r.growth_per_year), be(r.breakeven_fading_hsp_029), be(r.breakeven_held_hsp_029),
                 be(r.breakeven_fading_no_cut), be(r.breakeven_held_no_cut)] for r in ws.itertuples()]

    sources = sorted({v for v in SRC.values()}, key=lambda s: s[0].lower())
    src_lines = [f"- {link(l, u, w)}" for l, u, w in sources]
    src_lines += [f"- {link('NEAR AI homepage (customers)', facts['near_ai_customers']['source'], 'checked ' + facts['near_ai_customers']['checked'])}",
                  f"- {link('NEAR AI blog: private inference for Brave Leo', facts['brave_leo']['source'], 'checked ' + facts['brave_leo']['checked'])}",
                  f"- {link('HSP-027 coverage (gas rebate removed)', facts['hsp_027']['source'], 'checked ' + facts['hsp_027']['checked'])}",
                  "- Sourced facts no API exposes: `data/manual/facts.yaml`. Fetch log with dates: `data/raw/_manifest.json`."]

    # ---- the latest complete month, and a year earlier: one table, grouped by business ----
    M = mf["month"]
    Y = str(pd.Period(M, "M") - 12)
    c1m = ctx["c1"].set_index("month")
    vm = ctx["vol_m"].set_index("month").intents_volume_usd
    c4m = ctx["c4"].set_index("month")
    c6m = ctx["c6m"].set_index("month")
    c2m = c2.set_index("month")
    m3 = pd.read_csv(DER / "c3_monthly.csv").set_index("month")

    def val(get, m):
        try:
            v = get(m)
        except KeyError:
            return None
        return v if pd.notna(v) and v != 0 else None

    def row(label, get, f, points=None):
        """[label, latest month, a year earlier, change]. `points`: digits for a percentage-point change."""
        cur, prev = val(get, M), val(get, Y)
        if cur is None or prev is None:
            change = "new" if cur is not None else "–"
        elif points is not None:
            change = signed(round(cur, points) - round(prev, points), " pts", points)
        elif cur / prev >= 2:
            change = f"{cur / prev:.1f}×"
        else:
            change = signed(100 * (cur / prev - 1), "%")
        return [label, f(cur) if cur is not None else "–", f(prev) if prev is not None else "–", change]

    usd_ = lambda v: fmt(v, "usd")
    ai_m = pd.read_csv(DER / "c5_openrouter_revenue_estimate_monthly.csv")
    ai_tok = ai_m[ai_m.complete_month.astype(bool)].set_index("month").near_ai_tokens
    groups = [
        ("NEAR Intents", [
            row("Swap volume", lambda m: vm[m], lambda v: fmt(v, "usd", 2)),
            row("NEAR's share of swap fees", lambda m: c1m.loc[m, "intents_revenue_usd"], usd_),
            row("Distinct 1Click users", lambda m: m3.loc[m, "unique_users"], compact),
            row("Apps sending swaps through 1Click", lambda m: m3.loc[m, "active_referrers"], lambda v: f"{v:.0f}"),
            row("Share of native cross-chain swap volume", lambda m: c4m.loc[m, "intents_share_of_peers_pct"],
                lambda v: pct(v, 1), points=1)]),
        ("NEAR L1", [
            row("Transactions a day", lambda m: c2m.loc[m, "tx_per_day"], compact),
            row("Gas fees paid", lambda m: c1m.loc[m, "l1_gross_fees_usd"], usd_),
            row("Share of transactions that are Intents", lambda m: c2m.loc[m, "intents_share_of_l1_tx_pct"],
                lambda v: pct(v, 1), points=1)]),
        ("NEAR AI", [
            row("Tokens served on OpenRouter", lambda m: ai_tok[m], compact),
            row("NEAR staked for AI credits, month end", lambda m: c6m.loc[m, "ai_staked_month_end_near"], compact)]),
        ("NEAR token", [
            row("New NEAR issued", lambda m: c6m.loc[m, "minted_near"], compact),
            row("Share of new NEAR offset by burns and buybacks", lambda m: c6m.loc[m, "capture_ratio_pct"],
                lambda v: pct(v, 1), points=1)]),
    ]
    ctx_rows = [[f"**{g}**" if k == 0 else ""] + r for g, rs in groups for k, r in enumerate(rs)]
    context_table = md_table(["Business", "Measure", ml(M), ml(Y), "Change"], ctx_rows)
    vol_x = vm[M] / vm[Y]
    l1_fee_cents = 100 * c1m.loc[M, "l1_gross_fees_usd"] / (c2m.loc[M, "tx_per_day"] * pd.Period(M, "M").days_in_month)

    # ---- METHODS.md: the evidence in detail, claim by claim ----
    blocks = []
    for cl in claims:
        b = [f"### {cl.id.upper()}. {cl.title.rstrip('.')}", ""]
        if cl.scope:
            b += [f"*{cl.scope}*", ""]
        b += ["**Evidence for**", ""] + [f"- {x}" for x in cl.evidence] + [""]
        b += ["**Caveats**", ""] + [f"- {x}" for x in cl.against] + [""]
        b += [f"**What would change our mind:** {cl.change} Today: {cl.today}", ""]
        links = [f"[{c.title}](DASHBOARD.md#{c.id})" for c in cl.cards if c.chart]
        if links:
            b += ["Charts: " + " · ".join(links), ""]
        blocks.append("\n".join(b))

    # ---- THESIS.md: one row per claim: the evidence for, the evidence against, what would change our mind ----
    def first_chart(cl):
        return next((c.id for c in cl.cards if c.chart), "")

    ai_x = n5["tokens_last_week"] / n5["tokens_first_week"]
    dex = n4["dex_growth_12m_pct"]
    dex_move = f"{'fell' if dex < 0 else 'rose'} {pct(abs(dex))}"
    q = n6["quarter"].replace("Q", " Q")
    ye = n3["year_earlier"]
    evidence_for = {
        "c1": f"Intents earned {pct(n1['intents_share_net_last3_pct'])} of NEAR's protocol revenue over {n1['last3']}, "
              f"against {pct(n1['intents_share_net_last3_year_ago_pct'])} a year earlier.",
        "c2": f"{pct(n2['intents_share_last_pct'], 1)} of L1 transactions went to the Intents contract in {ml(n2['last'])}, "
              f"against {pct(n2['intents_share_year_ago_pct'], 1)} a year earlier.",
        "c3": f"1Click carried {fmt(n3['volume_usd'], 'usd')} of swaps for {compact(n3['unique_users'])} users in "
              f"{ml(n3['month'])}, against {fmt(ye['volume_usd'], 'usd')} and {compact(ye['unique_users'])} a year earlier. "
              f"The top 10 users made up {pct(n3['top10_share_pct'])} of volume.",
        "c4": f"Intents handled {pct(n4['share_last_pct'])} of native cross-chain swap volume in {ml(n4['last'])}, against "
              f"{pct(n4['share_year_ago_pct'])} a year earlier, while total DEX volume {dex_move}.",
        "c5": f"NEAR AI served {compact(n5['tokens_last_week'])} tokens on OpenRouter in the week to {dl(n5['last_week'])}, "
              f"{ai_x:.0f}× its first full week. {compact(n5['ai_stake_near'])} NEAR was staked for AI credits on "
              f"{dl(n5['ai_stake_date'])}.",
        "c6": f"Burns and buybacks offset {pct(n6['capture_ratio_pct'], 1)} of new NEAR in {q}, against "
              f"{pct(n6['capture_ratio_year_ago_pct'], 1)} a year earlier.",
    }
    change_table = md_table(["Claim", "For", "Against", "What would change our mind"],
                            [[f"**{cl.id.upper()}.** [{cl.title.rstrip('.')}](DASHBOARD.md#{first_chart(cl)})",
                              evidence_for[cl.id], AGAINST[cl.id], cl.change] for cl in claims])

    base_cut = be(base.breakeven_month)
    kp = [
        f"**Most of NEAR's money now comes from Intents, not the L1.** Intents earned {pct(n1['intents_share_net_last3_pct'])} "
        f"of NEAR's protocol revenue over {n1['last3']}, against {pct(n1['intents_share_net_last3_year_ago_pct'])} a year earlier.",
        f"**Intents is winning share.** It handled {pct(n4['share_last_pct'])} of native cross-chain swap volume in "
        f"{ml(n4['last'])}, up from {pct(n4['share_year_ago_pct'])} a year earlier, while total DEX volume {dex_move}.",
        f"**NEAR AI is small but real.** It served {compact(n5['tokens_last_week'])} tokens on OpenRouter in the week to "
        f"{dl(n5['last_week'])}, {ai_x:.0f}× its first full week, and customers have staked {compact(n5['ai_stake_near'])} NEAR "
        f"to pay for it.",
        f"**The token is beginning to capture that value.** Burns and buybacks offset {pct(n6['capture_ratio_pct'], 1)} of new "
        f"NEAR in {n6['quarter'].replace('Q', ' Q')}, up from {pct(n6['capture_ratio_year_ago_pct'], 1)} a year earlier."
        + (f" If Intents revenue keeps growing at a fading rate, they offset all of it by {base_cut}."
           if is_month(base.breakeven_month) else ""),
    ]
    N["key_points"] = [re.sub(r"\*\*", "", k) for k in kp]
    ai_rows = [r for r in ctx["c6m"].itertuples() if not r.partial_month and r.ai_stake_added_near > 1e5]

    # Where it could go: the scenarios in three sentences
    horizon = f"{cfg['horizon_years']} years"
    q_from, q_to = (x.replace("Q", " Q") for x in str(base.trend_window).split(" -> "))
    outlook = [f"Measured in NEAR, Intents revenue grew at a yearly rate of {pct(100 * base.start_growth_per_year)} between "
               f"{q_from} and {q_to}.",
               f"If that growth halves every {base.half_life_years:g} years, burns and buybacks "
               + (f"offset all new NEAR by {be(base.breakeven_month)}." if is_month(base.breakeven_month)
                  else f"do not offset all new NEAR within {horizon}."),
               "If it holds, " + (f"they get there by {be(bull.breakeven_month)}." if is_month(bull.breakeven_month)
                                  else f"they still do not get there within {horizon}."),
               "If revenue stops growing, " + (f"they get there by {be(bear.breakeven_month)}."
                                               if is_month(bear.breakeven_month)
                                               else f"they do not get there within the {horizon} we project.")]
    no_cut = S.loc[("no_cut", "base")]
    if is_month(base.breakeven_month) and is_month(no_cut.breakeven_month):
        outlook.append(f"Without HSP-029, the first of those dates moves to {be(no_cut.breakeven_month)}.")

    others = ["the " + c if c.startswith("Government") else c for c in facts["near_ai_customers"]["value"] if c != "Brave"]
    customers = f"NEAR AI's homepage also names {and_list(others)} as users of its private AI." if others else ""

    n3c = N["c3"]
    return {
        "asof": dl(asof), "key_points": "\n".join(f"- {k}" for k in kp),
        # thesis
        "thesis_breakeven": (f" If Intents revenue keeps growing, even at a fading rate, they would offset all of it by "
                             f"{base_cut}." if is_month(base.breakeven_month) else ""),
        # problem
        "l1_fees_usd": usd_(c1m.loc[M, "l1_gross_fees_usd"]), "kc_share": pct(n2["kaiching_share_mar_2026_pct"]),
        "kc_month": ml(str(pd.Period(n2["kaiching_stop"], "M") - 1)),
        "l1_tx_first": compact(c2.tx_per_day.iloc[0]), "l1_tx_first_month": ml(c2.month.iloc[0]),
        "l1_tx_last": compact(c2.tx_per_day.iloc[-1]), "l1_tx_last_month": ml(c2.month.iloc[-1]),
        # three layers
        "l1_fee": "1 cent" if round(l1_fee_cents, 1) == 1 else f"{round(l1_fee_cents, 1):g} cents", "m": ml(M),
        "c2_share": pct(n2["intents_share_last_pct"], 1), "c2_month": ml(n2["last"]),
        "c2_share_yago": pct(n2["intents_share_year_ago_pct"], 1),
        "int_vol": fmt(vm[M], "usd", 2), "int_vol_x": f"{vol_x:.1f}×",
        "int_chains": f"{n3c['origin_chains']:.0f}", "int_users": compact(n3c["unique_users"]),
        "int_apps": f"{n3c['referrers']:.0f}",
        "ai_last": compact(n5["tokens_last_week"]), "ai_last_week": dl(n5["last_week"]),
        "brave_date": dl(facts["brave_leo"]["date"]), "brave_model": facts["brave_leo"]["model"],
        "brave_mau": facts["brave_leo"]["brave_monthly_users"],
        # token
        "infl_date": dl(infl_date), "infl_from": f"{infl_from:.3g}%", "infl_to": f"{infl_to:.3g}%",
        "hsp_passed": dl(h["vote_passed"]), "hsp_target": f"{100 * h['target_rate']:g}%", "hsp_end": ml(tl["hsp_029_ramp_end"]),
        "bb_date": dl(tl["buybacks_start"]), "gas_txt": gas_txt, "ai_open": dl(n5["ai_staking_open"]),
        "stake_total": compact(mf["total_stake_near"]), "stake_pct": pct(mf["staked_share_of_supply_pct"], 1),
        "stake_date": dl(mf["stake_snapshot_date"]),
        "flow_caption": flow.memo, "outlook": " ".join(outlook),
        "c6_ratio": pct(n6["capture_ratio_pct"], 1), "c6_q": n6["quarter"].replace("Q", " Q"),
        "c6_ratio_yago": pct(n6["capture_ratio_year_ago_pct"], 1),
        "incl_ai": " and ".join(f"{pct(r.capture_ratio_incl_ai_stake_pct)} in {ml(r.month)}" for r in ai_rows),
        # context
        "c4_share": pct(n4["share_last_pct"]), "c4_yago": pct(n4["share_year_ago_pct"]), "c4_last": ml(n4["last"]),
        "c4_growth": pct(n4["intents_growth_12m_pct"]),
        "c4_dex_move": dex_move,
        # the last year, business by business
        "ai_first_week": dl(n5["first_week"]), "ai_month_tokens": compact(mf["ai_tokens"]),
        "ai_staked": compact(mf["ai_staked_month_end_near"]),
        "offset_m": pct(c6m.loc[M, "capture_ratio_pct"], 1), "offset_y": pct(c6m.loc[Y, "capture_ratio_pct"], 1),
        "context_table": context_table, "ai_annual": fmt(n5["est_revenue_annual_usd"], "usd"), "customers": customers,
        # each claim: for, against, what would change our mind
        "change_table": change_table,
        "c1_share3": pct(n1["intents_share_net_last3_pct"]), "c1_last3": n1["last3"],
        "c1_share3_yago": pct(n1["intents_share_net_last3_year_ago_pct"]),
        "ai_x": f"{ai_x:.0f}×", "mech_months": str(mech_months),
        # METHODS.md
        "evidence": "\n".join(blocks).rstrip(),
        "sc_s": sc.sentence, "sc_note": sc.note, "win_s": wc.sentence,
        "scenario_table": md_table(["Issuance path", "Scenario", "Revenue growth a year at start (NEAR terms)",
                                    "Growth then", "After 1 year", "After 3 years", "Supply after 6 years", "Breakeven",
                                    "Revenue at breakeven vs today"], scen_rows),
        "window_table": md_table(["Trailing window", "Growth a year (NEAR terms)", "With HSP-029, growth fades",
                                  "With HSP-029, growth holds", "At 2.5%, growth fades", "At 2.5%, growth holds"], win_rows),
        "tl_s": tlc.sentence, "mechanisms_table": mech_table,
        "l1_gross_method": l1_method, "l1_start": ml(c2.month.iloc[0]), "crosschecks": crosschecks(),
        "oneclick_share": pct(n3c["oneclick_share_of_intents_pct"]), "c3_month": ml(n3c["month"]),
        "untraced": compact(n6["cumulative_revenue_near"] - n6["held_near"]),
        "sources": "\n".join(src_lines),
    }


def write(N, ctx, SRC, AGAINST, ss, cfg, ws) -> list:
    """Write THESIS.md and METHODS.md; returns their paths."""
    texts = {name: tpl.read_text() for name, tpl in TEMPLATES.items()}
    for name, text in texts.items():
        check_template(text, str(TEMPLATES[name].relative_to(ROOT)))
    vals = values(N, ctx, SRC, AGAINST, ss, cfg, ws)
    out = []
    for name, text in texts.items():
        (ROOT / name).write_text(text.format_map(vals))
        out.append(ROOT / name)
    return out
