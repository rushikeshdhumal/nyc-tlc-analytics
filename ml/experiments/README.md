# Experiment Log — Demand Forecasting

Record every experiment cycle here. One entry per run_date / experiment session.
Link MLflow run IDs so findings are reproducible.

---

## Template

```
## YYYY-MM-DD — Stage N: <stage name>

**run_date**: YYYY-MM-DD  
**MLflow experiment**: demand_forecast_hourly  
**Splits**: train YYYY-MM-DD → YYYY-MM-DD | val YYYY-MM-DD → YYYY-MM-DD | test YYYY-MM-DD → YYYY-MM-DD

### Runs
| MLflow Run ID | Model / Config | val_mape | test_mape | mape_vs_baseline | Notes |
|---|---|---|---|---|---|
| abc123 | lightgbm default | 12.3% | 13.1% | +2.4% | baseline |

### Findings
- ...

### Next step
- ...
```

---

## 2026-04-21 — Stage 2: Baseline Comparison

**run_date**: 2026-04-21
**MLflow experiment**: demand_forecast_hourly
**Splits**: train 2024-01-08 → 2025-12-31 | val 2026-01-01 → 2026-01-31 | test 2026-02-01 → 2026-02-28

### Runs
| MLflow Run ID | Model / Config | test_mape | Notes |
|---|---|---|---|
| 9aec9bad | naive lag-168 | 236.38% | primary benchmark per ADR-005 |
| faf657fc | seasonal naive (avg lag cols) | 124.12% | |
| 2ca53f48 | Ridge (alpha=1.0, all features) | 99.33% | best baseline |

### Findings
- All baseline MAPEs are high (~100–236%) because the aggregate MAPE is dominated by low-demand zone-hours (37% of rows have <5 trips — small denominators inflate percentage errors). This is consistent with EDA: median per-zone lag-168 MAPE was 28.9% but mean was 89.7%.
- Ridge (99.33%) is the binding baseline to beat. LightGBM with lag_1h (r=0.951) should beat this comfortably.
- The lag-168 MAPE (236%) is extremely high for the Feb 2026 test period — likely driven by residual congestion pricing disruption in Manhattan CBD zones.

### Next step
- Stage 3: run `feature_ablation.py` to identify which feature groups drive MAPE reduction

## 2026-04-21 — Stage 3: Feature Ablation

**run_date**: 2026-04-21  
**MLflow experiment**: demand_forecast_hourly  
**Splits**: same as Stage 2

### Runs
| Variant | n_features | test_mape | delta vs full |
|---|---|---|---|
| full (all 12) | 12 | 35.33% | — |
| no_rolling | 10 | 36.15% | +0.82% |
| no_congestion | 11 | 35.55% | +0.22% |
| **no_borough_enc** | **11** | **35.22%** | **-0.11% (better)** |
| no_lag | 6 | 68.53% | +33.20% |
| calendar_only | 5 | 72.57% | +37.24% |

### Findings
- **Lag features are critical**: removing them doubles MAPE (35.33% → 68.53%). lag_1h (r=0.951) is the dominant signal.
- **Rolling features are marginal**: only +0.82% without them. Could be pruned without meaningful loss.
- **Congestion fees are negligible at aggregate level**: +0.22% — likely matters more for Manhattan CBD zones specifically, keep for now.
- **Borough encoding slightly hurts**: -0.11% improvement without it — `pu_location_id` already encodes zone identity; `pickup_borough_enc` is a coarser duplicate that adds noise.
- **LightGBM (full, 35.33%) vs best baseline (Ridge, 99.33%)**: Stage 2 gate passed with a 64 percentage point improvement.

### Decision: remove `pickup_borough_enc` from FEATURE_COLS
The ablation confirms it's redundant. Update `demand_features.py` before Stage 4.

### Next step
- Update FEATURE_COLS (remove pickup_borough_enc), delete cache, run Stage 4 model comparison

## 2026-04-21 — Stage 4 Preflight: MLflow Tracking Compatibility Fix

**Context**
- Stage 4 (`model_comparison.py`) failed during `model.log_model()` with:
	`API request to endpoint /api/2.0/mlflow/logged-models failed with error code 404`.

**Root cause**
- Local Python environment had `mlflow==3.11.1` while Docker MLflow server was
	`2.19.0`.
