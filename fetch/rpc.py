"""NEAR RPC (first-party): current protocol economics and revenue-wallet balances.

Endpoints from https://docs.near.org/api/rpc/providers:
  rpc.mainnet.near.org (current state), archival-rpc.mainnet.near.org (any past block).

Saves a dated snapshot of:
  - protocol config (inflation rate, epoch length, blocks per year)
  - latest final block (height, timestamp, total supply)
  - current validators and total stake (staking ratio)
  - balances of the revenue wallets named on revenue.near.org

Historical supply and wallet flows come from BigQuery; `block_at` below is a helper
for spot-checking a past block against BigQuery.

Usage: python -m fetch.rpc
"""
from __future__ import annotations

from fetch.common import RAW, http_post_json, record_fetch, utc_now, write_json

RPC = "https://rpc.mainnet.near.org"
ARCHIVAL = "https://archival-rpc.mainnet.near.org"
YOCTO = 10**24

# Wallets that receive NEAR's Intents revenue, as listed on revenue.near.org (2026-11-05).
REVENUE_WALLETS = [
    "fefundsadmin.sputnik-dao.near",   # near-intents.org / near.com front-end fees
    "buybacks.multisignature.near",    # NEAR buybacks
    "1csfundsadmin.sputnik-dao.near",  # 1Click fees
]


def call(method: str, params, url: str = RPC) -> dict:
    resp = http_post_json(url, {"jsonrpc": "2.0", "id": "thesis", "method": method, "params": params})
    if "error" in resp:
        raise RuntimeError(f"{method}: {resp['error']}")
    return resp["result"]


def block_at(height: int) -> dict:
    """Header of a past block (archival node)."""
    return call("block", {"block_id": height}, ARCHIVAL)["header"]


NEARAI_POOL = "nearai.pool.near"  # candidate pool behind NEAR AI Staking for Inference (not named in NEAR AI docs)


def pool_view(pool: str, method: str, args: dict | None = None):
    import base64
    import json
    r = call("query", {"request_type": "call_function", "finality": "final", "account_id": pool,
                       "method_name": method, "args_base64": base64.b64encode(json.dumps(args or {}).encode()).decode()})
    return json.loads(bytes(r["result"]).decode())


def pool_snapshot(pool: str) -> dict:
    accounts = pool_view(pool, "get_accounts", {"from_index": 0, "limit": 100})
    return {
        "pool": pool,
        "owner": pool_view(pool, "get_owner_id"),
        "total_staked_near": int(pool_view(pool, "get_total_staked_balance")) / YOCTO,
        "delegators": pool_view(pool, "get_number_of_accounts"),
        "accounts": sorted(({"account_id": a["account_id"],
                             "staked_near": int(a["staked_balance"]) / YOCTO,
                             "unstaked_near": int(a["unstaked_balance"]) / YOCTO} for a in accounts),
                           key=lambda a: -a["staked_near"]),
    }


def main() -> None:
    cfg = call("EXPERIMENTAL_protocol_config", {"finality": "final"})
    num, den = cfg["max_inflation_rate"]
    header = call("block", {"finality": "final"})["header"]
    supply = int(header["total_supply"]) / YOCTO

    validators = call("validators", [None])["current_validators"]
    total_stake = sum(int(v["stake"]) for v in validators) / YOCTO

    wallets = {}
    for account in REVENUE_WALLETS:
        try:
            acct = call("query", {"request_type": "view_account", "finality": "final", "account_id": account})
            wallets[account] = {"balance_near": int(acct["amount"]) / YOCTO,
                                "locked_near": int(acct["locked"]) / YOCTO}
        except RuntimeError as e:
            wallets[account] = {"error": str(e)[:200]}

    snapshot = {
        "fetched_at": utc_now(),
        "block_height": header["height"],
        "block_timestamp_ns": int(header["timestamp"]),
        "protocol_version": cfg["protocol_version"],
        "max_inflation_rate": f"{num}/{den}",
        "max_inflation_rate_pct": 100 * num / den,
        "protocol_reward_rate": cfg["protocol_reward_rate"],
        "epoch_length_blocks": cfg["epoch_length"],
        "num_blocks_per_year": cfg["num_blocks_per_year"],
        "total_supply_near": supply,
        "validators": len(validators),
        "total_stake_near": total_stake,
        "staked_share_of_supply_pct": 100 * total_stake / supply,
        "revenue_wallets": wallets,
        "nearai_pool": pool_snapshot(NEARAI_POOL),
    }
    out = RAW / "rpc" / f"snapshot_{snapshot['fetched_at'][:10]}.json"
    write_json(out, snapshot)
    for k in ("block_height", "max_inflation_rate", "total_supply_near", "validators",
              "total_stake_near", "staked_share_of_supply_pct"):
        print(f"  {k:28s} {snapshot[k]}")
    for a, w in wallets.items():
        print(f"  {a:34s} {w}")
    p = snapshot["nearai_pool"]
    top = p["accounts"][0] if p["accounts"] else {}
    print(f"  {NEARAI_POOL}: {p['total_staked_near']:,.0f} NEAR staked by {p['delegators']} delegators; "
          f"largest {top.get('account_id')} ({top.get('staked_near', 0):,.0f} NEAR)")
    record_fetch("rpc", url=RPC, block_height=header["height"], file=out.name)


if __name__ == "__main__":
    main()
