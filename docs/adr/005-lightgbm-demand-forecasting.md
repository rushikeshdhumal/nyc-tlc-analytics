# ADR-005: LightGBM for Demand Forecasting

**Status**: Accepted  
**Date**: 2026-04-19  
**Deciders**: Rushikesh Dhumal

---

## Context

Phase 7 requires a model to predict hourly trip count per NYC taxi zone
(`trip_count` at `(pickup_hour, pu_location_id)` granularity). The feature
contract (`.claude/ML_FEATURE_CONTRACTS.md §Model 1`) specifies 12 features:
calendar signals, per-zone lag values (1h, 24h, 168h), rolling averages, and
lagged congestion fees. Training data spans Jan 2024 – Oct 2025 (~22 months,
~4–5 M rows across ~265 zones).

The chosen model must:
1. Handle a mix of calendar (cyclic) and lagged (numerical) features without
   manual encoding.
2. Beat the naive lag-168 baseline on MAPE before being eligible for promotion
   to Production.
3. Be trainable within the free-tier Snowflake + local Docker environment
   (no GPU, limited RAM).
4. Integrate cleanly with MLflow for experiment tracking and model registry.

---

## Options Considered

### Option A: LightGBM (chosen)
Gradient-boosted decision tree library optimised for tabular data.

**Pros**
- Trains in minutes on 5 M rows on a CPU; no GPU required.
- Handles heterogeneous feature types (integers, floats) with no preprocessing.
- `mlflow.lightgbm.log_model` provides a first-class MLflow integration.
- Early stopping on a held-out validation set replaces a full grid search,
  keeping compute cost low.
- Strong track record on Kaggle time-series tabular benchmarks.

**Cons**
- Does not model long-range temporal dependencies natively (no recurrence or
  attention). This is mitigated by explicit lag and rolling features.
- Feature engineering must be done manually; TFT learns temporal patterns
  implicitly.

### Option B: Temporal Fusion Transformer (TFT)
Attention-based deep learning model for multi-horizon time-series forecasting.

**Pros**
- Learns temporal patterns at multiple horizons without manual lag engineering.
- Provides interpretable attention weights.

**Cons**
- Requires GPU or multi-hour CPU training at this dataset scale.
- PyTorch Lightning dependency adds significant Docker image complexity.
- Harder to inspect and debug predictions than a tree model.
- Overkill for a 1-month-ahead point forecast where lag features are abundant.

### Option C: Prophet (Meta)
Additive decomposition model tuned for business time series.

**Pros**
- Handles seasonality and holidays out of the box.
- No feature engineering required.

**Cons**
- Per-zone models required (one Prophet instance per `pu_location_id`); ~265
  separate model objects to train, register, and version.
- No support for exogenous features like congestion fees.
- MLflow integration requires wrapping in `mlflow.pyfunc`.

---

## Decision

**LightGBM** (Option A).

The dataset is tabular and well-described by a fixed feature contract. The 168h
lag feature already encodes the dominant weekly seasonality signal. LightGBM
trains a single model across all zones (using `pu_location_id` as a feature)
which is operationally simpler than 265 per-zone models. The early-stopping
validation approach satisfies the time-series cross-validation requirement
without incurring the compute cost of a full hyperparameter grid search.

TFT is the natural successor if the model needs to forecast multiple steps ahead
(e.g., 30-day horizon) without recursive prediction — this is documented as a
future enhancement.

---

## Consequences

- Feature extraction (`ml/features/demand_features.py`) must materialise all
  12 lag and rolling features before training. The 168h lookback window extends
  the Snowflake pull range by one week.
- A single `lgb.Booster` object covers all 265 zones; zone identity is encoded
  as an integer feature (`pu_location_id`). Zones with sparse data (e.g., EWR)
  may have higher per-zone error — acceptable at this stage.
- Multi-step-ahead forecasting beyond 7 days requires recursive prediction
  (predictions used as pseudo-lags). For the current monthly pipeline the
  prediction window is the most recent completed month, so all lag features
  are available from actual Gold data — no recursion needed.
- Promotion from alias `staging` to alias `production` requires `mape_vs_baseline > 0`
  (model must beat the naive lag-168 baseline on the holdout set). This check
  is logged as `mape_vs_baseline` in MLflow and evaluated manually before
  promotion.
