"""
retrain_demand_forecast — Monthly LightGBM demand forecast retrain DAG

Triggered by ingest_nyc_taxi_raw after the dbt_transform task group completes,
ensuring the latest Gold data is available before retraining starts.
schedule=None — this DAG never runs on its own cron.

Task graph:
    retrain_model >> write_predictions >> trigger_monitor_demand_forecast

retrain_model  — pulls full feature matrix from Gold, trains LightGBM,
                 logs all required params/metrics/artifacts to MLflow,
                 logs feature_baseline.json artifact for drift detection (Phase 9),
                 registers new version with alias 'staging'. Promotion to alias 'production'
                 is a deliberate manual step (ML_EXPERIMENT_STANDARDS.md §4).

write_predictions — loads the alias 'production' model from MLflow Registry and
                    writes a month of predictions to ML.fct_demand_forecast.
                    Fails explicitly if no production model exists — this is
                    expected on first run until a staging candidate is promoted.

trigger_monitor_demand_forecast — fires monitor_demand_forecast DAG after
                    predictions are written, so actuals vs predictions comparison
                    is always against the freshest forecast batch.
"""
from __future__ import annotations

from datetime import datetime

from airflow.decorators import dag, task
from airflow.operators.trigger_dagrun import TriggerDagRunOperator


@dag(
    dag_id="retrain_demand_forecast",
    schedule=None,
    start_date=datetime(2026, 2, 1),
    catchup=False,
    max_active_runs=1,
    tags=["mlops", "demand-forecast"],
)
def retrain_demand_forecast_dag() -> None:

    @task()
    def retrain_model() -> dict:
        from airflow.operators.python import get_current_context

        from ml.models.demand_forecast.train import run_training

        ctx = get_current_context()
        return run_training(ctx["ds"])

    @task()
    def write_predictions(train_result: dict) -> int:  # noqa: ARG001
        from airflow.operators.python import get_current_context

        from ml.models.demand_forecast.predict import run_predictions

        ctx = get_current_context()
        return run_predictions(ctx["ds"])

    trigger_monitoring = TriggerDagRunOperator(
        task_id="trigger_monitor_demand_forecast",
        trigger_dag_id="monitor_demand_forecast",
        logical_date="{{ ds }}",
        wait_for_completion=False,
        reset_dag_run=True,
    )

    result = retrain_model()
    predictions = write_predictions(result)
    predictions >> trigger_monitoring


retrain_demand_forecast_dag()
