"""Write THESIS.md from viz/thesis_template.md (called by viz/build.py, so `make charts` rebuilds it).

The template holds the prose. Every number enters through a {placeholder} filled here from what
viz/build.py computed (headline numbers, chart sentences, counterpoints), from data/derived/ and
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


def values(N: dict, T: dict, SRC: dict, RISKS: list, ss: pd.DataFrame, cfg: dict, ws: pd.DataFrame) -> dict:
    facts = yaml.safe_load(FACTS.read_text())
    pc = protocol_changes()
    c2 = pd.read_csv(DER / "c2_l1_monthly.csv")
    c2 = c2[~c2.partial_month.astype(bool)]
    summ = pd.read_csv(DER / "c5_summary.csv").set_index("metric").value
    mf, n1, n2, n3, n4, n5, n6, tl = (N[k] for k in ("money_flow", "c1", "c2", "c3", "c4", "c5", "c6", "timeline"))
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
    recent_txt = ", ".join(recent)
    recent_txt = recent_txt[0].upper() + recent_txt[1:]

    if gas:
        share_before = 1 - frac(gas["from"])
        l1_method = (f"L1 gross fees = burn ÷ {share_before:g} before {dl(gas['first_day_after'])}, while "
                     f"{100 * frac(gas['from']):g}% of gas went to the called contract, and = burn from that day, when all "
                     "gas is burned. Before the switch this is an upper bound, because some gas was always burned in full, "
                     "so C1's Intents share is conservative.")
    else:
        l1_method = "L1 gross fees = burn ÷ the burned share of gas set in the protocol config."

    def be(m):
        return ml(m) if re.match(r"\d{4}-\d{2}$", str(m)) else str(m)

    S = ss.set_index(["policy", "scenario"])
    base, bull = S.loc[("hsp_029", "base")], S.loc[("hsp_029", "bull")]
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

    customers = [("the " + c if c.startswith("Government") else c)
                 for c in facts["near_ai_customers"]["value"] if c != "Brave"]
    sources = sorted({v for v in SRC.values()}, key=lambda s: s[0].lower())
    src_lines = [f"- {link(l, u, w)}" for l, u, w in sources]
    src_lines += [f"- {link('NEAR AI homepage (customers)', facts['near_ai_customers']['source'], 'checked ' + facts['near_ai_customers']['checked'])}",
                  f"- {link('NEAR AI blog: private inference for Brave Leo', facts['brave_leo']['source'], 'checked ' + facts['brave_leo']['checked'])}",
                  f"- {link('HSP-027 coverage (gas rebate removed)', facts['hsp_027']['source'], 'checked ' + facts['hsp_027']['checked'])}",
                  "- Sourced facts no API exposes: `data/manual/facts.yaml`. Fetch log with dates: `data/raw/_manifest.json`."]

    n3c = N["c3"]
    status = (f"**Preliminary.** {T['c3_note1']}" if n3c["preliminary"] else T["c3_note1"])
    return {
        "asof": dl(asof),
        "l1_tx_first": compact(c2.tx_per_day.iloc[0]), "l1_tx_first_month": ml(c2.month.iloc[0]),
        "l1_tx_last": compact(c2.tx_per_day.iloc[-1]), "l1_tx_last_month": ml(c2.month.iloc[-1]),
        "c2_share": pct(n2["intents_share_last_pct"], 1),
        "mf_volume": fmt(mf["intents_volume_usd"], "usd"), "mf_fees": fmt(mf["intents_fees_usd"], "usd"),
        "mf_quarter": mf["quarter"].replace("Q", " Q"),
        "c4_share": pct(n4["share_last_pct"]), "c5_tokens": compact(n5["tokens_last_week"]),
        "c5_stake": compact(n5["ai_stake_near"]),
        "takeaways": "\n".join(f"- {t}" for t in N["takeaways"]),
        "flow_sentence": T["flow"],
        **{k: v for k, v in T.items() if re.match(r"c\d_(s\d|cp)$", k)},
        "c3_status": status,
        "c5_models": f"{summ['NEAR AI Cloud models in catalog']:.0f}",
        "c5_tee": f"{summ['  of which TEE-verifiable (private inference)']:.0f}",
        "brave_date": dl(facts["brave_leo"]["date"]), "brave_model": facts["brave_leo"]["model"],
        "brave_mau": facts["brave_leo"]["brave_monthly_users"],
        "customers": ", ".join(customers[:-1]) + " and " + customers[-1],
        "ironclaw_stars": compact(summ["IronClaw GitHub stars"]),
        "tl_s": T["tl_s"], "mechanisms_table": mech_table,
        "sc_s": T["sc_s"], "sc_note": T["sc_note"],
        "scenario_table": md_table(["Issuance path", "Scenario", "Revenue growth a year at start (NEAR terms)",
                                    "Growth then", "After 1 year", "After 3 years", "Supply after 6 years", "Breakeven",
                                    "Revenue at breakeven vs today"], scen_rows),
        "win_s": T["win_s"],
        "window_table": md_table(["Trailing window", "Growth a year (NEAR terms)", "With HSP-029, growth fades",
                                  "With HSP-029, growth holds", "At 2.5%, growth fades", "At 2.5%, growth holds"], win_rows),
        # verdict
        "c1_share3": pct(n1["intents_share_net_last3_pct"]), "c1_last3": n1["last3"],
        "c1_share3_yago": pct(n1["intents_share_net_last3_year_ago_pct"]),
        "c4_last": ml(n4["last"]), "c4_growth": pct(n4["intents_growth_12m_pct"]),
        "c4_dex_fall": pct(-n4["dex_growth_12m_pct"]),
        "ai_open": dl(n5["ai_staking_open"]),
        "c6_ratio": pct(n6["capture_ratio_pct"], 1), "c6_q": n6["quarter"].replace("Q", " Q"),
        "c6_ratio_yago": pct(n6["capture_ratio_year_ago_pct"], 1), "c6_cut_part": pct(n6["share_of_rise_from_cut_pct"]),
        "mech_months": str(mech_months), "recent_mechanisms": recent_txt,
        "base_cut": be(base.breakeven_month), "bull_cut": be(bull.breakeven_month),
        "base_growth": pct(100 * base.start_growth_per_year), "base_half_life": f"{base.half_life_years:g}", "topref": pct(n3c["top_referrer_share_pct"]), "top_staker": pct(n5["largest_staker_pct"]),
        # watching
        "signposts": md_table(["Signpost", "Claim", "Latest", "Earlier", "Direction", "We'd turn cautious if…"],
                              [[s["signpost"], s["claim"], s["latest"], s["earlier"], s["direction"], s["cautious_if"]]
                               for s in N["signposts"]]),
        "risks": "\n".join(f"- **{a}.** {b}" for a, b in RISKS),
        # appendix
        "l1_gross_method": l1_method, "l1_start": ml(c2.month.iloc[0]), "crosschecks": crosschecks(),
        "oneclick_share": pct(n3c["oneclick_share_of_intents_pct"]), "c3_month": ml(n3c["month"]),
        "untraced": compact(n6["cumulative_revenue_near"] - n6["held_near"]),
        "sources": "\n".join(src_lines),
    }


def write(N, T, SRC, RISKS, ss, cfg, ws) -> Path:
    text = TEMPLATE.read_text()
    check_template(text)
    out = ROOT / "THESIS.md"
    out.write_text(text.format_map(values(N, T, SRC, RISKS, ss, cfg, ws)))
    return out
