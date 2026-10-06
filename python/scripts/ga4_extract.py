"""Extract the GA4 obfuscated sample e-commerce dataset from BigQuery to local Parquet (bronze layer).

Source: bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_YYYYMMDD
        (Google Merchandise Store, 2020-11-01 to 2021-01-31, one table per day)
Target: data/raw/ga4/event_date=YYYYMMDD/events.parquet  (Hive-partitioned)

The nested GA4 schema (event_params, items, etc.) is kept as-is; it's flattened later in dbt.
Idempotent: days already on disk are skipped unless --force is passed.

Usage:
    python python/scripts/ga4_extract.py --project YOUR_GCP_PROJECT_ID
    python python/scripts/ga4_extract.py --project YOUR_GCP_PROJECT_ID --start 2020-11-01 --end 2020-11-07
"""

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

import pyarrow.parquet as pq
from google.cloud import bigquery

SOURCE_DATASET = "bigquery-public-data.ga4_obfuscated_sample_ecommerce"
DATA_START = date(2020, 11, 1)
DATA_END = date(2021, 1, 31)
OUT_ROOT = Path(__file__).resolve().parents[2] / "data" / "raw" / "ga4"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ga4_extract")


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def extract_day(client: bigquery.Client, day: date, force: bool) -> int:
    suffix = day.strftime("%Y%m%d")
    out_dir = OUT_ROOT / f"event_date={suffix}"
    out_file = out_dir / "events.parquet"
    if out_file.exists() and not force:
        log.info("skip %s (exists)", suffix)
        return 0

    # list_rows reads the table directly (no query cost); uses the Storage Read API when available.
    table = client.get_table(f"{SOURCE_DATASET}.events_{suffix}")
    try:
        arrow_table = client.list_rows(table).to_arrow()
    except Exception as exc:  # e.g. Storage Read API not permitted: fall back to the slower REST path
        log.warning("storage API failed for %s (%s); retrying via REST", suffix, exc)
        arrow_table = client.list_rows(table).to_arrow(create_bqstorage_client=False)

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(".parquet.tmp")
    pq.write_table(arrow_table, tmp, compression="zstd")
    tmp.replace(out_file)  # atomic swap so a failed run never leaves a half-written file
    log.info("wrote %s: %d rows", suffix, arrow_table.num_rows)
    return arrow_table.num_rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True, help="Your GCP project ID (billed/sandbox project for API calls)")
    p.add_argument("--start", type=date.fromisoformat, default=DATA_START)
    p.add_argument("--end", type=date.fromisoformat, default=DATA_END)
    p.add_argument("--force", action="store_true", help="Re-download days that already exist")
    args = p.parse_args()

    client = bigquery.Client(project=args.project)
    total = sum(extract_day(client, d, args.force) for d in daterange(args.start, args.end))
    log.info("done: %d new rows written under %s", total, OUT_ROOT)


if __name__ == "__main__":
    main()
