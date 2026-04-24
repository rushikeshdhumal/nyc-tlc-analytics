"""
congestion_pricing_analysis — Incremental DiD causal inference DAG

Triggered by ingest_nyc_taxi_raw after dbt_transform completes (in parallel
with trigger_retrain_demand_forecast). schedule=None — never runs on its own
cron; always driven by fresh Gold data landing.

Re-runs monthly. The post-treatment window (2025-01-05 onward) grows with
each run, stabilising the β₃ estimate over time.

Task graph:
    run_analysis

run_analysis — loads fct_revenue_daily from Gold, fits TWFE DiD OLS for
               trip_count and total_revenue, logs params/metrics to MLflow
               (experiment: congestion_pricing_did), writes per-zone per-period
               summary rows to ML.fct_congestion_pricing_impact.
"""
from __future__ import annotations

from datetime import datetime

from airflow.decorators import dag, task


@dag(
    dag_id="congestion_pricing_analysis",
    schedule=None,
    start_date=datetime(2026, 2, 1),
    catchup=False,
    max_active_runs=1,
    tags=["mlops", "causal-inference"],
)
def congestion_pricing_analysis_dag() -> None:

    @task()
    def run_analysis() -> int:
        from airflow.operators.python import get_current_context

        from ml.models.causal_inference.congestion_pricing_did import run_did

        ctx = get_current_context()
        return run_did(ctx["ds"])


    run_analysis()


congestion_pricing_analysis_dag()
