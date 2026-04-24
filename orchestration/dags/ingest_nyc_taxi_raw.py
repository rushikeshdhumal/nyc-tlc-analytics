"""
ingest_nyc_taxi_raw — Full monthly pipeline DAG

Runs on the 1st of each month (catchup=True).
start_date=2024-03-01, so the earliest scheduled logical_date is 2024-03-01,
which targets 2024-01 via the 2-month TLC lag. This covers the full ML
training window (ML_FEATURE_CONTRACTS.md §Model 1: train from 2024-01-01).
TLC publishes data with a ~2 month lag.
download_to_azure checks a 6-month rolling window so any month missed due to
TLC delays is caught automatically by the next run (e.g. June 2026 checks
Apr, Mar, Feb, Jan, Dec, Nov 2026/25).
copy_into_bronze targets logical_date minus 2 months.

Task graph:
    download_to_azure       — download TLC parquet from CDN → Azure Blob
        >> create_bronze_table
        >> copy_into_bronze
        >> validate_bronze_load
        >> dbt_transform (Cosmos DbtTaskGroup)
              ├─ stg_yellow_tripdata.run → stg_yellow_tripdata.test
              ├─ fct_revenue_per_zone_hourly.run → fct_revenue_per_zone_hourly.test
              └─ fct_revenue_daily.run → fct_revenue_daily.test
        >> trigger_retrain_demand_forecast

Cosmos runs Silver tests before building Gold, so bad Silver data never
reaches the Gold layer (DATA_LINEAGE_CONTRACTS.md §3).
trigger_retrain_demand_forecast fires retrain_demand_forecast (schedule=None)
with the same logical_date so the retrain sees the freshly built Gold tables.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import requests
from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook
from azure.storage.blob import BlobServiceClient
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import ExecutionMode, TestBehavior
from cosmos.profiles import SnowflakeUserPasswordProfileMapping

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SQL_DIR        = Path(__file__).parent.parent / "include" / "sql"
_DBT_PROJECT    = Path(os.getenv("DBT_PROJECT_DIR", "/opt/airflow/transform"))
_SNOWFLAKE_CONN = "snowflake_default"
_WAREHOUSE      = "COMPUTE_WH"
_TLC_CDN_URL    = (
    "https://d37ci6vzurychx.cloudfront.net/trip-data/"
    "yellow_tripdata_{month}.parquet"
)
_TLC_RELEASE_LAG     = 2               # months TLC takes to publish data


def _load_sql(filename: str) -> str:
    return (_SQL_DIR / filename).read_text()


def _target_month(logical_date: str) -> str:
    """
    Return the YYYY-MM string for the TLC file this DAG run should process.

    TLC publishes data with a ~2 month lag, so the run for May 2026 should
    download and load March 2026 data, not May 2026.
    """
    from datetime import date
    d = date.fromisoformat(logical_date[:10])
    month = d.month - _TLC_RELEASE_LAG
    year  = d.year
    if month <= 0:
        month += 12
        year  -= 1
    return f"{year}-{month:02d}"


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
    start_date=datetime(2024, 3, 1),
    catchup=True,
    max_active_runs=1,
    tags=["bronze", "silver", "gold", "ingestion", "nyc-tlc"],
)
def ingest_nyc_taxi_raw() -> None:

    # ── Phase 1: Download new parquet → Azure Blob Storage ───────────────

    @task()
    def download_to_azure(logical_date: str) -> None:
        """
        Check a 6-month rolling window ending at (logical_date - TLC lag) and
        download any parquet files missing from Azure Blob Storage.

        Window example for a June 2026 run (lag=2):
            checks: 2026-04, 2026-03, 2026-02, 2026-01, 2025-12, 2025-11
            downloads any that are absent from Azure.

        This ensures a month missed due to TLC publishing delays is caught
        automatically by the next scheduled run — no manual intervention needed.

        Raises AirflowSkipException only if the primary target month (newest
        in the window) returns 404 — meaning TLC is still delayed and there
        is genuinely no new data to process this run.
        """
        from datetime import date

        account   = os.environ["AZURE_STORAGE_ACCOUNT"]
        container = os.environ["AZURE_STORAGE_CONTAINER"]
        sas_token = os.environ["AZURE_SAS_TOKEN"]

        az_client = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=sas_token,
        )

        # Build the 6-month window: target month down to target - 5
        primary_month = _target_month(logical_date)
        d = date.fromisoformat(primary_month + "-01")
        window: list[str] = []
        for i in range(6):
            window.append(f"{d.year}-{d.month:02d}")
            month_num = d.month - 1 or 12
            year      = d.year - (1 if d.month == 1 else 0)
            d = date(year, month_num, 1)

        primary_published = False

        for month in window:
            filename = f"yellow_tripdata_{month}.parquet"
            blob     = az_client.get_blob_client(container=container, blob=filename)

            if blob.exists():
                print(f"[{month}] Already in Azure — skipping.")
                if month == primary_month:
                    primary_published = True
                continue

            url = _TLC_CDN_URL.format(month=month)
            print(f"[{month}] Downloading {url}")
            with requests.get(url, stream=True, timeout=300) as resp:
                if resp.status_code == 404:
                    print(f"[{month}] Not published yet (HTTP 404) — skipping.")
                    continue
                resp.raise_for_status()

                size_mb = int(resp.headers.get("content-length", 0)) / 1_048_576
                print(f"[{month}] Streaming {size_mb:.1f} MB → {container}/{filename}")
                resp.raw.decode_content = True  # handle transparent content-encoding
                blob.upload_blob(resp.raw, overwrite=False)
            print(f"[{month}] Uploaded → {container}/{filename}")
            if month == primary_month:
                primary_published = True

        if not primary_published:
            raise AirflowSkipException(
                f"[{primary_month}] Primary target not published yet and not already "
                "in Azure. DAG run skipped — will retry on next scheduled execution."
            )

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
        month    = _target_month(logical_date)
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
            errors = int(result_row[5] or 0) if len(result_row) > 5 else 0

            copy_reported_rows_loaded += loaded

            if status == "COPY_ALREADY_LOADED":
                files_already_loaded += 1
            else:
                # Only count errors_seen (index 5). Index 4 is error_limit,
                # which is 1 by default with ON_ERROR='ABORT_STATEMENT' and
                # must not be mistaken for an actual error count.
                rows_error += errors

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

    # ── Trigger downstream ML retrain ────────────────────────────────────

    trigger_retrain = TriggerDagRunOperator(
        task_id="trigger_retrain_demand_forecast",
        trigger_dag_id="retrain_demand_forecast",
        logical_date="{{ ds }}",
        wait_for_completion=False,
        reset_dag_run=True,
    )

    # ── Wire the graph ────────────────────────────────────────────────────

    summary = copy_into_bronze(logical_date="{{ ds }}")

    (
        download_to_azure(logical_date="{{ ds }}")
        >> create_bronze_table()
        >> summary
        >> validate_bronze_load(summary)
        >> dbt_transform
        >> trigger_retrain
    )


ingest_nyc_taxi_raw()
