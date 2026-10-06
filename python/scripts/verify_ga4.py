"""Sanity-check the downloaded GA4 Parquet with DuckDB."""

from pathlib import Path

import duckdb

GLOB = str(Path(__file__).resolve().parents[2] / "data" / "raw" / "ga4" / "*" / "events.parquet")

con = duckdb.connect()
src = f"read_parquet('{GLOB}', hive_partitioning = true)"

print(con.sql(f"""
    SELECT count(*)                        AS events,
           count(DISTINCT user_pseudo_id)  AS users,
           min(event_date)                 AS first_day,
           max(event_date)                 AS last_day,
           count(DISTINCT event_date)      AS days
    FROM {src}
"""))

print(con.sql(f"""
    SELECT event_name, count(*) AS n
    FROM {src}
    GROUP BY 1 ORDER BY n DESC LIMIT 15
"""))
