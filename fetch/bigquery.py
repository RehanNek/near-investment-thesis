"""NEAR BigQuery public dataset (named in the track prompt): run the SQL files in queries/.

Dataset: bigquery-public-data.crypto_near_mainnet_us (docs: https://docs.near.org/data-infrastructure/big-query)
Auth: Google Application Default Credentials (`gcloud auth application-default login`).
Billing project: GCP_PROJECT_ID in .env (a free sandbox project works: 1 TB of queries per month).

Every query is dry-run first to get its size. Queries larger than --max-gb are refused, and
each real run carries a hard maximum_bytes_billed cap, so a mistake can't eat the monthly
allowance. Bytes processed are logged to data/raw/bigquery/_usage.jsonl.

Results go to data/raw/bigquery/<query name>.csv.

Usage:
  python -m fetch.bigquery --schema              # save table schemas (metadata only, free)
  python -m fetch.bigquery --dry-run             # estimate every query's size, run nothing
  python -m fetch.bigquery                       # run every query in queries/
  python -m fetch.bigquery l1_daily_activity     # run one query by name
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fetch.common import RAW, ROOT, record_fetch, require_env, utc_now, write_json

DATASET = "bigquery-public-data.crypto_near_mainnet_us"
QUERIES = ROOT / "queries"
OUT = RAW / "bigquery"
GB = 1024**3


def client():
    from google.cloud import bigquery  # imported lazily so other fetchers don't need Google auth
    return bigquery.Client(project=require_env("GCP_PROJECT_ID"))


def save_schema(bq) -> None:
    schema = {}
    for table in bq.list_tables(DATASET):
        t = bq.get_table(table.reference)
        schema[table.table_id] = {
            "type": t.table_type,
            "rows": t.num_rows,
            "size_gb": round((t.num_bytes or 0) / GB, 1),
            "partitioning": t.time_partitioning.field if t.time_partitioning else None,
            "clustering": t.clustering_fields,
            "columns": [_field(f) for f in t.schema],
        }
        print(f"  {table.table_id:28s} {t.table_type:5s} rows={t.num_rows}  size={schema[table.table_id]['size_gb']} GB  "
              f"partitioned by {schema[table.table_id]['partitioning']}")
    write_json(OUT / "schema.json", schema)


def _field(f):
    d = {"name": f.name, "type": f.field_type, "mode": f.mode}
    if f.fields:
        d["fields"] = [_field(x) for x in f.fields]
    return d


def run_query(bq, path: Path, max_gb: float, dry_run: bool) -> None:
    from google.cloud import bigquery
    sql = path.read_text(encoding="utf-8")
    estimate = bq.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    gb = estimate.total_bytes_processed / GB
    print(f"  {path.stem:34s} estimated {gb:8.2f} GB", end="")
    if dry_run:
        print()
        return
    if gb > max_gb:
        print(f"  -> REFUSED (over --max-gb {max_gb})")
        return
    cap = int(max(gb * 1.2, 0.01) * GB)
    job = bq.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=cap))
    df = job.result().to_dataframe()
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"{path.stem}.csv", index=False)
    billed = (job.total_bytes_billed or 0) / GB
    print(f"  -> {len(df):,} rows, billed {billed:.2f} GB")
    with (OUT / "_usage.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": utc_now(), "query": path.stem, "gb_billed": round(billed, 3), "rows": len(df)}) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="query names (default: all files in queries/)")
    ap.add_argument("--schema", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-gb", type=float, default=100.0, help="refuse queries estimated above this (default 100)")
    args = ap.parse_args()

    bq = client()
    if args.schema:
        save_schema(bq)
        return
    files = sorted(QUERIES.glob("*.sql"))
    if args.names:
        files = [f for f in files if f.stem in set(args.names)]
    for f in files:
        run_query(bq, f, args.max_gb, args.dry_run)
    if not args.dry_run:
        record_fetch("bigquery", dataset=DATASET, queries=[f.stem for f in files])


if __name__ == "__main__":
    main()
