"""
ingest_nyc_taxi_raw — Phase 2 Bronze ingestion DAG

Runs on the 1st of each month (catchup=True to backfill from Jan 2025).
For each run, the logical_date gives the target month.

Task graph:
    create_bronze_table >> copy_into_bronze >> validate_bronze_load
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from airflow.decorators import dag, task
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SQL_DIR = Path(__file__).parent.parent / "include" / "sql"
_SNOWFLAKE_CONN = "snowflake_default"
_WAREHOUSE = "COMPUTE_WH"


def _load_sql(filename: str) -> str:
    return (_SQL_DIR / filename).read_text()


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------
@dag(
    dag_id="ingest_nyc_taxi_raw",
    description="Load Yellow Taxi Parquet files from Azure Blob into Bronze (VARIANT).",
    schedule="0 6 1 * *",       # 1st of every month at 06:00 UTC
    start_date=datetime(2025, 1, 1),
    catchup=True,               # backfill all months from 2025-01 to now
    max_active_runs=1,          # prevent concurrent backfill runs hammering Snowflake
    tags=["bronze", "ingestion", "nyc-tlc"],
)
def ingest_nyc_taxi_raw() -> None:

    @task()
    def create_bronze_table() -> None:
        """Ensure brz_yellow_tripdata exists before any COPY INTO runs."""
        hook = SnowflakeHook(snowflake_conn_id=_SNOWFLAKE_CONN)
        hook.run(
            _load_sql("create_brz_yellow_tripdata.sql"),
            autocommit=True,
        )

    @task()
    def copy_into_bronze(logical_date: str) -> dict[str, object]:
        """
        Run COPY INTO for the month represented by logical_date (YYYY-MM-DD).
        Returns Snowflake's load summary for downstream validation.
        """
        month = logical_date[:7]                          # '2025-01'
        batch_id = month                                  # reuse as batch identifier
        pattern = rf".*yellow_tripdata_{month}\.parquet"

        sql = (
            _load_sql("copy_into_bronze.sql")
            .replace("{{ batch_id }}", batch_id)
            .replace("{{ pattern }}", pattern)
        )

        hook = SnowflakeHook(snowflake_conn_id=_SNOWFLAKE_CONN)
        # USE WAREHOUSE inside the session to ensure cost guard is in place
        hook.run(f"USE WAREHOUSE {_WAREHOUSE};", autocommit=True)
        results = hook.get_records(sql)

        rows_loaded = sum(int(r[3]) for r in results) if results else 0
        rows_error  = sum(int(r[4]) for r in results) if results else 0

        return {
            "month": month,
            "rows_loaded": rows_loaded,
            "rows_error": rows_error,
            "files_processed": len(results),
        }

    @task()
    def validate_bronze_load(load_summary: dict[str, object]) -> None:
        """
        Fail the task — and therefore the DAG run — if no rows were loaded or
        if any rows errored. Acts as a lightweight quality gate before Phase 3.
        """
        month        = load_summary["month"]
        rows_loaded  = load_summary["rows_loaded"]
        rows_error   = load_summary["rows_error"]

        if rows_error > 0:
            raise ValueError(
                f"[{month}] COPY INTO reported {rows_error} error rows. "
                "Inspect COPY_HISTORY in Snowflake before retrying."
            )

        if rows_loaded == 0:
            raise ValueError(
                f"[{month}] No rows loaded. "
                "Verify that upload_to_azure.py has run for this month and "
                "that the stage file matches the expected pattern."
            )

        print(
            f"[{month}] Bronze load validated: "
            f"{rows_loaded:,} rows across {load_summary['files_processed']} file(s)."
        )

    # -----------------------------------------------------------------------
    # Wire the graph
    # -----------------------------------------------------------------------
    summary = copy_into_bronze(logical_date="{{ ds }}")

    create_bronze_table() >> summary >> validate_bronze_load(summary)


ingest_nyc_taxi_raw()
