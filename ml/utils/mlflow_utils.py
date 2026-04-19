"""MLflow helper utilities shared across all ML models.

Centralises tracking URI setup and Model Registry interactions so individual
training scripts don't duplicate this boilerplate.
"""
from __future__ import annotations

import os

import mlflow
from mlflow.tracking import MlflowClient


def setup_tracking() -> None:
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))


def get_or_create_experiment(name: str) -> str:
    """Return the experiment_id, creating the experiment if it does not exist."""
    setup_tracking()
    experiment = mlflow.get_experiment_by_name(name)
    if experiment is None:
        return mlflow.create_experiment(name)
    return experiment.experiment_id


def get_production_model(model_name: str) -> mlflow.pyfunc.PyFuncModel:
    """Load the Production model from the MLflow Registry.

    Raises RuntimeError if no Production version exists — never falls back to
    a local file (ML_EXPERIMENT_STANDARDS.md §5).
    """
    setup_tracking()
    client = MlflowClient()
    versions = client.get_latest_versions(model_name, stages=["Production"])
    if not versions:
        raise RuntimeError(
            f"No Production model found for '{model_name}'. "
            "Promote a Staging version to Production before running predictions."
        )
    return mlflow.pyfunc.load_model(f"models:/{model_name}/Production")


def register_and_stage(
    run_id: str,
    model_name: str,
    artifact_path: str = "model",
    stage: str = "Staging",
) -> str:
    """Register a model version from a completed run and set its stage.

    Returns the registered version string.
    Promotion from Staging → Production is a deliberate manual step
    (ML_EXPERIMENT_STANDARDS.md §4).
    """
    setup_tracking()
    client = MlflowClient()
    result = mlflow.register_model(f"runs:/{run_id}/{artifact_path}", model_name)
    client.transition_model_version_stage(
        name=model_name,
        version=result.version,
        stage=stage,
    )
    return result.version
