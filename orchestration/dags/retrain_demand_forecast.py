"""
retrain_demand_forecast — Monthly LightGBM demand forecast retrain DAG

Runs on the 5th of each month at 06:00 UTC, giving the ingest_nyc_taxi_raw
and dbt_transform pipelines time to land the previous month's data before
this DAG fires.

Task graph:
    retrain_model >> write_predictions

retrain_model  — pulls full feature matrix from Gold, trains LightGBM,
                 logs all required params/metrics/artifacts to MLflow,
                 registers new version with alias 'staging'. Promotion to alias 'production'
                 is a deliberate manual step (ML_EXPERIMENT_STANDARDS.md §4).

write_predictions — loads the alias 'production' model from MLflow Registry and
                    writes a month of predictions to ML.fct_demand_forecast.
                    Fails explicitly if no production model exists — this is
                    expected on first run until a staging candidate is promoted.
"""
from __future__ import annotations

from datetime import datetime

from airflow.decorators import dag, task


@dag(
    dag_id="retrain_demand_forecast",
    schedule="0 6 5 * *",
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

    result = retrain_model()
    write_predictions(result)


retrain_demand_forecast_dag()
