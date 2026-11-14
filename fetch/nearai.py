"""NEAR AI (first-party): on-chain staking for NEAR AI products, and the NEAR AI Cloud model catalog.

1. stake.dao: the House of Stake staking contract for NEAR AI products
   (source: github.com/houseofstake/house-of-stake-contracts/tree/main/staking-contract; its README
   calls it "pooled staking tied to NEAR AI products and prices"). Users lock NEAR for a product
   tier (subscriptions), or pay NEAR directly (purchases); the contract stakes locked NEAR with
   allowlisted validators (e.g. nearai.pool.near). All views are public RPC calls.
   Saved per run: products (+ their prices and any farm pools), validators, locks, subscriptions,
   purchases, registered accounts, and every account's farm positions (NEAR staked for NEAR AI
   Cloud credits, with created_ns), one RPC call per registered account.
2. NEAR AI Cloud public catalog: https://cloud-api.near.ai/v1/model/list (models with pricing) and
   /v1/models, plus /v1/services.

Output: data/raw/nearai/<YYYY-MM-DD>/*.json

Usage: python -m fetch.nearai
"""
from __future__ import annotations

import base64
import json
import time

from fetch.common import RAW, http_get, record_fetch, utc_now, write_json
from fetch.rpc import call

CONTRACT = "stake.dao"
CLOUD = "https://cloud-api.near.ai"
# Bulk read-only view calls go to FastNEAR's free RPC (listed at docs.near.org/api/rpc/providers);
# rpc.mainnet.near.org rate-limits a few hundred calls in a row.
RPC_URL = "https://free.rpc.fastnear.com"


def view(method: str, args: dict | None = None):
    r = call("query", {"request_type": "call_function", "finality": "final", "account_id": CONTRACT,
                       "method_name": method, "args_base64": base64.b64encode(json.dumps(args or {}).encode()).decode()},
             RPC_URL)
    return json.loads(bytes(r["result"]).decode())


def paged(method: str, page: int = 100, **extra) -> list:
    rows, i = [], 0
    while True:
        batch = view(method, {"from_index": i, "limit": page, **extra})
        rows += batch
        if len(batch) < page:
            return rows
        i += page


def main() -> None:
    out = RAW / "nearai" / utc_now()[:10]
    data = {
        "config": view("get_config"),
        "version": view("get_version"),
        "products": paged("get_products"),
        "validators": paged("get_validators"),
        "locks": paged("get_locks"),
        "subscriptions": paged("get_subscriptions"),
        "purchases": paged("get_purchases"),
        "accounts": paged("get_account_ids", page=500),
    }
    prices, farms = [], []
    for p in data["products"]:
        for pid in p.get("price_ids", []):
            price = view("get_price", {"price_id": pid})
            if price:
                prices.append(price)
            farm = view("get_farm_pool", {"price_id": pid})
            if farm:
                farms.append({"price_id": pid, **farm})
    data["prices"], data["farm_pools"] = prices, farms
    positions = []
    for i, acct in enumerate(data["accounts"]):
        positions += paged("get_farm_positions_for_account", page=50, account_id=acct)
        time.sleep(0.4)  # be gentle with the public RPC
    data["farm_positions"] = positions
    data["validator_revenue"] = [{"validator_id": v["validator_id"],
                                  "revenue_balance": view("get_revenue_balance_for_validator", {"validator_id": v["validator_id"]})}
                                 for v in data["validators"]]
    for name, rows in data.items():
        write_json(out / f"stake_dao_{name}.json", rows)

    for path in ("/v1/model/list", "/v1/models", "/v1/services"):
        write_json(out / f"cloud{path.replace('/', '_')}.json", http_get(CLOUD + path).json())

    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    print("  stake.dao:", counts)
    record_fetch("nearai", contract=CONTRACT, cloud=CLOUD, snapshot=str(out.relative_to(RAW.parent.parent)), counts=counts)


if __name__ == "__main__":
    main()
