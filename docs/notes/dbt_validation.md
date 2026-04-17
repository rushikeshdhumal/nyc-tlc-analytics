`dbt debug`
Verifies that dbt can connect to Snowflake using the credentials in `profiles.yml` + your `.env`. It checks the account, user, role, warehouse, and database all exist and are accessible. Running this first saves you from a cryptic error mid-run.

`dbt seed`
Loads `transform/seeds/taxi_zone_lookup.csv` into `NYC_TLC_DB.SILVER.taxi_zone_lookup` as a static Snowflake table. This is the reference table that maps zone IDs (like 132) to human-readable names (like `"JFK Airport"`, `"Queens"`). The Gold model joins against it — without it, dbt run will fail on a missing table reference.

`dbt run`
Executes the two SQL models in dependency order:
1. `stg_yellow_tripdata` — reads from `brz_yellow_tripdata` (Bronze), casts types, deduplicates, filters, writes to `NYC_TLC_DB.SILVER`
2. `fct_revenue_per_zone_hourly` — reads from Silver + `taxi_zone_lookup`, aggregates, writes to `NYC_TLC_DB.GOLD`

`dbt test`
Runs all the tests defined in the `.yml` files — unique, not_null, and the relationships check on `pu_location_id`. This is the quality gate: if Silver tests fail, you know bad data would have propagated to Gold.

The full sequence is: connect → load reference data → build models → validate. Each step depends on the previous one succeeding.

---

## dbt-fusion vs dbt-core syntax divergence

This project uses two different dbt runtimes:

| Context | Runtime | Version |
|---|---|---|
| Local (`dbt debug`, `dbt run`, `dbt test`) | dbt-fusion | 2.0.x |
| Airflow / Cosmos (inside Docker) | dbt-core | 1.8.7 |

They have diverged on the `relationships` generic test syntax:

**dbt-fusion 2.0 (local) — new format required:**
```yaml
- relationships:
    arguments:
      to: ref('taxi_zone_lookup')
      field: LocationID
```

**dbt-core 1.8.7 (Airflow/Cosmos) — old format required:**
```yaml
- relationships:
    to: ref('taxi_zone_lookup')
    field: LocationID
```

The `.yml` files in this repo use the **dbt-core 1.8.7 format** (without `arguments:`) so that Cosmos can parse the project without errors. Running `dbt test` locally with dbt-fusion will show a deprecation warning for this test — that warning is safe to ignore.