"""Feature matrix quality assertions — run at the top of every train.py.

Raises DataQualityError with a descriptive message so training aborts cleanly
rather than silently fitting on corrupt data.
"""
from __future__ import annotations

import pandas as pd


class DataQualityError(Exception):
    pass


def assert_feature_matrix(
    df: pd.DataFrame,
    feature_cols: list[str],
    train_end: str,
    val_start: str,
    target_col: str = "trip_count",
    min_rows: int = 10_000,
    max_null_rate: float = 0.05,
) -> None:
    """Run all quality checks on the full feature DataFrame before splitting.

    Args:
        df: Full feature matrix (train + val + test rows).
        feature_cols: List of feature column names to check for nulls.
        train_end: ISO date string — training set must not exceed this.
        val_start: ISO date string — no train row's pickup_hour may be >= this.
        target_col: Name of the target column.
        min_rows: Minimum acceptable row count.
        max_null_rate: Maximum null fraction per feature column (default 5%).
    """
    _check_row_count(df, min_rows)
    _check_null_rates(df, feature_cols, max_null_rate)
    _check_no_future_leakage(df, train_end, val_start)
    _check_no_duplicate_keys(df)
    _check_target_positive(df, target_col)


def _check_row_count(df: pd.DataFrame, min_rows: int) -> None:
    if len(df) < min_rows:
        raise DataQualityError(
            f"Feature matrix has only {len(df):,} rows — expected at least {min_rows:,}. "
            "Check that Gold data was loaded for the full date range."
        )


def _check_null_rates(
    df: pd.DataFrame, feature_cols: list[str], max_null_rate: float
) -> None:
    for col in feature_cols:
        if col not in df.columns:
            raise DataQualityError(
                f"Feature column '{col}' is missing from the DataFrame. "
                "FEATURE_COLS may be out of sync with demand_features.py."
            )
        null_rate = df[col].isna().mean()
        if null_rate > max_null_rate:
            raise DataQualityError(
                f"Column '{col}' has {null_rate:.1%} nulls — exceeds {max_null_rate:.0%} threshold. "
                "Lag features may be missing for early rows; check the lookback window."
            )


def _check_no_future_leakage(
    df: pd.DataFrame, train_end: str, val_start: str
) -> None:
    train_rows = df[df["pickup_hour"] <= pd.Timestamp(train_end)]
    if train_rows.empty:
        return
    max_train_ts = train_rows["pickup_hour"].max()
    val_start_ts = pd.Timestamp(val_start)
    if max_train_ts >= val_start_ts:
        raise DataQualityError(
            f"Training rows extend into the validation period: "
            f"max train pickup_hour={max_train_ts}, val_start={val_start_ts}. "
            "This indicates a data leakage bug in the split logic."
        )


def _check_no_duplicate_keys(df: pd.DataFrame) -> None:
    key_cols = ["pickup_hour", "pu_location_id"]
    missing = [c for c in key_cols if c not in df.columns]
    if missing:
        return  # can't check — columns may not be present in all contexts
    n_dupes = df.duplicated(subset=key_cols).sum()
    if n_dupes > 0:
        raise DataQualityError(
            f"Found {n_dupes:,} duplicate (pickup_hour, pu_location_id) rows. "
            "The Gold table may have been loaded multiple times for the same period."
        )


def _check_target_positive(df: pd.DataFrame, target_col: str) -> None:
    if target_col not in df.columns:
        return
    neg_count = (df[target_col] < 0).sum()
    if neg_count > 0:
        raise DataQualityError(
            f"Target column '{target_col}' contains {neg_count:,} negative values. "
            "trip_count must be non-negative — check the Gold aggregation query."
        )
