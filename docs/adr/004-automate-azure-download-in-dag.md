# ADR-004: Automate Azure Download Inside the Airflow DAG

| Field       | Value                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Date**    | 2026-04-17                   |
| **Author**  | Rushikesh Dhumal             |

---

## Context

ADR-001 introduced `infra/scripts/upload_to_azure.py` as a manual bootstrap
script to download TLC Parquet files from the CloudFront CDN and upload them
to Azure Blob Storage before each monthly pipeline run. Two problems with this
approach became apparent during production backfill:

1. **No orchestration.** The script had to be run manually before triggering
   the DAG. A missed execution left no data in Azure and caused the pipeline
   to fail silently or skip.

2. **TLC publishing lag.** TLC publishes data with an approximately 2-month
   delay. A DAG scheduled for May 2026 cannot download May 2026 data — it
   must target March 2026. The manual script had no awareness of this lag,
   requiring the operator to remember and apply the offset by hand.

3. **Missed months.** If TLC delayed a release beyond the expected lag (or a
   run was skipped), the affected month was permanently missed — no mechanism
   existed to catch up without manual intervention.

---

## Decision

Replace `upload_to_azure.py` with a `download_to_azure` Airflow task at the
head of the `ingest_nyc_taxi_raw` DAG. The task runs automatically on every
scheduled execution and handles the TLC lag and catch-up logic internally.

---

## Design

### TLC release lag

`_target_month(logical_date)` subtracts 2 months from Airflow's `logical_date`
to derive the primary target month:

```
logical_date 2026-05-01  →  target month 2026-03
logical_date 2025-07-01  →  target month 2025-05
```

This is implemented as a pure function so it can be tested independently of
Airflow and reused by both `download_to_azure` and `copy_into_bronze`.

### 6-month rolling window

Rather than targeting only the primary month, `download_to_azure` scans a
6-month window ending at the primary target month and downloads any files
absent from Azure. Example for a June 2026 run (primary = 2026-04):

```
checks: 2026-04, 2026-03, 2026-02, 2026-01, 2025-12, 2025-11
downloads any that are missing from Azure Blob Storage
```

This ensures a month missed due to TLC delays or a skipped run is caught
automatically on the next execution — no manual intervention required.

A 6-month window was chosen because:
- TLC's documented lag is ~2 months; edge cases have reached 3 months.
- A 6-month buffer provides a 3-month margin above the worst-known lag.
- Azure Blob Storage checks (`blob.exists()`) are metadata-only — no compute
  cost for months already present.

### Graceful skip

If the primary target month returns HTTP 404 from the TLC CDN **and** is not
already in Azure, the task raises `AirflowSkipException`. This marks the DAG
run as skipped (not failed) so Airflow does not alert on a normal publishing
delay. The rolling window still downloads any older months that are available.

### Idempotency

`blob.exists()` is checked before every download. Re-running the task for the
same month is a no-op — no duplicate uploads, no overwrite errors.

---

## Options Considered

| | Automated DAG task (chosen) | Manual script | Scheduled Azure Function |
|---|---|---|---|
| **Orchestration** | Fully in Airflow — single scheduler | Manual — operator must remember | Two schedulers (Airflow + Azure) |
| **TLC lag awareness** | Built-in via `_target_month()` | Manual offset applied by operator | Would need custom logic |
| **Missed month recovery** | 6-month rolling window | Manual re-run of script | Complex state tracking |
| **Failure visibility** | Airflow task failure / skip | Silent unless operator checks | Separate alerting system needed |

---

## Consequences

**Positive**
- Zero manual steps for monthly ingestion — the full pipeline runs end-to-end
  from a single DAG trigger.
- TLC lag and catch-up logic are version-controlled and tested alongside the
  rest of the pipeline.
- `AirflowSkipException` provides clean observability: skipped runs mean TLC
  hasn't published yet, failed runs mean a real problem.

**Trade-offs**
- The Airflow container image now requires `azure-storage-blob` and `requests`,
  adding two dependencies to the Docker build.
- The 6-month window may download files that no DAG run will ever load into
  Bronze (e.g., months before `start_date`). These are inert blobs in Azure
  and can be deleted manually if storage cost is a concern.

---

## Files Changed

| File | Change |
|------|--------|
| `orchestration/dags/ingest_nyc_taxi_raw.py` | Added `download_to_azure` task, `_target_month()` helper, `_TLC_CDN_URL`, `_CHUNK_SIZE`, `_TLC_RELEASE_LAG` constants; wired as first task in graph |
| `orchestration/requirements.txt` | Added `azure-storage-blob==12.22.0`, `requests==2.32.3` |
| `infra/docker/airflow.Dockerfile` | Added `azure-storage-blob==12.22.0`, `requests==2.32.3` to pip install |
| `docker-compose.yml` | Added `AZURE_STORAGE_ACCOUNT`, `AZURE_STORAGE_CONTAINER`, `AZURE_SAS_TOKEN` to `x-airflow-common` environment |
