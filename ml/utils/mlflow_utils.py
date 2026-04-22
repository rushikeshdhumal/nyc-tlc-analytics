"""MLflow helper utilities shared across all ML models.

Centralises tracking URI setup and Model Registry interactions so individual
training scripts don't duplicate this boilerplate.
"""
from __future__ import annotations

import os

import mlflow
from mlflow.tracking import MlflowClient


def _alias_from_stage(stage: str) -> str:
    """Map legacy stage names to model aliases."""
    normalized = stage.strip().lower()
    if normalized in {"staging", "production", "archived"}:
        return normalized
    raise ValueError(f"Unsupported stage '{stage}'. Expected Staging/Production/Archived.")


def setup_tracking() -> None:
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    if tracking_uri.startswith("file:"):
        raise ValueError(
            "File-based MLflow tracking is disabled for this project. "
            "Set MLFLOW_TRACKING_URI to the MLflow server (for example, http://localhost:5000)."
        )
    mlflow.set_tracking_uri(tracking_uri)


def get_or_create_experiment(name: str) -> str:
    """Return the experiment_id, creating the experiment if it does not exist."""
    setup_tracking()
    experiment = mlflow.get_experiment_by_name(name)
    if experiment is None:
        return mlflow.create_experiment(name)
    return experiment.experiment_id


def get_production_model(model_name: str) -> mlflow.pyfunc.PyFuncModel:
    """Load the production model from MLflow Registry.

    Prefers the `production` alias (future-proof). Falls back to the legacy
    `Production` stage for backward compatibility with older registrations.
    Raises RuntimeError if neither exists.
    """
    setup_tracking()
    client = MlflowClient()

    # Preferred path: registry alias (MLflow stages are deprecated).
    try:
        client.get_model_version_by_alias(model_name, "production")
        return mlflow.pyfunc.load_model(f"models:/{model_name}@production")
    except Exception:
        pass

    # Backward-compatible path for existing stage-based deployments.
    versions = client.get_latest_versions(model_name, stages=["Production"])
    if versions:
        return mlflow.pyfunc.load_model(f"models:/{model_name}/Production")

    raise RuntimeError(
        f"No production model found for '{model_name}'. "
        "Assign alias 'production' (preferred) or promote a version to stage 'Production' before running predictions."
    )


def register_and_stage(
    run_id: str,
    model_name: str,
    artifact_path: str = "model",
    stage: str = "Staging",
) -> str:
    """Register a model version from a completed run and assign an alias.

    Returns the registered version string.
    Promotion from staging to production is a deliberate manual step
    (ML_EXPERIMENT_STANDARDS.md §4).
    """
    setup_tracking()
    client = MlflowClient()
    alias = _alias_from_stage(stage)
    result = mlflow.register_model(f"runs:/{run_id}/{artifact_path}", model_name)

    # Use aliases instead of stage transitions (stage API is deprecated).
    client.set_registered_model_alias(
        name=model_name,
        alias=alias,
        version=result.version,
    )
    return result.version
