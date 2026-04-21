"""SHAP explainability utilities — routes to the correct explainer by model type.

Tree models  → shap.TreeExplainer  (exact, fast)
Linear models → shap.LinearExplainer (exact)
PyTorch DL   → shap.DeepExplainer  (approximate; use a small background sample)

Logs shap_summary.png to the active MLflow run.
"""
from __future__ import annotations

import os

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def log_shap_summary(
    model,
    X_sample: np.ndarray,
    feature_names: list[str],
    model_type: str,
    out_path: str = "/tmp/shap_summary.png",
    background_size: int = 200,
) -> str:
    """Compute SHAP values and save a summary plot.

    Args:
        model: Trained model object (lgb.Booster, xgb.Booster, sklearn estimator,
               or torch.nn.Module).
        X_sample: 2D array of shape (n_rows, n_features) — the holdout or a sample.
        feature_names: Feature column names in the same order as X_sample columns.
        model_type: One of "lightgbm", "xgboost", "ridge", "tabnet", "lstm".
        out_path: Where to save the PNG.
        background_size: Number of rows used as DeepExplainer background (DL only).

    Returns:
        out_path — pass directly to mlflow.log_artifact.
    """
    import shap

    shap_values = _compute_shap_values(
        model, X_sample, model_type, background_size
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    shap.summary_plot(
        shap_values,
        X_sample,
        feature_names=feature_names,
        show=False,
        plot_size=None,
    )
    plt.tight_layout()
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close("all")

    try:
        import mlflow
        mlflow.log_artifact(out_path)
    except Exception:
        pass  # no active run — caller may log manually

    return out_path


def _compute_shap_values(
    model,
    X: np.ndarray,
    model_type: str,
    background_size: int,
) -> np.ndarray:
    import shap

    if model_type in ("lightgbm", "xgboost"):
        explainer = shap.TreeExplainer(model)
        return explainer.shap_values(X)

    if model_type == "ridge":
        explainer = shap.LinearExplainer(model, X)
        return explainer.shap_values(X)

    if model_type in ("lstm", "tabnet"):
        return _deep_shap_values(model, X, background_size)

    raise ValueError(
        f"Unknown model_type='{model_type}'. "
        "Expected one of: lightgbm, xgboost, ridge, lstm, tabnet."
    )


def _deep_shap_values(
    model,
    X: np.ndarray,
    background_size: int,
) -> np.ndarray:
    """DeepExplainer for PyTorch models — uses a random background sample."""
    import shap
    import torch

    model.eval()

    n_bg = min(background_size, len(X))
    bg_idx = np.random.choice(len(X), size=n_bg, replace=False)
    background = torch.tensor(X[bg_idx], dtype=torch.float32)
    test_tensor = torch.tensor(X, dtype=torch.float32)

    explainer = shap.DeepExplainer(model, background)
    shap_values = explainer.shap_values(test_tensor)
    if isinstance(shap_values, list):
        shap_values = shap_values[0]
    return np.array(shap_values)
