"""make verify: spot-check random slices of the committed data against the live sources (~1 minute).

Picks random past days (or months, blocks, tokens) from the committed raw data, fetches the same
points from each source now, and compares them. A settled past value should not change, so a
difference there ("differs") means either our copy is wrong or the source rewrote its history.

Some values are known to settle after the fact. revenue.near.org's monthly net Intents revenue (after
partner payouts) keeps rising for about three months after a month ends: between the Nov 5 and
Nov 7, 2026 pages, Aug rose 0.08%, Sep 0.86% and Oct 1.29%; daily fees and volume did not move.
A difference inside such a window is shown as "revised", with both values, and doesn't fail the run.

DefiLlama's category totals (all bridge aggregators, all DEXs) are sums over the protocols it lists, and
it keeps adding protocols together with their history. Between its Nov 5 and Nov 14, 2026 responses it
added five protocols to the bridge-aggregator category, which raised that category's past daily totals
by a median of 4%, while the protocols already in our copy changed by less than 0.001%. So a category
total is checked like for like (the live values of the protocols in the committed copy, summed), and the
live total over every protocol listed now is shown next to it as "revised" when it has moved.

  Source                     What is checked                                       Tolerance
  NEAR RPC, archival         end-of-day total supply at BigQuery's last block of one exact (0.0001%)
                             day, and that day's net new supply (minted - burned)
  NEAR RPC                   live protocol config (issuance cap, gas burn)           exact
  revenue.near.org           daily Intents fees and volume, monthly Intents revenue  0.5% (last 3
                                                                                   months: revised)
  NEAR Intents 1Click API    chain and symbol of supported tokens                    exact
  NEAR Intents Explorer API  swap count and volume for one early day, and for one     exact (0.0001%)
                             recent 15-minute window of the committed per-swap
                             table; needs NEAR_INTENTS_JWT, skipped without it
  DefiLlama                  daily Intents volume and revenue, THORChain volume;     2% (category
                             bridge-aggregator and all-DEX volume for the            totals: revised)
                             protocols in the committed copy
  NearBlocks                 daily transactions and NEAR price                       0.5%
  CoinGecko                  daily NEAR price                                        1%
  OpenRouter                 daily tokens NEAR AI served                             1%

Sources with no history (agent listings, model catalogs, GitHub) are not checked: there is no past
value to compare. BigQuery itself needs a Google sign-in, so its numbers are checked through the
archival RPC instead.

Exit code: 0 if nothing differs (skips and revisions are fine), 1 if any check differs.
Usage: python -m verify.spot_check [--seed N]     (the seed is printed, so a run can be repeated)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pandas as pd
import requests

from analysis.c3_intents_breadth import read_swaps
from fetch.common import RAW, http_get, load_env
from fetch.revenue_tracker import URL as TRACKER_URL, extract_payload, extract_series

DER = RAW.parent / "derived"
YOCTO = 10**24
RPC = "https://rpc.mainnet.near.org"          # endpoints from https://docs.near.org/api/rpc/providers
ARCHIVAL = "https://archival-rpc.mainnet.near.org"


@dataclass
class Row:
    source: str
    what: str
    committed: object
    live: object
    tol: float | None = None   # relative tolerance for numbers; None = must be equal
    note: str = ""
    settling: bool = False     # a value the source is known to revise (see the docstring): a difference is "revised"

    @property
    def result(self) -> str:
        if self.live is None:
            return "skipped"
        if isinstance(self.committed, (int, float)) and isinstance(self.live, (int, float)):
            if self.committed == self.live:
                return "match"
            base = max(abs(self.committed), 1e-12)
            if abs(self.live - self.committed) / base <= (self.tol or 0.0):
                return "match"
            return "revised" if self.settling else "differs"
        return "match" if self.committed == self.live else "differs"

    @property
    def diff(self) -> str:
        if isinstance(self.committed, (int, float)) and isinstance(self.live, (int, float)) and self.committed:
            d = 100 * (self.live - self.committed) / abs(self.committed)
            return "0%" if d == 0 else f"{d:+.2f}%" if abs(d) >= 0.01 else f"{d:+.1e}%"
        return ""


def num(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, str):
        return v
    a = abs(v)
    if a < 1000 and float(v).is_integer():
        return f"{int(v):,}"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{v / div:,.4f}{suf}"
    return f"{v:,.4f}" if a < 100 else f"{v:,.2f}"


def skip(source: str, what: str, why: str) -> Row:
    return Row(source, what, None, None, note=why)


def picks(rng: random.Random, items, k: int):
    items = sorted(items)
    return sorted(rng.sample(items, min(k, len(items))))


# ---------- first-party: NEAR RPC ----------

def rpc_call(url: str, method: str, params, attempts: int = 3, wait: float = 8.0) -> dict:
    """JSON-RPC call that gives up quickly (the public archival node is heavily rate-limited)."""
    for i in range(attempts):
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": "verify", "method": method, "params": params}, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            out = r.json()
            if "error" in out:
                raise RuntimeError(str(out["error"])[:200])
            return out["result"]
        except (requests.RequestException, ValueError):
            if i == attempts - 1:
                raise
            time.sleep(wait * (i + 1))
    raise RuntimeError("unreachable")


def check_archival_supply(rng: random.Random) -> list[Row]:
    src = "NEAR RPC (archival) vs BigQuery"
    bd = pd.read_csv(RAW / "bigquery" / "blocks_daily.csv")
    flows = pd.read_csv(RAW / "bigquery" / "supply_flows_daily.csv").set_index("block_date")
    bd = bd.reset_index(drop=True)
    ok = bd.index[(bd.block_date >= "2025-01-02") & bd.block_date.isin(flows.index)][:-1]  # last day may be partial
    rows = []
    # One day = two calls. The public archival node rate-limits hard, so keep calls few and stop at the first refusal.
    for i in picks(rng, list(ok), 1):
        day, prev = bd.loc[i], bd.loc[i - 1]
        try:
            s_prev = int(rpc_call(ARCHIVAL, "block", {"block_id": int(prev.last_height)}, wait=10)["header"]["total_supply"]) / YOCTO
            time.sleep(2)
            s_day = int(rpc_call(ARCHIVAL, "block", {"block_id": int(day.last_height)}, wait=10)["header"]["total_supply"]) / YOCTO
        except Exception as e:  # noqa: BLE001 - report, don't fail the run
            why = ("archival RPC is rate-limiting (HTTP 429); wait a few minutes and run again" if "429" in str(e)
                   else f"archival RPC unavailable ({e.__class__.__name__}: {str(e)[:60]})")
            return [skip(src, f"Total supply and net new supply, {day.block_date}", why)]
        f = flows.loc[day.block_date]
        rows.append(Row(src, f"End-of-day total supply, {day.block_date} (block {int(day.last_height):,})",
                        float(day.end_of_day_total_supply_near), s_day, 1e-6))
        rows.append(Row(src, f"Net new supply (minted - burned), {day.block_date}",
                        float(f.minted_near - f.burned_near), s_day - s_prev, 1e-6))
    return rows


def frac(v) -> str:
    return f"{v[0]}/{v[1]}"


def check_protocol_config(rng: random.Random) -> list[Row]:
    src = "NEAR RPC (live config)"
    pc = json.loads((RAW / "rpc" / "protocol_changes.json").read_text())
    cfg = rpc_call(RPC, "EXPERIMENTAL_protocol_config", {"finality": "final"})
    note = f"committed as of {pc['end']}; a difference means the protocol changed since"
    return [Row(src, "Issuance cap (max_inflation_rate)", frac(pc["latest"]["max_inflation_rate"]),
                frac(cfg["max_inflation_rate"]), note=note),
            Row(src, "Gas paid to called contracts (burnt_gas_reward)", frac(pc["latest"]["burnt_gas_reward"]),
                frac(cfg["runtime_config"]["transaction_costs"]["burnt_gas_reward"]), note=note)]


# ---------- first-party: revenue.near.org, 1Click, Explorer ----------

def check_revenue_tracker(rng: random.Random) -> list[Row]:
    src = "revenue.near.org"
    snap = sorted(p for p in (RAW / "revenue_tracker").iterdir() if p.is_dir())[-1]
    live = extract_series(extract_payload(http_get(TRACKER_URL).text))
    rows = []
    for series, date_key, fields, k in (("totalFeesSeries", "date_at", ("fees_usd",), 2),
                                        ("intentVolumeSeries", "date_at", ("volume_usd",), 2),
                                        ("revenueSeries", "period_month", ("revenue_usd", "revenue_near"), 2)):
        old = {r[date_key][:10]: r for r in json.loads((snap / f"{series}.json").read_text())}
        new = {r[date_key][:10]: r for r in live.get(series, [])}
        daily = date_key == "date_at"
        dates = sorted(set(old) & set(new))[:-3 if daily else -1]  # drop partial days / the partial month
        for d in picks(rng, dates, k):
            # monthly net revenue settles for ~3 months after the month ends (see the module docstring)
            settling = not daily and pd.Period(d[:7], "M") >= pd.Period(snap.name[:7], "M") - 3
            for fld in fields:
                label = {"fees_usd": "Intents gross fees (USD)", "volume_usd": "Intents volume (USD)",
                         "revenue_usd": "NEAR's Intents revenue (USD)", "revenue_near": "NEAR's Intents revenue (NEAR)"}[fld]
                rows.append(Row(src, f"{label}, {d if daily else d[:7]}", float(old[d][fld]), float(new[d][fld]), 0.005,
                                note=(f"within 3 months of the committed snapshot ({snap.name}): net revenue is still "
                                      "settling" if settling else f"committed snapshot {snap.name}"), settling=settling))
    return rows


def check_oneclick_tokens(rng: random.Random) -> list[Row]:
    src = "NEAR Intents 1Click API"
    old = {t["assetId"]: t for t in json.loads((RAW / "oneclick" / "tokens.json").read_text())}
    new = {t["assetId"]: t for t in http_get("https://1click.chaindefuser.com/v0/tokens").json()}
    rows = []
    for a in picks(rng, list(old), 4):
        rows.append(Row(src, f"Chain / symbol of {a}", f"{old[a]['blockchain']} / {old[a]['symbol']}",
                        f"{new[a]['blockchain']} / {new[a]['symbol']}" if a in new else "not listed now"))
    return rows


EXPLORER = "https://explorer.near-intents.org/api/v0/transactions"  # parameters from its OpenAPI spec


def explorer_window(token: str, start: int, end: int) -> list[dict]:
    """All successful swaps created in the whole seconds start <= t < end, up to 1,000.

    The request is two seconds wider on each side and the rows are then cut here by whole second, the same way the
    committed table is cut. The API compares its bounds more finely than a second: asked for swaps after second t,
    it also returned one created during second t, which a whole-second cut of our table left out.
    """
    r = http_get(EXPLORER, headers={"Authorization": f"Bearer {token}"}, backoff=12.0,
                 params={"numberOfTransactions": 1000, "statuses": "SUCCESS", "direction": "next",
                         "startTimestampUnix": start - 2, "endTimestampUnix": end + 2})
    return [x for x in r.json() if start <= int(x.get("createdAtTimestamp") or 0) < end]


def swap_stats(rows: list[dict]) -> tuple[int, float]:
    uniq = {f"{r.get('depositAddress')}|{r.get('depositMemo') or ''}|{r.get('createdAtTimestamp')}": r for r in rows}
    vol = sum(float(r["amountInUsd"]) for r in uniq.values() if r.get("amountInUsd") not in (None, ""))
    return len(uniq), vol


def check_explorer(rng: random.Random) -> list[Row]:
    src = "NEAR Intents Explorer API"
    load_env()
    token = os.environ.get("NEAR_INTENTS_JWT", "")
    if not token:
        return [skip(src, "Swaps per day (C3)", "needs NEAR_INTENTS_JWT in .env (partner key)")]
    rows = []
    # 1) A whole early day: few enough swaps for one request, compared with the committed c3_daily.csv
    dd = pd.read_csv(DER / "c3_daily.csv")
    small = dd[(dd.swaps >= 50) & (dd.swaps < 900) & dd.complete_day.astype(bool)]
    for _, d in pd.DataFrame([small.iloc[i] for i in picks(rng, range(len(small)), 1)]).iterrows():
        t0 = int(pd.Timestamp(d.date, tz="UTC").timestamp())
        n, vol = swap_stats(explorer_window(token, t0, t0 + 86400))
        rows.append(Row(src, f"Successful 1Click swaps, {d.date}", float(d.swaps), float(n), 1e-6, note="vs data/derived/c3_daily.csv"))
        rows.append(Row(src, f"1Click volume (USD), {d.date}", float(d.volume_usd), vol, 1e-4, note="vs data/derived/c3_daily.csv"))
    # 2) A recent 15-minute window, compared with the committed per-swap table (one row per swap)
    sw = read_swaps(columns=["ts", "volume_usd"])
    if len(sw):
        hi = int(sw.ts.max()) - 86400
        t0 = rng.randrange(hi - 180 * 86400, hi)
        local = sw[(sw.ts >= t0) & (sw.ts < t0 + 900)]
        time.sleep(6)  # API limit: one request per 5 s
        n, vol = swap_stats(explorer_window(token, t0, t0 + 900))
        when = pd.Timestamp(t0, unit="s").strftime("%Y-%m-%d %H:%M")
        rows.append(Row(src, f"Successful 1Click swaps, 15 min from {when} UTC", float(len(local)), float(n), 1e-6,
                        note="vs data/raw/explorer/swaps/"))
        rows.append(Row(src, f"1Click volume (USD), 15 min from {when} UTC", float(local.volume_usd.sum()), vol, 1e-4,
                        note="vs data/raw/explorer/swaps/"))
    return rows


# ---------- third-party ----------

SINCE = int(pd.Timestamp("2025-01-01").timestamp())  # the analysis covers 2025 onwards


def check_defillama(rng: random.Random) -> list[Row]:
    src = "DefiLlama"
    rows = []
    for name, path, label in (("near_intents_volume", "/summary/dexs/near-intents", "NEAR Intents volume"),
                              ("near_intents_revenue", "/summary/fees/near-intents?dataType=dailyRevenue", "NEAR Intents revenue"),
                              ("bridge_aggregators_overview", "/overview/bridge-aggregators", "Bridge-aggregator volume"),
                              ("dexs_overview", "/overview/dexs", "All-DEX volume")):
        old_d = json.loads((RAW / "defillama" / f"{name}.json").read_text())
        new_d = http_get("https://api.llama.fi" + path, timeout=120).json()
        old, new = dict(map(tuple, old_d["totalDataChart"])), dict(map(tuple, new_d["totalDataChart"]))
        days = [t for t in sorted(set(old) & set(new))[:-3] if t >= SINCE and old[t]]  # the analysis window, non-zero
        category = name.endswith("_overview")  # a total over every protocol DefiLlama lists in the category
        if category:
            ob = {t: v for t, v in old_d["totalDataChartBreakdown"]}
            nb = {t: v for t, v in new_d["totalDataChartBreakdown"]}
            days = [t for t in days if t in ob and t in nb]
        for t in picks(rng, days, 1):
            day = pd.Timestamp(t, unit="s").strftime("%Y-%m-%d")
            if not category:
                rows.append(Row(src, f"{label}, {day}", float(old[t]), float(new[t]), 0.02))
                continue
            # Like for like: the committed total against the live values of the same protocols.
            same = float(sum(nb[t].get(p) or 0 for p in ob[t]))
            rows.append(Row(src, f"{label}, {day} (same {len(ob[t]):,} protocols)", float(old[t]), same, 0.02))
            added, gone = sum(p not in ob[t] for p in nb[t]), sum(p not in nb[t] for p in ob[t])
            rows.append(Row(src, f"{label}, {day} (all listed now)", float(old[t]), float(new[t]), 0.02, settling=True,
                            note=f"DefiLlama's list for this category changed for that day ({added} added, {gone} no longer "
                                 "listed); the row above compares the same protocols"))
        if name == "dexs_overview":  # the C4 peer set comes from the per-protocol breakdown
            days = [t for t in sorted(set(ob) & set(nb))[:-3]
                    if t >= SINCE and ob[t].get("THORChain DEX") and "THORChain DEX" in nb[t]]
            for t in picks(rng, days, 1):
                day = pd.Timestamp(t, unit="s").strftime("%Y-%m-%d")
                rows.append(Row(src, f"THORChain DEX volume (C4 peer), {day}", float(ob[t]["THORChain DEX"]),
                                float(nb[t]["THORChain DEX"]), 0.02))
    return rows


def check_nearblocks(rng: random.Random) -> list[Row]:
    src = "NearBlocks"
    old = {r["date"][:10]: r for r in json.loads((RAW / "nearblocks" / "charts.json").read_text())}
    new = {r["date"][:10]: r for r in http_get("https://api.nearblocks.io/v1/charts", timeout=120).json()["charts"]}
    days = [d for d in sorted(set(old) & set(new)) if d >= "2025-01-01"][:-2]
    rows = []
    for d in picks(rng, days, 2):
        rows.append(Row(src, f"L1 transactions, {d}", float(old[d]["txns"]), float(new[d]["txns"]), 0.005))
        rows.append(Row(src, f"NEAR price (USD), {d}", float(old[d]["near_price"]), float(new[d]["near_price"]), 0.005))
    return rows


def check_coingecko(rng: random.Random) -> list[Row]:
    src = "CoinGecko"
    day = lambda ms: pd.Timestamp(ms, unit="ms").strftime("%Y-%m-%d")
    old_d = json.loads((RAW / "coingecko" / "near_market_chart_365d.json").read_text())
    new_d = http_get("https://api.coingecko.com/api/v3/coins/near/market_chart", backoff=30.0,
                     params={"vs_currency": "usd", "days": 365, "interval": "daily"}).json()
    old = {day(t): v for t, v in old_d["prices"]}
    new = {day(t): v for t, v in new_d["prices"]}
    days = sorted(set(old) & set(new))[:-2]
    return [Row(src, f"NEAR price (USD), {d}", float(old[d]), float(new[d]), 0.01) for d in picks(rng, days, 2)]


def check_openrouter(rng: random.Random) -> list[Row]:
    src = "OpenRouter"
    snap = sorted(p for p in (RAW / "openrouter").iterdir() if p.is_dir())[-1]
    html = http_get("https://openrouter.ai/provider/near-ai").text
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    blob = "".join(json.loads('"' + c + '"') for c in chunks)
    m = re.search(r'"chartData":\[\{', blob)
    if not m:
        return [skip(src, "NEAR AI tokens per day", "chart data not found on the page (layout changed?)")]
    live = json.JSONDecoder().raw_decode(blob, m.end() - 2)[0]
    tot = lambda r: float(sum(r["ys"].values()))
    old = {r["x"][:10]: tot(r) for r in json.loads((snap / "near_ai_tokens_daily.json").read_text())}
    new = {r["x"][:10]: tot(r) for r in live}
    days = sorted(set(old) & set(new))[:-2]
    return [Row(src, f"Tokens NEAR AI served, {d}", old[d], new[d], 0.01, note=f"committed snapshot {snap.name}")
            for d in picks(rng, days, 2)]


CHECKS = [check_archival_supply, check_protocol_config, check_revenue_tracker, check_oneclick_tokens, check_explorer,
          check_defillama, check_nearblocks, check_coingecko, check_openrouter]
SOURCE_OF = {"check_archival_supply": "NEAR RPC (archival) vs BigQuery", "check_protocol_config": "NEAR RPC (live config)",
             "check_revenue_tracker": "revenue.near.org", "check_oneclick_tokens": "NEAR Intents 1Click API",
             "check_explorer": "NEAR Intents Explorer API", "check_defillama": "DefiLlama", "check_nearblocks": "NearBlocks",
             "check_coingecko": "CoinGecko", "check_openrouter": "OpenRouter"}


def run(check, seed: int) -> list[Row]:
    try:
        return check(random.Random(f"{seed}-{check.__name__}"))  # each check has its own stream: same picks for a seed
    except Exception as e:  # noqa: BLE001 - one source being down shouldn't hide the others
        return [skip(SOURCE_OF[check.__name__], "(whole source)", f"could not fetch: {e.__class__.__name__}: {str(e)[:80]}")]


def main() -> None:
    ap = argparse.ArgumentParser(description="Spot-check committed data against live sources.")
    ap.add_argument("--seed", type=int, default=int(os.environ.get("SEED") or random.randrange(10**6)))
    args = ap.parse_args()
    t0 = time.time()
    print(f"Spot-checking committed data against live sources (seed {args.seed}; repeat with SEED={args.seed} make verify)\n")
    with ThreadPoolExecutor(max_workers=len(CHECKS)) as ex:
        rows = [r for rs in ex.map(lambda c: run(c, args.seed), CHECKS) for r in rs]

    w = (32, 62, 18, 18, 10, 8)
    head = ("Source", "What", "Committed", "Live", "Diff", "Result")
    print("  ".join(h.ljust(n) for h, n in zip(head, w)))
    print("  ".join("-" * n for n in w))
    for r in rows:
        cells = (r.source, r.what, num(r.committed), num(r.live), r.diff, r.result)
        print("  ".join(str(c)[:n].ljust(n) for c, n in zip(cells, w)))
        if r.note and r.result != "match":
            print(" " * (w[0] + 2) + f"↳ {r.note}")
    n = {k: sum(r.result == k for r in rows) for k in ("match", "revised", "differs", "skipped")}
    print(f"\n{n['match']} match, {n['revised']} revised, {n['differs']} differ, {n['skipped']} skipped, "
          f"in {time.time() - t0:.0f} s.")
    if n["revised"]:
        print("Revised: the source has updated a value it is known to revise (a recent month that is still settling, or a "
              "category total that gained protocols). Expected; the run still passes.")
    if n["differs"]:
        print("A difference means the committed data and the live source disagree about a past value: either our copy "
              "is wrong, or the source revised its history. Re-fetch that source (`make fetch`) and rebuild (`make charts`).")
    sys.exit(1 if n["differs"] else 0)


if __name__ == "__main__":
    main()
