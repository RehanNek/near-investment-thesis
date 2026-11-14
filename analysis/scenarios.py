"""Scenarios: when could value capture offset all new NEAR supply?

Projects the capture ratio month by month from the last complete quarter. Labelled as projections,
not findings.

Revenue growth starts from Intents' trailing growth rate, measured from the data: the annualised
change in Intents revenue (in NEAR) over the last `trend.quarters` complete quarters.
  bear  no growth from the last quarter's level
  base  the trailing rate, fading: it halves every `half_life_years`
  bull  the trailing rate, held

Each scenario runs under two issuance paths:
  hsp_029  HSP-029: 2.5% -> 1.6%, phased over 24 months after a 90-day grace period (passed, not
           yet in force). The main path.
  no_cut   issuance stays at today's 2.5% (the check if HSP-029 isn't implemented)

  rate(t)     = issuance rate on the path
  minted(t)   = supply(t) x rate(t) / 12, with supply growing by minted - L1 burn
  captured(t) = L1 burn + Intents revenue in NEAR
  ratio(t)    = captured / minted; breakeven is the first month with ratio >= 100%

L1 burn is held at the last quarter's level, scaled up from the day all gas is burned (HSP-027,
dated from protocol config: analysis.common.gas_burn_switch). NEAR newly staked for NEAR AI is left
out (lumpy, withdrawable; see C6).

A sensitivity table shows how the breakeven date moves with the trailing window used.

Outputs: data/derived/scenarios_monthly.csv, scenarios_summary.csv, scenarios_window_sensitivity.csv
"""
from __future__ import annotations

import pandas as pd
import yaml

from analysis.common import RAW, ROOT, gas_burn_switch, save

POLICIES = {"hsp_029": "With HSP-029 (2.5% → 1.6%)", "no_cut": "If HSP-029 isn't implemented (stays 2.5%)"}


def inflation_path(cfg: dict, start: pd.Period, months: int, with_cut: bool) -> list[float]:
    inf = cfg["inflation"]
    cur = inf["current_rate"]
    if not with_cut:
        return [cur] * months
    h = inf["hsp_029"]
    ramp_start = pd.Period(h["ramp_start"], freq="M")
    step = (cur - h["target_rate"]) / h["ramp_months"]
    out = []
    for i in range(months):
        k = ((start + i) - ramp_start).n
        out.append(cur if k < 0 else max(h["target_rate"], cur - step * (k + 1)))
    return out


def trailing_growth(q: pd.DataFrame, n: int) -> tuple[float, str]:
    """Annualised growth of Intents revenue (NEAR) over the last n complete quarters."""
    r = q.intents_revenue_near.values
    return (r[-1] / r[-1 - n]) ** (4 / n) - 1, f"{q.quarter.iloc[-1 - n]} -> {q.quarter.iloc[-1]}"


def project(cfg, start, supply0, rev0, burn0, g0, half_life, with_cut):
    """Monthly projection. Returns (rows, summary dict)."""
    months = int(cfg["horizon_years"] * 12)
    rates = inflation_path(cfg, start, months, with_cut)
    switch, before = gas_burn_switch()
    switch_m = pd.Period(switch, freq="M") if switch else None
    gb = (1 + cfg["l1_burn_growth_per_year"]) ** (1 / 12) - 1
    supply, rev, burn, breakeven, rev_at_be, rows, ratios = supply0, rev0, burn0, None, None, [], []
    for i in range(months):
        m = start + i
        burn_now = burn / before if switch_m is not None and m >= switch_m else burn
        minted = supply * rates[i] / 12
        ratio = 100 * (rev + burn_now) / minted
        ratios.append(ratio)
        g_year = 0.0 if g0 == 0 else (g0 if half_life is None else g0 * 0.5 ** (i / 12 / half_life))
        rows.append({"month": str(m), "inflation_rate": rates[i], "growth_per_year": g_year, "minted_near": minted,
                     "intents_revenue_near": rev, "l1_burn_near": burn_now, "capture_ratio_pct": ratio,
                     "supply_near": supply})
        if breakeven is None and ratio >= 100:
            breakeven, rev_at_be = str(m), rev / rev0
        supply += minted - burn_now
        rev *= (1 + g_year) ** (1 / 12)
        burn *= 1 + gb
    return rows, {"start_capture_ratio_pct": ratios[0], "ratio_after_1y_pct": ratios[11],
                  "ratio_after_3y_pct": ratios[35], "supply_after_6y_bn": supply / 1e9,
                  "breakeven_month": breakeven or f"not within {cfg['horizon_years']} years",
                  "revenue_vs_start_at_breakeven": rev_at_be}


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    q = pd.read_csv(ROOT / "data" / "derived" / "c6_capture_quarterly.csv")
    q = q[q.months == 3].reset_index(drop=True)  # complete quarters
    qL = q.iloc[-1]
    rev0, burn0 = qL.intents_revenue_near / 3, qL.l1_burned_near / 3
    supply0 = pd.read_csv(RAW / "bigquery" / "blocks_daily.csv").end_of_day_total_supply_near.iloc[-1]
    start = pd.Period(qL.quarter, freq="Q").asfreq("M", "end") + 1
    g_trend, window = trailing_growth(q, cfg["trend"]["quarters"])

    rows, summary = [], []
    for policy, label in POLICIES.items():
        for name, sc in cfg["scenarios"].items():
            g0 = 0.0 if sc["growth"] == "none" else g_trend
            hl = sc.get("half_life_years")
            r, s = project(cfg, start, supply0, rev0, burn0, g0, hl, policy == "hsp_029")
            rows += [{"policy": policy, "policy_label": label, "scenario": name, **x} for x in r]
            summary.append({"policy": policy, "policy_label": label, "scenario": name, "start_growth_per_year": g0,
                            "half_life_years": hl, "trend_window": window if g0 else "", "start_month": str(start), **s})

    sens = []
    for n in cfg["trend"]["sensitivity_quarters"]:
        if n + 1 > len(q) or q.intents_revenue_near.iloc[-1 - n] <= 0:
            continue
        g, w = trailing_growth(q, n)
        row = {"window": w, "quarters": n, "growth_per_year": g}
        for policy in POLICIES:
            for kind, hl in (("held", None), ("fading", cfg["scenarios"]["base"]["half_life_years"])):
                _, s = project(cfg, start, supply0, rev0, burn0, g, hl, policy == "hsp_029")
                row[f"breakeven_{kind}_{policy}"] = s["breakeven_month"]
        sens.append(row)

    save(pd.DataFrame(rows), "scenarios_monthly")
    s = pd.DataFrame(summary)
    save(s, "scenarios_summary")
    w = pd.DataFrame(sens)
    save(w, "scenarios_window_sensitivity")
    print(f"Start: {qL.quarter}: Intents revenue {rev0:,.0f} NEAR/month, L1 burn {burn0:,.0f} NEAR/month, "
          f"supply {supply0 / 1e9:.3f}B NEAR. Trailing growth ({window}): {100 * g_trend:+.0f}% a year")
    print(s.drop(columns=["policy_label"]).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print("\nBreakeven by trailing window:")
    print(w.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


if __name__ == "__main__":
    main()