- The 3.x client calls newer logged-model APIs not available on the 2.19 server,
	causing artifact/model logging to fail even though metrics logging worked.

**Fix applied**
- Enforced clean, server-backed tracking in experiment scripts (removed local
	`file:./mlruns` fallback).
- Added a guard in `ml/utils/mlflow_utils.py` to reject file-based tracking URIs.
- Aligned local client and server to `mlflow==2.19.0`.

**Preflight checks before Stage 4**
- Ensure required services are up:
	`docker compose up -d postgres postgres-init mlflow`
- Confirm server version:
	`docker compose exec -T mlflow mlflow --version`
- Confirm local version (inside `.venv-ml`):
	`python -c "import mlflow; print(mlflow.__version__)"`
- Required state: both print `2.19.0`.

**Why this matters**
- Keeps MLflow logging clean in a single backend (no split lineage).
- Preserves model artifact logging for Stage 4+ instead of disabling it.

## 2026-04-21 — Stage 4: Model Comparison

**run_date**: 2026-04-21  
**MLflow experiment**: demand_forecast_hourly  
**Splits**: train 2024-01-08 → 2025-12-31 | val 2026-01-01 → 2026-01-31 | test 2026-02-01 → 2026-02-28

### Runs
| Model | val_mape | test_mape | Notes |
|---|---|---|---|
| LightGBM | 35.33% | 35.22% | best model |
| XGBoost | 48.92% | 48.12% | significantly behind LightGBM |
| Ridge | 96.88% | 99.39% | near Stage 2 baseline range |

### Findings
- Stage 4 executed successfully with clean server-backed MLflow tracking and model artifact logging.
- LightGBM is the clear winner for this split (large margin vs XGBoost and Ridge).
- MLflow warnings about missing model signature/input example are non-blocking for this phase; runs were logged successfully.

### Next step
- Proceed to Stage 4b (ensemble exploration). Only keep an ensemble if it improves over LightGBM by >0.5% test MAPE.

## 2026-04-22 — Stage 4b: Ensemble Exploration

**run_date**: 2026-04-22  
**MLflow experiment**: demand_forecast_hourly  
**Splits**: same windowing as Stage 4 (latest monthly holdout)

### Runs
| Strategy | test_mape | gain vs best individual | Threshold (>0.5%) | Result |
|---|---|---|---|---|
| weighted_blend | 40.67% | -5.45% | Not met | FAIL |
| rank_average | 39.73% | -4.51% | Not met | FAIL |
| stacking (Ridge meta) | 43.12% | -7.90% | Not met | FAIL |

### Findings
- No ensemble strategy improved over the best individual model.
- LightGBM remains the best candidate.
- Stage 4b gate failed (required improvement >0.5% test MAPE).

### Next step
- Proceed to Stage 5 (LightGBM-only hyperparameter tuning).

## 2026-04-22 — Stage 5: Hyperparameter Tuning (Optuna)

**run_date**: 2026-04-22  
**MLflow experiment**: demand_forecast_hourly  
**Optuna study**: 100 trials, TPE sampler, validation MAPE minimization

### Best Trial Result
| Metric | Value |
|---|---|
| best_trial | 64/100 |
| val_mape | 35.20% |
| test_mape | 34.84% |
| gain_vs_stage4 | +0.38% |
| **Gate (> +0.5%)** | **FAIL** |

### Tuned Hyperparams (Trial 64)
```json
{
  "learning_rate": 0.0524,
  "num_leaves": 241,
  "max_depth": 14,
  "min_child_samples": 45,
  "feature_fraction": 0.923,
  "bagging_fraction": 0.678,
  "bagging_freq": 5,
  "lambda_l1": 9.777,
  "lambda_l2": 0.00006
}
```

### Findings
- Optuna found modest improvement over Stage 4 defaults: +0.38% test MAPE gain.
- Falls 0.12 percentage points short of the >0.5% gate threshold.
- Stage 5 gate: **FAIL** — discard tuned params.

### Next step
- Proceed to Stage 6 (final evaluation) using Stage 4 LightGBM defaults (test_mape 35.22%).

---

## Status — Model Coverage

LightGBM is the only model fully implemented through the 7-stage iterative workflow. XGBoost, LSTM, and TabNet forecaster implementations are **postponed** and will be developed in a future iteration. When resumed, each model will follow the same Stages 2–7 protocol defined in `ML_DEVELOPMENT_WORKFLOW.md`.