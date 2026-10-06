"""Export reporting tables from warehouse.duckdb to Parquet for Power BI (the serving layer).

Output: data/serving/<table>.parquet, overwritten on every run.
Power BI reads these files through a DataFolder parameter, so a refresh picks up the latest pipeline run.

Usage:
    python python/scripts/export_powerbi.py
"""

from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = PROJECT_ROOT / "warehouse.duckdb"
OUT_DIR = PROJECT_ROOT / "data" / "serving"

TABLES = {
    # facts
    "fct_sessions": "marts.fct_sessions",
    "fct_orders": "marts.fct_orders",
    "fct_attribution_credits": "marts.fct_attribution_credits",
    "attribution_markov": "marts.attribution_markov",
    # dimensions
    "dim_date": "marts.dim_date",
    "dim_channel": "marts.dim_channel",
    "dim_attribution_model": "marts.dim_attribution_model",
    "dim_device": "marts.dim_device",
    "dim_funnel_stage": "marts.dim_funnel_stage",
    "fct_order_items": "marts.fct_order_items",
    "dim_customers": "marts.dim_customers",
    "mart_product_pairs": "marts.mart_product_pairs",
}

# Power BI's Parquet connector can't read 128-bit integers; DuckDB produces them from SUM(bigint).
CASTS = {"HUGEINT": "BIGINT", "UHUGEINT": "BIGINT"}


def export(con: duckdb.DuckDBPyConnection, name: str, relation: str) -> int:
    cols = con.sql(f"DESCRIBE {relation}").fetchall()
    select = ", ".join(
        f'CAST("{c[0]}" AS {CASTS[c[1]]}) AS "{c[0]}"' if c[1] in CASTS else f'"{c[0]}"' for c in cols
    )
    out = OUT_DIR / f"{name}.parquet"
    con.sql(f"COPY (SELECT {select} FROM {relation}) TO '{out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
    return con.sql(f"SELECT count(*) FROM {relation}").fetchone()[0]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(WAREHOUSE), read_only=True) as con:
        for name, relation in TABLES.items():
            print(f"{name:28s} {export(con, name, relation):>10,} rows")
    print(f"\nExported to {OUT_DIR}")


if __name__ == "__main__":
    main()
