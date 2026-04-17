`dbt debug`
Verifies that dbt can connect to Snowflake using the credentials in `profiles.yml` + your `.env`. It checks the account, user, role, warehouse, and database all exist and are accessible. Running this first saves you from a cryptic error mid-run.

`dbt seed`
Loads `transform/seeds/taxi_zone_lookup.csv` into `NYC_TLC_DB.SILVER.taxi_zone_lookup` as a static Snowflake table. This is the reference table that maps zone IDs (like 132) to human-readable names (like `"JFK Airport"`, `"Queens"`). The Gold model joins against it — without it, dbt run will fail on a missing table reference.

`dbt run`
Executes the two SQL models in dependency order:
1. `stg_yellow_tripdata` — reads from `brz_yellow_tripdata` (Bronze), casts types, deduplicates, filters, writes to `NYC_TLC_DB.SILVER`
2. `fct_revenue_per_zone_hourly` — reads from Silver + `taxi_zone_lookup`, aggregates, writes to `NYC_TLC_DB.GOLD`

`dbt test`
Runs all the tests defined in the `.yml` files — unique and not_null checks across Silver and Gold. This is the quality gate: if Silver tests fail, you know bad data would have propagated to Gold.

The full sequence is: connect → load reference data → build models → validate. Each step depends on the previous one succeeding.

---

## dbt-fusion vs dbt-core syntax divergence

This project uses two different dbt runtimes:

| Context | Runtime | Version |
|---|---|---|
| Local (`dbt debug`, `dbt run`, `dbt test`) | dbt-fusion | 2.0.x |
| Airflow / Cosmos (inside Docker) | dbt-core | 1.8.7 |

They have a hard incompatibility on the `relationships` generic test syntax:

- dbt-fusion 2.0 requires `arguments:` wrapper (hard error `dbt0102` without it)
- dbt-core 1.8.7 (Cosmos) breaks when `arguments:` is present

There is no format that satisfies both runtimes simultaneously. The `relationships` test on `pu_location_id` has been removed from `stg_yellow_tripdata.yml` to unblock local runs. The referential integrity it checked is enforced structurally in the Gold model via `LEFT JOIN` + `COALESCE(..., 'Unknown')` on unmatched zone IDs.

To restore the test properly, upgrade the Airflow Dockerfile to dbt-core 1.9.x (which supports `arguments:`) and add back the test using the new format.

---

## Gold model — dashboard readability changes

`fct_revenue_per_zone_hourly` was updated before connecting Superset to address four issues that would have made charts hard to read or build:

**vendor_name** — `vendor_id` is an opaque integer (1, 2, 6, 7). Every chart label and filter dropdown would show the number. A `vendor_name` column (CMT / Curb / Myle / Helix / Unknown) was added alongside `vendor_id` so chart dimensions use human-readable names without needing a Superset calculated column.

**Time breakdown columns** — `pickup_hour` is a full `TIMESTAMP_NTZ`. Building an hour-of-day heatmap or day-of-week demand chart would require a computed column on every query. `pickup_date` (DATE), `hour_of_day` (0–23), and `day_of_week` (Mon–Sun) are now pre-computed in the model so Superset can use them as simple dimensions.

**COALESCE on zone dimensions** — `pickup_borough`, `pickup_zone`, and `service_zone` come from a `LEFT JOIN` against `taxi_zone_lookup`. Any `pu_location_id` with no matching row would produce NULL, silently dropping those trips from grouped charts. All three columns are now `COALESCE`d to `'Unknown'` and carry `not_null` tests.

**ROUND on float columns** — revenue, distance, and duration metrics were stored at full float precision (e.g. `revenue_per_trip = 23.456789`). Every tooltip and table cell displayed 6–8 decimal places. All metrics are now rounded at the model level (2 dp for money, 1 dp for rates and durations) so Superset needs no per-chart formatting overrides.