"""NEAR Intents Explorer API: every successful 1Click swap, newest to oldest.

Source: https://docs.near-intents.org/integration/distribution-channels/1click-api/explorer/introduction
Needs NEAR_INTENTS_JWT in .env. Rate limit: 1 request per 5 seconds per partner.

Raw pages are written to data/raw/explorer/pages/ as gzipped JSON lines. Progress is
saved after every page in data/raw/explorer/state.json, so an interrupted run resumes
where it stopped.

The address cursor can skip: on the first full backfill, one page ended on 2026-05-22 and the next
started on 2026-04-08, with no error. `--fill-gaps` finds such jumps (a time gap between two pages
far larger than a page's own span) and refills each one by walking a time window instead of the
cursor (endTimestampUnix moves back to the oldest swap seen; overlaps are deduplicated later).
Parameters are from the OpenAPI spec: https://explorer.near-intents.org/api/v0/openapi.yaml

Usage:
  python -m fetch.explorer                 # backfill full history (resumable)
  python -m fetch.explorer --max-pages 2   # quick test
  python -m fetch.explorer --update        # fetch swaps newer than the newest already saved
  python -m fetch.explorer --fill-gaps     # find and refill pages the cursor skipped (resumable)
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import time
from datetime import datetime, timezone

import requests

from fetch.common import RAW, http_get, read_json, record_fetch, require_env, utc_now, write_json, write_jsonl_gz

BASE = "https://explorer.near-intents.org/api/v0/transactions"
PAGE_SIZE = 1000  # API maximum
STATUSES = "SUCCESS"  # volume and user metrics use completed swaps only
MIN_INTERVAL = 6.0  # seconds between requests (limit is 1 per 5 s; 5.3 s still drew occasional 429s)

OUT = RAW / "explorer"
PAGES = OUT / "pages"
STATE = OUT / "state.json"

_last_request = 0.0


def fetch_page(token: str, params: dict) -> list[dict]:
    global _last_request
    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    while True:
        try:
            r = http_get(BASE, params=params, headers={"Authorization": f"Bearer {token}"}, backoff=12.0)
            return r.json()
        except requests.ConnectionError as e:
            # Laptop asleep or offline (e.g. DNS failure): wait it out instead of stopping the backfill.
            print(f"  connection lost ({e.__class__.__name__}); retrying in 60s", flush=True)
            time.sleep(60)


def ts(row: dict) -> int:
    return int(row.get("createdAtTimestamp") or 0)


def iso(t: int | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def run(token: str, state: dict, key: str, extra_params: dict, page_prefix: str, max_pages: int | None) -> None:
    s = state[key]
    pages_this_run = 0
    while not s.get("done"):
        params = {"numberOfTransactions": PAGE_SIZE, "statuses": STATUSES, "direction": "next", **extra_params}
        cursor = s.get("cursor")
        if cursor:
            params["lastDepositAddress"] = cursor["address"]
            if cursor.get("memo"):
                params["lastDepositMemo"] = cursor["memo"]

        rows = fetch_page(token, params)
        if not rows:
            s["done"] = True
            s["finished_at"] = utc_now()
            write_json(STATE, state)
            break

        last = rows[-1]
        new_cursor = {"address": last.get("depositAddress"), "memo": last.get("depositMemo")}
        if cursor and new_cursor == cursor:
            raise SystemExit("Cursor did not advance; stopping to avoid a loop.")

        s["pages"] = s.get("pages", 0) + 1
        write_jsonl_gz(PAGES / f"{page_prefix}{s['pages']:06d}.jsonl.gz", rows)
        s["rows"] = s.get("rows", 0) + len(rows)
        page_ts = [ts(r) for r in rows if ts(r)]
        if page_ts:
            s["newest"] = max(s.get("newest") or 0, max(page_ts))
            s["oldest"] = min(s.get("oldest") or 10**12, min(page_ts))
        s["cursor"] = new_cursor
        write_json(STATE, state)

        pages_this_run += 1
        print(f"[{key}] page {s['pages']}: +{len(rows)} rows (total {s['rows']:,}), "
              f"reached {iso(s.get('oldest'))}", flush=True)
        if max_pages and pages_this_run >= max_pages:
            print(f"[{key}] stopped after {max_pages} page(s) (--max-pages); rerun to resume.")
            break


def find_gaps(min_hours: float = 1.0, min_ratio: float = 20.0) -> list[dict]:
    """Time jumps between consecutive backfill pages that are much larger than the page's own span."""
    gaps, prev = [], None
    for f in sorted(glob.glob(str(PAGES / "b*.jsonl.gz"))):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            ts_ = [ts(json.loads(line)) for line in fh]
        ts_ = [t for t in ts_ if t]
        if prev:
            gap, span = prev[1] - max(ts_), max(prev[2], 1)
            if gap > min_hours * 3600 and gap / span > min_ratio:
                gaps.append({"after_page": os.path.basename(prev[0]), "newer": prev[1], "older": max(ts_),
                             "newer_iso": iso(prev[1]), "older_iso": iso(max(ts_))})
        prev = (f, min(ts_), max(ts_) - min(ts_))
    return gaps


