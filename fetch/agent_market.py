"""NEAR Agent Market (first-party): platform statistics and the public agent listing.

Endpoints (public, no key):
  - https://market.near.ai/v1/platform/stats: current totals only, so each run appends one dated
    row to stats.jsonl (running it daily builds a short history).
  - https://market.near.ai/v1/agents: every listed agent, with created_at, delivered_jobs,
    success_rate, category, runtime and payment options. created_at gives a listing history.
    Saved as a dated snapshot, agents_<date>.json. Text fields (bios, schemas) are dropped.

Usage: python -m fetch.agent_market
"""
from __future__ import annotations

import json
import time

from fetch.common import RAW, http_get, record_fetch, utc_now, write_json

URL = "https://market.near.ai/v1/platform/stats"
AGENTS_URL = "https://market.near.ai/v1/agents"
KEEP = ["agent_id", "handle", "name", "category", "created_at", "updated_at", "listing_status", "delivered_jobs",
        "success_rate", "runtime", "payable_with", "owner_account_id", "response_time_seconds_median", "tags"]


def fetch_agents() -> list[dict]:
    agents, offset = [], 0
    while True:
        page = http_get(AGENTS_URL, params={"limit": 50, "offset": offset, "sort": "recent"}).json()["agents"]
        agents += [{k: a.get(k) for k in KEEP} for a in page]
        if len(page) < 50:
            return agents
        offset += 50
        time.sleep(0.5)


def main() -> None:
    agents = fetch_agents()
    day = utc_now()[:10]
    write_json(RAW / "agent_market" / f"agents_{day}.json", agents)
    print(f"  {len(agents)} listed agents")
    stats = http_get(URL).json()
    row = {"fetched_at": utc_now(), **stats}
    path = RAW / "agent_market" / "stats.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(f"  {row}")
    record_fetch("agent_market", url=URL, rows=sum(1 for _ in path.open()), agents_url=AGENTS_URL, agents=len(agents))


if __name__ == "__main__":
    main()
