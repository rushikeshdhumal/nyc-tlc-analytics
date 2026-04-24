"""
monitor_demand_forecast — Monthly model monitoring DAG

Triggered by retrain_demand_forecast after write_predictions completes,
so predictions are guaranteed to exist in ML.fct_demand_forecast before
monitoring runs.
schedule=None — this DAG never runs on its own cron.

Task graph:
    run_monitoring

run_monitoring — computes MAE/RMSE/MAPE of fct_demand_forecast predictions
                 vs Gold actuals, detects feature distribution drift vs the
                 training baseline stored as a MLflow artifact, and writes
                 one summary row to ML.fct_model_monitoring.

                 Logs a WARNING if MAPE has degraded or features have drifted.
                 Does NOT auto-trigger retraining — the monthly retrain cadence
                 is driven by ingest_nyc_taxi_raw (cost guard on Snowflake Trial).
"""
from __future__ import annotations

from datetime import datetime

from airflow.decorators import dag, task


@dag(
    dag_id="monitor_demand_forecast",
    schedule=None,
    start_date=datetime(2026, 2, 1),
    catchup=False,
    max_active_runs=1,
    tags=["mlops", "monitoring", "demand-forecast"],
)
def monitor_demand_forecast_dag() -> None:

    @task()
    def run_monitoring() -> dict:
        from airflow.operators.python import get_current_context

        from ml.monitoring.monitor import run_monitoring as _run_monitoring

        ctx = get_current_context()
        return _run_monitoring(ctx["ds"])

    run_monitoring()


monitor_demand_forecast_dag()
