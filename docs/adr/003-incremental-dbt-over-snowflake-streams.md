# ADR-003: Incremental dbt Models Over Snowflake Streams for Silver/Gold Processing

| Field       | Value                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Date**    | 2026-04-17                   |
| **Author**  | Rushikesh Dhumal             |

---

## Context

Silver (`stg_yellow_tripdata`) and Gold (`fct_revenue_per_zone_hourly`,
`fct_revenue_daily`) were originally materialized as `table`, meaning every
`dbt run` performed a full `CREATE OR REPLACE TABLE` — reprocessing the entire
Bronze dataset regardless of how much new data had arrived. For a growing
multi-month dataset this becomes increasingly expensive on a cost-constrained
Snowflake trial warehouse.

Two approaches were evaluated to make processing incremental:

1. **dbt incremental models** — filter source tables using a watermark derived
   from the model's own current state (`MAX(_batch_id)`, `MAX(pickup_hour)`,
   `MAX(pickup_date)`), merge only new rows using Snowflake's `MERGE` statement.

2. **Snowflake Streams** — CDC objects that track inserts to Bronze at the
   storage layer and expose only the delta rows to downstream consumers.

---

## Decision

Use **dbt incremental models** with `merge` strategy and per-layer watermark
filters. Snowflake Streams were rejected.

---

## Options Considered

| | dbt Incremental (chosen) | Snowflake Streams |
|---|---|---|
| **Efficiency** | Watermark subquery + MERGE scan | Zero-scan CDC — more efficient at the engine level |
| **Staleness risk** | None | Stream goes stale after 14 days if unconsumed |
| **Late-arriving data** | Handled — watermark recalculates on next run | Missed if stream was already consumed |
| **dbt compatibility** | Native `{{ is_incremental() }}` macro | Not a dbt source type — requires custom macros or a Snowflake Task feeding a staging table |
| **Orchestration** | Airflow controls the full pipeline | Snowflake Tasks run on their own schedule — two schedulers in play |

---

## Reasoning

Snowflake Streams are more efficient at the storage layer — they track changes
via CDC with no scanning overhead. However, they are the wrong fit for a
monthly batch pipeline for two reasons:

**Staleness.** Snowflake Streams have a 14-day data retention window. If a
stream is not consumed within that window, the offset is lost and the delta
cannot be recovered. This pipeline runs on the 1st of each month. A single
missed or delayed run puts the stream within days of going stale. Any extended
incident (broken DAG, Snowflake outage, credential expiry) would silently
discard a month of Bronze deltas with no recovery path.

**Orchestration split.** Streams are typically consumed by Snowflake Tasks,
which run on their own internal schedule. Introducing Tasks alongside Airflow
creates two independent schedulers with no shared failure handling. A Task
consuming the stream and an Airflow DAG running dbt would need to be
coordinated externally, adding complexity with no benefit over dbt incremental.

The dbt incremental approach keeps all orchestration in Airflow, all
transformation logic in dbt, and relies on a `_batch_id` watermark (YYYY-MM
string) that is monotonically increasing by design. Late-arriving data or
reruns are handled gracefully — the watermark recalculates on the next run.

---

## Watermark design per layer

| Model | Incremental filter |
|---|---|
| `stg_yellow_tripdata` | `_batch_id > MAX(_batch_id)` in Silver — aligns with monthly Bronze ingestion batches |
| `fct_revenue_per_zone_hourly` | `pickup_hour > MAX(pickup_hour)` in Gold hourly — processes only new hours from Silver |
| `fct_revenue_daily` | `pickup_date > MAX(pickup_date)` in Gold daily — processes only new dates from hourly |

---

## Consequences

**Positive**
- Each monthly run processes only the new batch — Bronze, Silver, and Gold
  all updated incrementally with no full-table rewrites.
- All orchestration remains in Airflow; all transformation logic remains in dbt.
- No Snowflake-specific CDC objects to manage or monitor for staleness.
- `dbt run --full-refresh` provides a clean escape hatch if the incremental
  state ever needs to be rebuilt from scratch.

**Trade-offs**
- Each incremental run executes a watermark subquery (`SELECT MAX(...)`) before
  the main transformation. This is negligible overhead for a monthly batch.
- Streams would be the better choice if the pipeline ever moves to
  near-real-time ingestion (hourly or continuous). At that point the staleness
  risk disappears and the CDC efficiency gains become meaningful.

---

## Files Changed

| File | Change |
|------|--------|
| `transform/models/silver/stg_yellow_tripdata.sql` | Changed to `incremental`, `unique_key='trip_id'`; filter on `_batch_id` |
| `transform/models/gold/fct_revenue_per_zone_hourly.sql` | Changed to `incremental`, `unique_key='fct_id'`; filter on `pickup_hour` |
| `transform/models/gold/fct_revenue_daily.sql` | Changed to `incremental`, `unique_key='fct_id'`; filter on `pickup_date` |