def fill(token: str, state: dict, gap: dict) -> None:
    """Refill one gap by walking a time window back from its newer edge (resumable via state)."""
    key = f"fill_{gap['newer']}_{gap['older']}"
    s = state.setdefault(key, {"gap": gap, "end": gap["newer"] + 1, "pages": 0, "rows": 0})
    while not s.get("done"):
        rows = fetch_page(token, {"numberOfTransactions": PAGE_SIZE, "statuses": STATUSES, "direction": "next",
                                  "startTimestampUnix": gap["older"] - 1, "endTimestampUnix": s["end"]})
        if rows:
            s["pages"] += 1
            write_jsonl_gz(PAGES / f"g{gap['newer']}_{s['pages']:06d}.jsonl.gz", rows)
            s["rows"] += len(rows)
            oldest = min(ts(r) for r in rows if ts(r))
            if oldest + 1 >= s["end"]:
                raise SystemExit(f"Window did not move back from {iso(s['end'])}; stopping to avoid a loop.")
            s["end"] = oldest + 1  # endTimestampUnix is non-inclusive; same-second swaps are deduplicated later
            print(f"[{key}] page {s['pages']}: +{len(rows)} rows (total {s['rows']:,}), reached {iso(oldest)}", flush=True)
        if len(rows) < PAGE_SIZE:
            s["done"], s["finished_at"] = True, utc_now()
        write_json(STATE, state)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--update", action="store_true", help="fetch swaps newer than those already saved")
    ap.add_argument("--fill-gaps", action="store_true", help="find and refill pages the cursor skipped")
    args = ap.parse_args()

    token = require_env("NEAR_INTENTS_JWT")
    state = read_json(STATE, {"statuses": STATUSES, "backfill": {}})
    # state.json is in the repo (the build reads it) but the raw pages are not. On a copy without the pages, the
    # progress in state.json describes a download made elsewhere, so the full download starts again.
    if state["backfill"].get("pages") and not glob.glob(str(PAGES / "b*.jsonl.gz")):
        if args.update or args.fill_gaps:
            raise SystemExit("The raw pages are not on this machine (data/raw/explorer/pages/ is not in the repo), so "
                             "there is nothing to update or refill. Run the full download first: make fetch-explorer")
        print("No raw pages on this machine: starting the full download again.", flush=True)
        state = {"statuses": STATUSES, "backfill": {}}

    if args.fill_gaps:
        gaps = find_gaps()
        print(f"{len(gaps)} gap(s) in the backfill pages: " + "; ".join(f"{g['older_iso']} .. {g['newer_iso']}" for g in gaps), flush=True)
        for g in gaps:
            fill(token, state, g)
        state["gaps"] = gaps
        write_json(STATE, state)
        record_fetch("explorer_gaps", endpoint=BASE, gaps=len(gaps),
                     rows=sum(state[f"fill_{g['newer']}_{g['older']}"]["rows"] for g in gaps))
        return

    if args.update:
        newest = max(state["backfill"].get("newest") or 0,
                     *[u.get("newest") or 0 for u in state.get("updates", [])], 0)
        if not newest:
            raise SystemExit("Nothing saved yet; run the backfill first.")
        key = f"update_{utc_now()}"
        state.setdefault("updates", [])
        state[key] = {"since": iso(newest)}
        run(token, state, key, {"startTimestampUnix": newest}, f"u{newest}_", args.max_pages)
        state["updates"].append({"key": key, "newest": state[key].get("newest")})
        write_json(STATE, state)
    else:
        run(token, state, "backfill", {}, "b", args.max_pages)

    b = state["backfill"]
    record_fetch("explorer", endpoint=BASE, statuses=STATUSES, rows=b.get("rows"),
                 oldest=iso(b.get("oldest")), newest=iso(b.get("newest")), complete=bool(b.get("done")))


if __name__ == "__main__":
    main()
