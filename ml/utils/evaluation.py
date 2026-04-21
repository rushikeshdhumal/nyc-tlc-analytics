"""Evaluation utilities for demand forecasting experiments.

Provides:
- walk_forward_cv: 3-window time-series cross-validation
- segment_errors: per-group MAPE breakdown
- plot_error_by_segment: PNG artifact for MLflow
- reshape_for_sequence: 3D array for LSTM / TFT input
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# Walk-forward cross-validation
# ---------------------------------------------------------------------------

def walk_forward_cv(
    forecaster,
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    run_date: str,
    n_windows: int = 3,
    ingest_start: str = "2024-01-01",
    tlc_lag: int = 2,
) -> dict[str, float]:
    """Run n_windows consecutive monthly test folds, return mean ± std MAPE.

    Each window shifts the test month one month earlier relative to run_date.
    The model is retrained from scratch on each fold using the same class and
    default params as passed in.

    Args:
        forecaster: Any object conforming to BaseForecaster (fit + predict).
        df: Full feature matrix (must cover enough history for all windows).
        feature_cols: Feature column names.
        target_col: Target column name.
        run_date: ISO date — the most-recent fold test end is derived from this.
        n_windows: Number of test months to evaluate (default 3).
        ingest_start: Earliest training data date.
        tlc_lag: Months between run_date and last available Gold month.

    Returns:
        dict with keys: mape_mean, mape_std, mape_per_window (list)
    """
    mapes: list[float] = []

    for window_offset in range(n_windows):
        splits = _compute_splits_offset(run_date, tlc_lag, window_offset, ingest_start)
        fold_df = df.copy()

        train_mask = fold_df["pickup_hour"] <= pd.Timestamp(splits["train_end"])
        val_mask = (
            (fold_df["pickup_hour"] >= pd.Timestamp(splits["val_start"]))
            & (fold_df["pickup_hour"] <= pd.Timestamp(splits["val_end"]))
        )
        test_mask = fold_df["pickup_hour"] >= pd.Timestamp(splits["test_start"])

        train_df = fold_df[train_mask]
        val_df = fold_df[val_mask]
        test_df = fold_df[test_mask]

        if train_df.empty or val_df.empty or test_df.empty:
            continue

        X_train = train_df[feature_cols].values
        y_train = train_df[target_col].values
        X_val = val_df[feature_cols].values
        y_val = val_df[target_col].values
        X_test = test_df[feature_cols].values
        y_test = test_df[target_col].values

        forecaster.fit(X_train, y_train, X_val, y_val)
        y_pred = forecaster.predict(X_test)
        mapes.append(_mape(y_test, y_pred))

    if not mapes:
        return {"mape_mean": float("nan"), "mape_std": float("nan"), "mape_per_window": []}

    return {
        "mape_mean": float(np.mean(mapes)),
        "mape_std": float(np.std(mapes)),
        "mape_per_window": mapes,
    }


def _compute_splits_offset(
    run_date: str,
    tlc_lag: int,
    window_offset: int,
    ingest_start: str,
) -> dict[str, str]:
    """Shift the standard rolling splits back by window_offset extra months."""
    d = date.fromisoformat(run_date[:10]).replace(day=1)
    for _ in range(tlc_lag + window_offset):
        d = date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)

    test_start = d
    test_end = date(d.year, d.month, monthrange(d.year, d.month)[1])

    val_d = date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)
    val_start = val_d
    val_end = date(val_d.year, val_d.month, monthrange(val_d.year, val_d.month)[1])

    train_start = date.fromisoformat(ingest_start)
    train_end = val_start - timedelta(days=1)

    return {
        "train_start": train_start.isoformat(),
        "train_end": train_end.isoformat(),
        "val_start": val_start.isoformat(),
        "val_end": val_end.isoformat(),
        "test_start": test_start.isoformat(),
        "test_end": test_end.isoformat(),
    }


# ---------------------------------------------------------------------------
# Error segmentation
# ---------------------------------------------------------------------------

def segment_errors(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    df: pd.DataFrame,
    group_col: str,
) -> pd.DataFrame:
    """Compute per-group MAPE.

    Returns a DataFrame with columns [group_col, mape, n_rows] sorted by mape desc.
    """
    results = []
    groups = df[group_col].values
    for group in np.unique(groups):
        mask = groups == group
        m = _mape(y_true[mask], y_pred[mask])
        results.append({group_col: group, "mape": m, "n_rows": int(mask.sum())})
    return (
        pd.DataFrame(results)
        .sort_values("mape", ascending=False)
        .reset_index(drop=True)
    )


def plot_error_by_segment(
    segment_df: pd.DataFrame,
    group_col: str,
    title: str,
    out_path: str,
    top_n: int = 20,
) -> str:
    """Save a horizontal bar chart of per-group MAPE to out_path.

    Returns out_path so callers can pass it directly to mlflow.log_artifact.
    """
    plot_df = segment_df.head(top_n).sort_values("mape")
    fig, ax = plt.subplots(figsize=(8, max(4, len(plot_df) * 0.35)))
    ax.barh(plot_df[group_col].astype(str), plot_df["mape"])
    ax.set_xlabel("MAPE (%)")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Sequence reshape for LSTM / TFT
# ---------------------------------------------------------------------------

def reshape_for_sequence(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    lookback: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Reshape a flat 2D feature matrix into 3D sequences for LSTM input.

    Each sample is a sliding window of `lookback` consecutive rows.
    Rows are assumed to be sorted by time within each zone.

    Args:
        df: Feature DataFrame sorted by pickup_hour.
        feature_cols: Features to include in each time step.
        target_col: Target column name.
        lookback: Number of past time steps per sample.

    Returns:
        X: shape (n_samples, lookback, n_features)
        y: shape (n_samples,)
    """
    X_raw = df[feature_cols].values
    y_raw = df[target_col].values

    n = len(X_raw)
    if n <= lookback:
        raise ValueError(
            f"DataFrame has {n} rows but lookback={lookback}. Need at least lookback+1 rows."
        )

    X_seq = np.stack([X_raw[i : i + lookback] for i in range(n - lookback)])
    y_seq = y_raw[lookback:]
    return X_seq, y_seq


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)
