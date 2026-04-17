"""
ingest_nyc_taxi_raw — Full monthly pipeline DAG (Phase 2 + Phase 4)

Runs on the 1st of each month (catchup=True to backfill from Jan 2025).
The logical_date gives the target month.

Task graph:
    create_bronze_table
        >> copy_into_bronze
        >> validate_bronze_load
        >> dbt_transform (Cosmos DbtTaskGroup)
              ├─ stg_yellow_tripdata.run → stg_yellow_tripdata.test
              └─ fct_revenue_per_zone_hourly.run → fct_revenue_per_zone_hourly.test

Cosmos runs Silver tests before building Gold, so bad Silver data never
reaches the Gold layer (DATA_LINEAGE_CONTRACTS.md §3).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from airflow.decorators import dag, task
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import ExecutionMode, TestBehavior
from cosmos.profiles import SnowflakeUserPasswordProfileMapping

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SQL_DIR        = Path(__file__).parent.parent / "include" / "sql"
_DBT_PROJECT    = Path("/opt/airflow/transform")
_SNOWFLAKE_CONN = "snowflake_default"
_WAREHOUSE      = "COMPUTE_WH"


def _load_sql(filename: str) -> str:
    return (_SQL_DIR / filename).read_text()


# ---------------------------------------------------------------------------
# Cosmos config — reused by the DbtTaskGroup
# ---------------------------------------------------------------------------
_profile_config = ProfileConfig(
    profile_name="nyc_tlc_project",
    target_name="dev",
    profile_mapping=SnowflakeUserPasswordProfileMapping(
        conn_id=_SNOWFLAKE_CONN,
        profile_args={
            "database": "NYC_TLC_DB",
            "schema":   "silver",
            "warehouse": _WAREHOUSE,
            "role":     "DE_ROLE",
        },
    ),
)


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------
@dag(
    dag_id="ingest_nyc_taxi_raw",
    description="End-to-end monthly pipeline: Bronze COPY INTO → dbt Silver → dbt Gold.",
    schedule="0 6 1 * *",       # 1st of every month at 06:00 UTC
    start_date=datetime(2025, 1, 1),
    catchup=True,
    max_active_runs=1,
    tags=["bronze", "silver", "gold", "ingestion", "nyc-tlc"],
)
def ingest_nyc_taxi_raw() -> None:

    # ── Phase 2: Bronze ingestion ─────────────────────────────────────────

    @task()
    def create_bronze_table() -> None:
        """Ensure brz_yellow_tripdata exists before any COPY INTO runs."""
        hook = SnowflakeHook(snowflake_conn_id=_SNOWFLAKE_CONN)
        hook.run(_load_sql("create_brz_yellow_tripdata.sql"), autocommit=True)

    @task()
    def copy_into_bronze(logical_date: str) -> dict[str, object]:
        """
        Run COPY INTO for the month represented by logical_date (YYYY-MM-DD).
        Returns load summary for downstream validation.

        rows_loaded is derived from before/after row counts for this _batch_id,
        which is stable across Snowflake COPY result format variations.
        """
        month    = logical_date[:7]
        batch_id = month
        pattern  = rf".*yellow_tripdata_{month}\.parquet"

        sql = (
            _load_sql("copy_into_bronze.sql")
            .replace("{{ batch_id }}", batch_id)
            .replace("{{ pattern }}", pattern)
        )

        hook = SnowflakeHook(snowflake_conn_id=_SNOWFLAKE_CONN)
        hook.run(f"USE WAREHOUSE {_WAREHOUSE};", autocommit=True)

        count_sql = (
            "SELECT COUNT(*) "
            "FROM NYC_TLC_DB.BRONZE.brz_yellow_tripdata "
            f"WHERE _batch_id = '{batch_id}'"
        )
        before_count_row = hook.get_first(count_sql)
        before_count = int(before_count_row[0] or 0) if before_count_row else 0

        results = hook.get_records(sql) or []

        after_count_row = hook.get_first(count_sql)
        after_count = int(after_count_row[0] or 0) if after_count_row else 0

        # Snowflake COPY INTO result tuple shapes can vary by connector/provider version.
        # Parse defensively so this task remains stable across environments.
        rows_loaded = max(after_count - before_count, 0)
        copy_reported_rows_loaded = 0
        rows_error = 0
        files_already_loaded = 0

        for result_row in results:
            status = str(result_row[1]).upper() if len(result_row) > 1 and result_row[1] is not None else ""
            loaded = int(result_row[3] or 0) if len(result_row) > 3 else 0
            errors = int(result_row[4] or 0) if len(result_row) > 4 else 0

            copy_reported_rows_loaded += loaded
            rows_error += errors

            if status == "COPY_ALREADY_LOADED":
                files_already_loaded += 1

        # If this batch already existed and COPY added nothing, treat as idempotent replay.
        if rows_loaded == 0 and before_count > 0:
            files_already_loaded = max(files_already_loaded, 1)

        print(
            f"[{month}] COPY reconciliation: "
            f"before_count={before_count}, after_count={after_count}, rows_loaded={rows_loaded}"
        )
        print(
            f"[{month}] COPY reported: "
            f"copy_reported_rows_loaded={copy_reported_rows_loaded}, rows_error={rows_error}, "
            f"files_processed={len(results)}, files_already_loaded={files_already_loaded}"
        )

        return {
            "month":                month,
            "rows_loaded":          rows_loaded,
            "copy_reported_rows_loaded": copy_reported_rows_loaded,
            "rows_error":           rows_error,
            "files_processed":      len(results),
            "files_already_loaded": files_already_loaded,
        }

    @task()
    def validate_bronze_load(load_summary: dict[str, object]) -> None:
        """
        Fail the DAG run if no rows were loaded or if any rows errored.
        Prevents dbt_transform from running against an empty/broken Bronze table.
        COPY_ALREADY_LOADED is treated as valid — data exists from a prior run.
        """
        month                = load_summary["month"]
        rows_loaded          = load_summary["rows_loaded"]
        rows_error           = load_summary["rows_error"]
        files_already_loaded = load_summary.get("files_already_loaded", 0)

        if rows_error > 0:
            raise ValueError(
                f"[{month}] COPY INTO reported {rows_error} error rows. "
                "Inspect COPY_HISTORY in Snowflake before retrying."
            )
        if rows_loaded == 0 and files_already_loaded == 0:
            raise ValueError(
                f"[{month}] No rows loaded. "
                "Verify that upload_to_azure.py has run for this month and "
                "that the stage file matches the expected pattern."
            )

        if files_already_loaded > 0 and rows_loaded == 0:
            print(
                f"[{month}] Bronze data already present — "
                f"{files_already_loaded} file(s) skipped (COPY_ALREADY_LOADED). "
                "Proceeding to dbt transforms."
            )
        else:
            print(
                f"[{month}] Bronze load validated: "
                f"{rows_loaded:,} rows across {load_summary['files_processed']} file(s)."
            )

    # ── Phase 4: dbt Silver + Gold via Cosmos ─────────────────────────────

    dbt_transform = DbtTaskGroup(
        group_id="dbt_transform",
        project_config=ProjectConfig(_DBT_PROJECT),
        profile_config=_profile_config,
        execution_config=ExecutionConfig(execution_mode=ExecutionMode.LOCAL),
        render_config=RenderConfig(
            # Run Silver tests before Gold runs — bad Silver data never reaches Gold
            test_behavior=TestBehavior.AFTER_EACH,
        ),
    )

    # ── Wire the graph ────────────────────────────────────────────────────

    summary = copy_into_bronze(logical_date="{{ ds }}")

    create_bronze_table() >> summary >> validate_bronze_load(summary) >> dbt_transform


ingest_nyc_taxi_raw()
