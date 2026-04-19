"""
mlflow_cleanup — Monthly MLflow run archival DAG

Runs on the 1st of each month at 02:00 UTC. Soft-deletes (archives) MLflow
training runs older than 90 days from all registered experiments, skipping
any run that backs an active Production or Staging model version in the
Model Registry.

Task graph:
    cleanup_stale_runs
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import mlflow
import mlflow.entities
from airflow.decorators import dag, task
from mlflow.tracking import MlflowClient

_EXPERIMENTS = [
    "demand_forecast_hourly",
    "anomaly_detection_daily",
    "congestion_pricing_did",
]
_RETENTION_DAYS = 90


@dag(
    dag_id="mlflow_cleanup",
    schedule="0 2 1 * *",
    start_date=datetime(2026, 5, 1),
    catchup=False,
    tags=["mlops", "maintenance"],
)
def mlflow_cleanup_dag() -> None:

    @task()
    def cleanup_stale_runs() -> dict:
        mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
        client = MlflowClient()

        cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)).timestamp() * 1000
        )

        # Collect run_ids backing Production or Staging model versions — never delete these
        protected_run_ids: set[str] = set()
        for rm in client.search_registered_models():
            for mv in client.search_model_versions(f"name='{rm.name}'"):
                if mv.current_stage in ("Production", "Staging") and mv.run_id:
                    protected_run_ids.add(mv.run_id)

        deleted = 0
        for exp_name in _EXPERIMENTS:
            experiment = client.get_experiment_by_name(exp_name)
            if experiment is None:
                continue
            runs = client.search_runs(
                experiment_ids=[experiment.experiment_id],
                filter_string=f"attributes.start_time < {cutoff_ms}",
                run_view_type=mlflow.entities.ViewType.ACTIVE_ONLY,
            )
            for run in runs:
                if run.info.run_id not in protected_run_ids:
                    client.delete_run(run.info.run_id)
                    deleted += 1

        print(
            f"Archived {deleted} MLflow run(s) older than {_RETENTION_DAYS} days. "
            f"Protected {len(protected_run_ids)} run(s) backing active model versions."
        )
        return {"runs_deleted": deleted, "protected_count": len(protected_run_ids)}

    cleanup_stale_runs()


mlflow_cleanup_dag()
