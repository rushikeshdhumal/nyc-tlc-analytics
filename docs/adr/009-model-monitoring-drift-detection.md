# ADR-009 — Model Monitoring & Drift Detection

**Date**: 2026-04-24
**Status**: Accepted
**Phase**: 9

---

## Context

The demand forecast model (`demand_forecast_hourly`) retrains monthly via the
`retrain_demand_forecast` DAG. Without monitoring, MAPE degradation or feature
distribution drift can go undetected between retrains. NYC TLC data is susceptible
to structural shifts (e.g., congestion pricing effective 2025-01-05, seasonal demand
changes, zone-level disruptions) that may degrade forecast quality before the next
scheduled retrain surfaces the problem.

Phase 9 adds a lightweight monthly monitoring layer that runs automatically after
each retrain cycle.

---

## Decision

### Architecture

- A new `monitor_demand_forecast` DAG (schedule=None) is triggered by
  `retrain_demand_forecast` after `write_predictions` completes, ensuring predictions
  are always present before monitoring runs.
- Business logic lives in `ml/monitoring/monitor.py`. The DAG is orchestration-only.
- One summary row per run_date is written to `NYC_TLC_DB.ML.FCT_MODEL_MONITORING`.

### Prediction Error Metrics

Computed by joining `ML.fct_demand_forecast` predictions (filtered by `_RUN_DATE`)
against `GOLD.fct_revenue_per_zone_hourly` actuals on `(pickup_hour, pu_location_id)`:

- **MAE** — Mean Absolute Error (trips)
- **RMSE** — Root Mean Squared Error (trips)
- **MAPE** — Mean Absolute Percentage Error (%)

### MAPE Degradation Signal

`mape_degraded = True` when either condition holds:

1. `current_mape > training_test_mape × 1.2` — 20% relative degradation from the
   model's own holdout performance at training time.
2. `current_mape > training_baseline_mape` — model no longer beats the naive
   lag-168 baseline (the minimum promotion bar from ML_EXPERIMENT_STANDARDS.md §4).

Both thresholds use metrics fetched from the production model's MLflow run — no
additional Snowflake queries.

### Feature Distribution Drift Detection

During training, `train.py` logs a `feature_baseline.json` artifact to the MLflow
run. The JSON contains per-feature `{mean, std}` computed on the training window.

At monitoring time, `monitor.py` downloads this artifact from local MLflow (zero
Snowflake credits), builds the current month's feature matrix (one Snowflake query),
and flags features where:

```
|current_month_mean - training_mean| > 2 × training_std
```

Drifted feature names are stored in `DRIFTED_FEATURES` (comma-separated) and the
count in `N_DRIFTED_FEATURES`.

### Retraining Response (Flag + Warning)

The monitoring DAG does **not** auto-trigger retraining. Rationale:

- The monthly retrain cadence already tracks the latest Gold data. Auto-triggering
  on degradation would fire a second retrain in the same month, doubling Snowflake
  warehouse costs on a Trial account.
- Persistent degradation (e.g., a structural data shift post-congestion-pricing)
  requires human review to decide whether more data, feature engineering, or model
  changes are needed — not just a re-run.

Instead: `mape_degraded = True` is written to `FCT_MODEL_MONITORING` and surfaced in
Superset. The Airflow task also emits a `WARNING` log line visible in the task logs.

---

## Alternatives Considered

### Option A — Passive flag only (rejected)
Flag written to Snowflake, no log signal. Requires active Superset monitoring to
catch degradation. Insufficient for a production pipeline.

### Option B — Auto-trigger retrain (rejected)
Creates a feedback loop on a Trial Snowflake account. If the model is in persistent
degradation, every monthly monitoring run would trigger an unbounded retrain cycle.

### Option C — Flag + Airflow warning (accepted)
Balances observability with cost control. The flag is machine-readable for Superset
dashboards; the warning log is visible in Airflow task logs without requiring a
separate alerting channel.

---

## Consequences

- Every training run now logs `feature_baseline.json`. Models registered before
  Phase 9 do not have this artifact — drift detection is gracefully skipped for
  those versions with a WARNING log.
- `ML.FCT_MODEL_MONITORING` holds one row per monthly run, giving a time-series of
  MAPE, drift counts, and model version history suitable for Superset trending charts.
- `retrain_demand_forecast` trigger chain:
  `ingest_nyc_taxi_raw → retrain_demand_forecast → monitor_demand_forecast`

---

## Files Added / Modified

| File | Change |
|---|---|
| `ml/monitoring/__init__.py` | New — monitoring module |
| `ml/monitoring/monitor.py` | New — core monitoring logic |
| `ml/models/demand_forecast/train.py` | Modified — log `feature_baseline.json` artifact |
| `ml/utils/snowflake_io.py` | Modified — add `read_sql`, `insert_model_monitoring_rows` |
| `infra/scripts/ml_setup.sql` | Modified — add `FCT_MODEL_MONITORING` DDL |
| `orchestration/dags/monitor_demand_forecast.py` | New — monitoring DAG |
| `orchestration/dags/retrain_demand_forecast.py` | Modified — add trigger to monitoring DAG |
