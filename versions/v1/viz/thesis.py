"""Write THESIS.md from viz/thesis_template.md (called by viz/build.py, so `make charts` rebuilds it).

The template holds the prose. Every number enters through a {placeholder} filled here from what
viz/build.py computed (headline numbers, chart sentences, each claim's evidence for and against), from data/derived/ and
data/raw/, and from data/manual/facts.yaml (sourced facts that no API exposes).

check_template() stops the build if the template's own text contains a digit outside a short list
of labels (C1-C6, L1, 1Click, HSP-0xx, Part n, list numbering, code spans, chart paths), so a
hand-typed figure can't slip into the document.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import yaml

from viz.svg import as_date, compact, fmt

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "viz" / "thesis_template.md"
FACTS = ROOT / "data" / "manual" / "facts.yaml"
DER, RAW = ROOT / "data" / "derived", ROOT / "data" / "raw"

ALLOWED = [r"<!--.*?-->", r"`[^`\n]*`", r"site/charts/[\w-]+\.svg", r"\bC[1-6]\b", r"\bL1\b", r"1Click",
           r"HSP-0\d\d", r"\bPart [1-4]\b", r"^\d+\. "]


def check_template(text: str) -> None:
    body = re.sub(r"\{[a-z0-9_]+\}", "", text)
    for pat in ALLOWED:
        body = re.sub(pat, "", body, flags=re.M)
    bad = [m.group(0).strip() for m in re.finditer(r"[^\n]{0,30}\d[^\n]{0,30}", body)]
    if bad:
        raise SystemExit("viz/thesis_template.md has hand-typed figures; use a {placeholder} instead:\n  "
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


def values(N: dict, ctx: dict, SRC: dict, RISKS: list, ss: pd.DataFrame, cfg: dict, ws: pd.DataFrame) -> dict:
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
    recent = []
    if gas and (as_date(asof) - as_date(gas["first_day_after"])).days < 183:
        recent.append(f"the full gas burn has only been live since {dl(gas['first_day_after'])}")
    elif not gas:
        recent.append("the full gas burn is newly live")
    recent.append(f"HSP-029's cut to {100 * h['target_rate']:g}% is not yet in force")
    recent_txt = ", and ".join(recent)
    recent_txt = recent_txt[0].upper() + recent_txt[1:]

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

    def be(m):
        return ml(m) if re.match(r"\d{4}-\d{2}$", str(m)) else str(m)

    S = ss.set_index(["policy", "scenario"])
    base, bull, bear = S.loc[("hsp_029", "base")], S.loc[("hsp_029", "bull")], S.loc[("hsp_029", "bear")]
    scen_rows = [[r.policy_label, r.scenario, pct(100 * r.start_growth_per_year),
                  "–" if r.start_growth_per_year == 0 else
                  (f"halves every {r.half_life_years:g} years" if pd.notna(r.half_life_years) else "held"),
                  pct(r.ratio_after_1y_pct, 1), pct(r.ratio_after_3y_pct, 1), f"{r.supply_after_6y_bn:.3f}B",
                  be(r.breakeven_month),
                  "–" if pd.isna(r.revenue_vs_start_at_breakeven) else f"{r.revenue_vs_start_at_breakeven:.1f}×"]
                 for r in ss.itertuples()]

    def assumption(r):
        g = pct(100 * r.start_growth_per_year)
        if r.start_growth_per_year == 0:
            return "Intents revenue stops growing"
        if pd.notna(r.half_life_years):
            return f"Intents revenue growth starts at {g} a year and halves every {r.half_life_years:g} years"
        return f"Intents revenue keeps growing {g} a year"
    scen_short = md_table(["Scenario", "Assumption (revenue in NEAR terms)", "All new NEAR offset by",
                           "If HSP-029 isn't implemented"],
                          [[n.capitalize(), assumption(S.loc[("hsp_029", n)]), be(S.loc[("hsp_029", n)].breakeven_month),
                            be(S.loc[("no_cut", n)].breakeven_month)] for n in ("bear", "base", "bull")])

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

    # ---- the latest complete month, and a year earlier (context table, three layers) ----
    M = mf["month"]
    Y = str(pd.Period(M, "M") - 12)
    c1m = ctx["c1"].set_index("month")
    vm = ctx["vol_m"].set_index("month").intents_volume_usd
    c4m = ctx["c4"].set_index("month")
    c6m = ctx["c6m"].set_index("month")
    c2m = c2.set_index("month")
    m3 = pd.read_csv(DER / "c3_monthly.csv").set_index("month")

    def pair(get, f):
        out = []
        for m in (M, Y):
            try:
                v = get(m)
                out.append(f(v) if pd.notna(v) else "–")
            except KeyError:
                out.append("–")
        return out
    usd_ = lambda v: fmt(v, "usd")
    ctx_rows = [
        ["Intents swap volume", *pair(lambda m: vm[m], lambda v: fmt(v, "usd", 2))],
        ["Fees paid by Intents users", *pair(lambda m: c1m.loc[m, "intents_gross_fees_usd"], usd_)],
        ["NEAR's share of those fees", *pair(lambda m: c1m.loc[m, "intents_revenue_usd"], usd_)],
        ["Distinct 1Click users", *pair(lambda m: m3.loc[m, "unique_users"], compact)],
        ["Apps sending swaps through 1Click", *pair(lambda m: m3.loc[m, "active_referrers"], lambda v: f"{v:.0f}")],
        ["Intents share of native cross-chain swap volume", *pair(lambda m: c4m.loc[m, "intents_share_of_peers_pct"], lambda v: pct(v))],
        ["L1 transactions a day", *pair(lambda m: c2m.loc[m, "tx_per_day"], compact)],
        ["NEAR issued", *pair(lambda m: c6m.loc[m, "minted_near"], compact)],
        ["Share of new NEAR offset by burns and buybacks", *pair(lambda m: c6m.loc[m, "capture_ratio_pct"], lambda v: pct(v, 1))],
    ]
    context_table = md_table(["", ml(M), ml(Y)], ctx_rows)
    vol_x = vm[M] / vm[Y]
    l1_fee_cents = 100 * c1m.loc[M, "l1_gross_fees_usd"] / (c2m.loc[M, "tx_per_day"] * pd.Period(M, "M").days_in_month)

    # ---- the evidence, claim by claim ----
    blocks = []
    for cl in claims:
        b = [f"### {cl.id.upper()}. {cl.title.rstrip('.')}", ""]
        if cl.scope:
            b += [f"*{cl.scope}*", ""]
        b += ["**Evidence for**", ""] + [f"- {x}" for x in cl.evidence] + [""]
        b += ["**Evidence against**", ""] + [f"- {x}" for x in cl.against] + [""]
        b += [f"**What would change our mind:** {cl.change}", ""]
        links = [f"[{c.title}](DASHBOARD.md#{c.id})" for c in cl.cards if c.chart]
        if links:
            b += ["Charts: " + " · ".join(links), ""]
        blocks.append("\n".join(b))

    tw = pd.read_csv(DER / "c5_openrouter_tokens_weekly.csv")
    tw = tw[tw.complete_week.astype(bool)].reset_index(drop=True)
    ai_x = n5["tokens_last_week"] / n5["tokens_first_week"]
    dex = n4["dex_growth_12m_pct"]
    base_cut = be(base.breakeven_month)
    kp = [
        f"**Most of NEAR's money now comes from Intents, not the L1.** Intents earned {pct(n1['intents_share_net_last3_pct'])} "
        f"of NEAR's protocol revenue over {n1['last3']}, against {pct(n1['intents_share_net_last3_year_ago_pct'])} a year earlier.",
        f"**Intents is winning share.** It handled {pct(n4['share_last_pct'])} of native cross-chain swap volume in "
        f"{ml(n4['last'])}, up from {pct(n4['share_year_ago_pct'])} a year earlier, while total DEX volume "
        f"{'fell' if dex < 0 else 'rose'} {pct(abs(dex))}.",
        f"**NEAR AI is small but real.** It served {compact(n5['tokens_last_week'])} tokens on OpenRouter in the week to "
        f"{dl(n5['last_week'])}, {ai_x:.0f}× its first full week, and customers have staked {compact(n5['ai_stake_near'])} NEAR "
        f"to pay for it.",
        f"**The token is beginning to capture that value.** Burns and buybacks offset {pct(n6['capture_ratio_pct'], 1)} of new "
        f"NEAR in {n6['quarter'].replace('Q', ' Q')}, up from {pct(n6['capture_ratio_year_ago_pct'], 1)} a year earlier. If "
        f"Intents revenue keeps growing at a fading rate, they offset all of it by {base_cut}.",
    ]
    N["key_points"] = [re.sub(r"\*\*", "", k) for k in kp]
    ai_rows = [r for r in ctx["c6m"].itertuples() if not r.partial_month and r.ai_stake_added_near > 1e5]
    early = pd.read_csv(DER / "c6_capture_quarterly.csv").query("months == 3")
    early = early[early.quarter < "2025Q4"]
    early_period = f"{early.quarter.iloc[0].replace('Q', ' Q')}–Q{early.quarter.iloc[-1][-1]}"
    early = early.capture_ratio_pct.mean()

    n3c = N["c3"]
    return {
        "asof": dl(asof), "key_points": "\n".join(f"- {k}" for k in kp),
        # problem
        "l1_tx_first": compact(c2.tx_per_day.iloc[0]), "l1_tx_first_month": ml(c2.month.iloc[0]),
        "l1_tx_last": compact(c2.tx_per_day.iloc[-1]), "l1_tx_last_month": ml(c2.month.iloc[-1]),
        # three layers
        "l1_fee": "1 cent" if round(l1_fee_cents, 1) == 1 else f"{round(l1_fee_cents, 1):g} cents", "m": ml(M),
        "c2_share": pct(n2["intents_share_last_pct"], 1), "c2_month": ml(n2["last"]),
        "c2_share_yago": pct(n2["intents_share_year_ago_pct"], 1),
        "int_vol": fmt(vm[M], "usd", 2), "int_vol_x": f"{vol_x:.1f}×", "int_fees": fmt(c1m.loc[M, "intents_gross_fees_usd"], "usd"),
        "int_chains": f"{n3c['origin_chains']:.0f}", "int_users": compact(n3c["unique_users"]),
        "ai_first": compact(n5["tokens_first_week"]), "ai_first_week": dl(n5["first_week"]),
        "ai_last": compact(n5["tokens_last_week"]), "ai_last_week": dl(n5["last_week"]),
        "brave_date": dl(facts["brave_leo"]["date"]), "brave_model": facts["brave_leo"]["model"],
        "brave_mau": facts["brave_leo"]["brave_monthly_users"],
        # token
        "infl_date": dl(infl_date), "infl_from": f"{infl_from:.3g}%", "infl_to": f"{infl_to:.3g}%",
        "hsp_passed": dl(h["vote_passed"]), "hsp_target": f"{100 * h['target_rate']:g}%", "hsp_end": ml(tl["hsp_029_ramp_end"]),
        "bb_date": dl(tl["buybacks_start"]), "gas_txt": gas_txt, "ai_open": dl(n5["ai_staking_open"]),
        "flow_sentence": flow.sentence, "early_ratio": pct(early), "early_period": early_period,
        "c6_ratio": pct(n6["capture_ratio_pct"], 1), "c6_q": n6["quarter"].replace("Q", " Q"),
        "c6_ratio_yago": pct(n6["capture_ratio_year_ago_pct"], 1), "c6_cut_part": pct(n6["share_of_rise_from_cut_pct"]),
        "incl_ai": " and ".join(f"{pct(r.capture_ratio_incl_ai_stake_pct)} in {ml(r.month)}" for r in ai_rows),
        # context
        "c4_share": pct(n4["share_last_pct"]), "c4_yago": pct(n4["share_year_ago_pct"]), "c4_last": ml(n4["last"]),
        "c4_growth": pct(n4["intents_growth_12m_pct"]),
        "c4_dex_move": f"{'fell' if dex < 0 else 'rose'} {pct(abs(dex))}",
        "context_table": context_table, "ai_annual": fmt(n5["est_revenue_annual_usd"], "usd"),
        # risks, view
        "risks": "\n".join(f"- **{a}.** {b}" for a, b in RISKS),
        "c1_share3": pct(n1["intents_share_net_last3_pct"]), "c1_last3": n1["last3"],
        "c1_share3_yago": pct(n1["intents_share_net_last3_year_ago_pct"]),
        "ai_x": f"{ai_x:.0f}×", "c5_stake": compact(n5["ai_stake_near"]),
        "mech_months": str(mech_months), "recent_mechanisms": recent_txt,
        "base_cut": base_cut, "base_half_life": f"{base.half_life_years:g}", "scenario_short": scen_short,
        # evidence
        "evidence": "\n".join(blocks).rstrip(),
        # appendix
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


def write(N, ctx, SRC, RISKS, ss, cfg, ws) -> Path:
    text = TEMPLATE.read_text()
    check_template(text)
    out = ROOT / "THESIS.md"
    out.write_text(text.format_map(values(N, ctx, SRC, RISKS, ss, cfg, ws)))
    return out
