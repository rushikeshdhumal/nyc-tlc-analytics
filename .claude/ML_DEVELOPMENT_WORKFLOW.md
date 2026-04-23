# ML Development Workflow

Defines the end-to-end iterative development process for all ML models in this
project — from data exploration through production promotion. This document is
the authority on *how* models are developed; `ML_FEATURE_CONTRACTS.md` defines
*what* features are used and `ML_EXPERIMENT_STANDARDS.md` defines *how* runs
are logged.

---

## 0. Hardware Context & Constraints

**System**: AMD Ryzen 7 7735HS (8c/16t, 3.2 GHz) · 16 GB RAM (15.2 GB usable)
· AMD Radeon RX 7700S (8 GB VRAM) · Windows 11

### GPU Acceleration Reality

The RX 7700S is an AMD GPU. On Windows, **CUDA is not available**.
The only viable GPU acceleration path is **DirectML via PyTorch**:

```
pip install torch-directml
```

DirectML covers the core ops needed for LSTM, MLP, and TabNet.
It is slower than CUDA equivalent (~30–50%) but meaningfully faster than CPU
for batch matrix ops. TensorFlow has no maintained DirectML support on Windows
— PyTorch is the only DL framework to use here.

ROCm (AMD's full GPU compute stack) requires Linux. Do not attempt WSL2 + ROCm
for this project — the Docker bind-mount complexity outweighs the benefit.

### Memory Budget — Training Tiers

Docker services consume ~6–8 GB RAM when fully running. Available RAM for
training varies by which services are active:

| Tier | Services running | Available for training | Use for |
|---|---|---|---|
| **Tier 1** | All (Airflow + Postgres + Redis + MLflow + Superset + Jupyter) | ~7 GB | LightGBM, XGBoost, Ridge, feature ablation, Optuna <50 trials |
| **Tier 2** | Postgres + MLflow + Jupyter (stop Airflow workers + Superset) | ~10 GB | TabNet, compact LSTM, stacking ensembles, Optuna 50–150 trials |
| **Tier 3** | Postgres + MLflow only (Jupyter runs natively, not in Docker) | ~12 GB | TFT (small config), large ensembles, Optuna 150+ trials |

**Rule**: always confirm which tier a training run requires before starting.
OOM mid-run wastes more time than stopping containers upfront.

Stop Airflow workers: `docker compose stop airflow-worker airflow-scheduler`
Stop Superset: `docker compose stop superset`
Restart all: `docker compose up -d`

---

## 1. Guiding Principles

- **Exploration is code**: all notebook work imports from `ml/` — no logic lives
  only in notebooks. When a feature or approach is proven, it is promoted to
  `ml/features/` or `ml/experiments/` and the notebook is kept as a record.
- **Every comparison is logged**: no mental-note comparisons. Every model variant,
  feature set change, and baseline is an MLflow run with full params and metrics.
- **Baselines first**: no model is evaluated in isolation. It must beat at minimum
  two baselines (naive + statistical) before entering hyperparameter tuning.
- **Splits never change mid-experiment**: once a `run_date` is chosen for an
  experiment cycle, all variants in that cycle use the identical splits.
- **Stage gates**: each stage has explicit exit criteria. Do not advance until met.
- **Hardware-aware scheduling**: check the memory tier table before running.
  Gradient boosting = Tier 1. DL = Tier 2+. Large ensembles = Tier 2+.

---

## 2. Directory Structure

```
ml/
├── features/
│   ├── demand_features.py         # canonical feature set (FEATURE_COLS, build_feature_matrix)
│   ├── anomaly_features.py        # rolling z-score statistics (Phase 9)
│   └── causal_features.py         # DiD treatment/control assignment (Phase 8)
│
├── experiments/                   # structured comparison scripts — not production code
│   ├── demand_forecast/
│   │   ├── baseline_comparison.py     # lag-168, seasonal naive, linear regression
│   │   ├── feature_ablation.py        # systematic add/remove features, MLflow per run
│   │   ├── model_comparison.py        # all candidates via BaseForecaster interface
│   │   └── ensemble_comparison.py     # stacking / blending experiments
│   └── README.md                      # experiment log: run_date, findings, MLflow run IDs
│
├── models/
│   ├── base_forecaster.py         # NEW: model-agnostic interface (Protocol)
│   ├── demand_forecast/
│   │   ├── lgbm_forecaster.py     # LightGBM implementing BaseForecaster
│   │   ├── xgb_forecaster.py      # XGBoost implementing BaseForecaster [POSTPONED]
│   │   ├── lstm_forecaster.py     # PyTorch LSTM implementing BaseForecaster [POSTPONED]
│   │   ├── tabnet_forecaster.py   # TabNet implementing BaseForecaster [POSTPONED]
│   │   ├── ensemble_forecaster.py # stacking / blend wrapper
│   │   ├── train.py               # production training entry point
│   │   └── predict.py             # write predictions to Snowflake ML schema
│   ├── anomaly_detection/
│   │   ├── train.py
│   │   └── score.py
│   └── causal_inference/
│       └── congestion_pricing_did.py
│
├── utils/
│   ├── mlflow_utils.py            # existing: get_or_create_experiment, register_and_stage
│   ├── snowflake_io.py            # existing: read/write Snowflake
│   ├── data_quality.py            # NEW: feature matrix assertions before training
│   ├── evaluation.py              # NEW: walk-forward CV, error segmentation by zone/hour
│   └── shap_utils.py              # NEW: SHAP for tree models + DeepExplainer for DL
│
├── notebooks/
│   ├── demand_forecast/
│   │   ├── 00_eda.ipynb
│   │   ├── 01_baselines.ipynb
│   │   ├── 02_feature_engineering.ipynb
│   │   ├── 03_model_selection.ipynb
│   │   ├── 04_ensemble_exploration.ipynb
│   │   ├── 05_hyperparameter_tuning.ipynb
│   │   └── 06_error_analysis.ipynb
│   ├── anomaly_detection/
│   │   ├── 00_eda.ipynb
│   │   ├── 01_threshold_selection.ipynb
│   │   └── 02_error_analysis.ipynb
│   └── causal_inference/
│       ├── 00_eda.ipynb
│       ├── 01_did_specification.ipynb
│       └── 02_robustness_checks.ipynb
│
└── requirements.txt
```

---

## 3. Model-Agnostic Interface

All model implementations must conform to `BaseForecaster` so that
`model_comparison.py` and `ensemble_forecaster.py` can swap models without
framework-specific branching.

```python
# ml/models/base_forecaster.py
from typing import Protocol
import numpy as np

class BaseForecaster(Protocol):
    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> None: ...

    def predict(self, X: np.ndarray) -> np.ndarray: ...

    def log_model(self, artifact_path: str) -> None:
        """Log the trained model to the active MLflow run."""
        ...

    @property
    def model_type(self) -> str:
        """Short identifier logged as mlflow param 'model_type'."""
        ...
```

Each implementation wraps its framework's training loop. `train.py` remains the
production entry point and instantiates the best model class directly — the
protocol is used only in experiment scripts.

---

## 4. Model Candidate Registry

Hardware feasibility is assessed against the memory tier table in §0.

### Demand Forecasting

| Model | Framework | Tier | SHAP | Notes |
|---|---|---|---|---|
| `LightGBM` | lightgbm | 1 | TreeExplainer | Current production choice |
| `XGBoost` | xgboost | 1 | TreeExplainer | **POSTPONED** — will be implemented in a future iteration |
| `Ridge Regression` | sklearn | 1 | LinearExplainer | Strong interpretable baseline |
| `LightGBM + log target` | lightgbm | 1 | TreeExplainer | Try if EDA shows heavy right skew |
| `TabNet` | pytorch-tabnet | 2 | attention weights | **POSTPONED** — will be implemented in a future iteration |
| `LSTM (compact)` | pytorch + DirectML | 2 | DeepExplainer | **POSTPONED** — will be implemented in a future iteration |
| `LightGBM + XGBoost stack` | lightgbm + xgboost | 2 | per-model | Blend predictions via meta-learner |
| `TFT (small config)` | pytorch + DirectML | 3 | attention weights | Only if multi-step horizon needed |

**TFT note**: ADR-005 deferred TFT to multi-step forecasting. Do not attempt
TFT unless the forecast horizon expands beyond 1 month. At that point revisit
hardware tier and consider a cloud GPU for the training run.

### Anomaly Detection

z-score threshold is the production approach. Model selection (Stage 4) becomes
threshold sensitivity analysis and isolation forest comparison only.

### Causal Inference (DiD)

OLS with fixed effects is the only appropriate estimator. Stage 4 = robustness
checks (varying fixed effects, placebo tests, parallel trends plot).

---

## 5. Staged Experiment Protocol

All model development follows this 7-stage process in order.
Each stage has entry requirements and exit criteria.

---

### Stage 1 — EDA

**Goal**: understand the raw signal before committing to any model approach.

**Entry**: Gold table populated and queryable.

**Notebook**: `notebooks/{model}/00_eda.ipynb`

**What to do**:
- Distribution of target (trip_count, revenue) — skew, outliers, log-transform candidate?
- Temporal patterns: hourly, daily, weekly, monthly seasonality
- Zone-level variation: high-volume vs. sparse zones
- Missing value patterns in lag features
- Correlation matrix of candidate features vs. target

**Exit criteria**:
- Target distribution characterized (log-transform: yes/no)
- Dominant seasonality period confirmed (weekly for demand)
- Data quality issues per zone/hour flagged
- Findings written as markdown summary cell at notebook top

---

### Stage 2 — Baseline Establishment

**Goal**: set a quantitative minimum bar before any model is trained.

**Entry**: EDA complete. `run_date` fixed for this experiment cycle.

**Notebook**: `notebooks/{model}/01_baselines.ipynb`
**Script**: `experiments/{model}/baseline_comparison.py` (Tier 1)

**Required baselines — demand forecasting**:

| Baseline | Description | MLflow run name |
|---|---|---|
| `naive_lag168` | last week same-hour value | `baseline__naive_lag168__<run_date>` |
| `seasonal_naive` | median of same hour over last 4 weeks | `baseline__seasonal_naive__<run_date>` |
| `linear_ols` | Ridge regression on calendar features only | `baseline__linear_ols__<run_date>` |

All baselines use identical splits. All logged to the same MLflow experiment.

**Exit criteria**:
- All baselines logged with MAPE / MAE / RMSE
- Minimum promotion bar recorded in `experiments/README.md`

---

### Stage 3 — Feature Engineering

**Goal**: validate and expand the canonical feature set.

**Entry**: Baselines logged and recorded.

**Notebook**: `notebooks/{model}/02_feature_engineering.ipynb`
**Script**: `experiments/{model}/feature_ablation.py` (Tier 1)

**Process**:
1. Start from `FEATURE_COLS` in `ML_FEATURE_CONTRACTS.md`
2. Each candidate new feature: train quick model (500 rounds), log `val_mape`
3. Each existing feature: remove it, retrain, measure MAPE delta
4. Leakage check: `|correlation with target| > 0.95` → manual audit required

**Cache invalidation rule**: delete `data/features_*.parquet` whenever
`FEATURE_COLS` changes. Stale cache with new features is silent corruption.

**Sequence models note**: if a compact LSTM is in Stage 4 candidates, add a
`reshape_for_sequence(df, lookback_window)` call after loading the cache.
The Parquet cache stays tabular — reshaping is a model-side responsibility.

**Exit criteria**:
- Final `FEATURE_COLS` locked and updated in `demand_features.py`
- All ablation runs tagged `stage=feature_ablation` in MLflow
- No feature has a leakage risk flag

---

### Stage 4 — Model Selection

**Goal**: identify the best model family on identical splits and features.

**Entry**: Feature set locked.

**Notebook**: `notebooks/{model}/03_model_selection.ipynb`
**Script**: `experiments/{model}/model_comparison.py`

All candidates are implemented as `BaseForecaster` and iterated in a loop:

```python
candidates = [LGBMForecaster(), RidgeForecaster()]  # XGBForecaster, TabNetForecaster postponed
for model in candidates:
    with mlflow.start_run():
        model.fit(X_train, y_train, X_val, y_val)
        val_mape = _mape(y_val, model.predict(X_val))
        mlflow.set_tag("stage", "model_selection")
        mlflow.set_tag("model_type", model.model_type)
        mlflow.log_metric("val_mape", val_mape)
```

**Tier guidance**:
- LightGBM + Ridge: Tier 1 — run simultaneously
- XGBoost: Tier 1 — **POSTPONED**, will be added in a future iteration
- TabNet: Tier 2 — **POSTPONED**, will be added in a future iteration
- Compact LSTM: Tier 2 — **POSTPONED**, will be added in a future iteration

**Exit criteria**:
- Best model type identified by `val_mape`
- Gap vs. second-best assessed: if < 0.3% MAPE difference, prefer simpler model
- Decision + MLflow run IDs recorded in `experiments/README.md`

---

### Stage 4b — Ensemble Exploration

**Goal**: determine if combining models beats the best single model.

**Entry**: Stage 4 complete. Best single model identified.

**Notebook**: `notebooks/{model}/04_ensemble_exploration.ipynb`
**Script**: `experiments/{model}/ensemble_comparison.py` (Tier 2)

**Ensemble strategies (in order of complexity)**:

| Strategy | Description | Memory cost | When to try |
|---|---|---|---|
| **Weighted blend** | `α·pred_lgbm + (1-α)·pred_xgb` | minimal | always — free to try |
| **Rank average** | average of percentile-ranked predictions | minimal | when models have different error scales |
| **Stacking** | meta-learner (Ridge) trained on OOF predictions | ~2× single model | if blend gains > 0.5% MAPE |
| **DL + GBM blend** | blend LSTM predictions with LightGBM | Tier 2 RAM | only if LSTM beats LightGBM in Stage 4 |

**Out-of-fold (OOF) stacking protocol**:
- Generate OOF predictions from base models using walk-forward CV
- Train meta-learner on OOF predictions → evaluate on holdout
- Never train meta-learner on the same fold used by base models

**Ensemble register**: log each ensemble variant as a separate MLflow run
tagged `stage=ensemble_exploration`.

**Exit criteria**:
- Best ensemble vs. best single model: improvement > 0.5% MAPE to justify added complexity
- If no meaningful gain: discard ensembles, proceed with single best model
- Decision recorded in `experiments/README.md`

---

### Stage 5 — Hyperparameter Tuning

**Goal**: optimize the chosen model (single or ensemble).

**Entry**: Model architecture confirmed in Stage 4 / 4b.

**Notebook**: `notebooks/{model}/05_hyperparameter_tuning.ipynb`
**Tool**: Optuna with MLflow auto-logging. All runs tagged `stage=hyperparam_tuning`.

**Run against cached features** — zero Snowflake credits for all tuning runs.

**Search spaces by model type**:

```python
# LightGBM / XGBoost (Tier 1 — 100 trials feasible)
params = {
    "num_leaves":        trial.suggest_int("num_leaves", 31, 255),
    "learning_rate":     trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
    "feature_fraction":  trial.suggest_float("feature_fraction", 0.5, 1.0),
    "bagging_fraction":  trial.suggest_float("bagging_fraction", 0.5, 1.0),
    "min_child_samples": trial.suggest_int("min_child_samples", 10, 100),
}

# TabNet (Tier 2 — 30 trials; each trial ~5–10 min on DirectML)
params = {
    "n_d":           trial.suggest_int("n_d", 8, 64),
    "n_steps":       trial.suggest_int("n_steps", 3, 10),
    "gamma":         trial.suggest_float("gamma", 1.0, 2.0),
    "learning_rate": trial.suggest_float("learning_rate", 1e-4, 1e-1, log=True),
    "batch_size":    trial.suggest_categorical("batch_size", [1024, 4096, 16384]),
}

# Compact LSTM (Tier 2 — 20 trials; each trial ~10–20 min on DirectML)
params = {
    "hidden_size":   trial.suggest_int("hidden_size", 32, 256),
    "num_layers":    trial.suggest_int("num_layers", 1, 3),
    "dropout":       trial.suggest_float("dropout", 0.0, 0.5),
    "learning_rate": trial.suggest_float("learning_rate", 1e-4, 1e-2, log=True),
    "batch_size":    trial.suggest_categorical("batch_size", [512, 2048, 8192]),
}
```

**Pruner**: `MedianPruner` — kills unpromising trials after 10% of epochs/rounds.
This is critical for DL trials where each trial is expensive.

**Trial budget by tier**:
- Tier 1 models: 100 trials
- Tier 2 models: 30 trials (DirectML), 20 trials (CPU-only)

**Exit criteria**:
- Best params identified and updated in model's `train.py` or forecaster class
- Improvement over default params > 0.5% MAPE (otherwise keep defaults)
- Best run tagged `stage=hyperparam_best`

---

### Stage 6 — Final Evaluation

**Goal**: rigorous validation before production registration.

**Entry**: Hyperparameters locked.

**Notebook**: `notebooks/{model}/06_error_analysis.ipynb`

**What to run**:

1. **Walk-forward cross-validation** (`ml/utils/evaluation.py`):
   - 3 consecutive test months via `_compute_splits()`
   - Report mean ± std of `test_mape`
   - CV std < 2.0% required for promotion

2. **SHAP / interpretability** (`ml/utils/shap_utils.py`):
   - Tree models: `TreeExplainer` — fast, exact
   - DL models: `DeepExplainer` (PyTorch) — approximate; use 200-row background sample
   - Log `shap_summary.png` to MLflow
   - Verify top features align with EDA findings

3. **Error segmentation** (`ml/utils/evaluation.py`):
   - MAPE by `pu_location_id` and by `hour_of_day`
   - Log `error_by_zone.png` and `error_by_hour.png` to MLflow

4. **Final production run**:
   - `train.py --run-date <current_run_date>` — no cache, fresh Snowflake query
   - All required params/metrics/artifacts logged per `ML_EXPERIMENT_STANDARDS.md §2`

**Promotion criteria**:
- `test_mape` < current Production model
- `mape_vs_baseline` > 0
- Walk-forward CV std < 2.0%
- All required MLflow fields present

**Exit criteria = promotion decision**:
- PASS → manually promote `Staging` → `Production` in MLflow UI
- FAIL → return to Stage 3 or Stage 5 with a documented hypothesis

---

## 6. Per-Model Applicability Matrix

| Stage | Demand Forecast | Anomaly Detection | DiD (Causal) |
|---|---|---|---|
| 1. EDA | full | full | full |
| 2. Baselines | 3 baselines | z-score fixed threshold | naive mean diff |
| 3. Feature engineering | full ablation | threshold sensitivity | specification testing |
| 4. Model selection | all candidates in registry | isolation forest vs z-score | robustness checks only |
| 4b. Ensemble | blend + stacking | not applicable | not applicable |
| 5. Hyperparameter tuning | Optuna (tier-dependent budget) | not applicable | not applicable |
| 6. Final evaluation | walk-forward CV + SHAP + segmentation | manual anomaly review | p-value + DiD plot |

---

## 7. Shared Utilities

### `ml/models/base_forecaster.py`
`BaseForecaster` Protocol — see §3. All model implementations must conform.

### `ml/utils/data_quality.py`
Assertions run at the top of every `train.py` before the model trains:
- Row count within expected range for the date window
- Null rate in each feature column < 5% (lag features)
- No future leakage: max `pickup_hour` in train set < `val_start`
- No duplicate `(pickup_hour, pu_location_id)` rows

Raises `DataQualityError` — training aborts with a descriptive message.

### `ml/utils/evaluation.py`
- `walk_forward_cv(forecaster, run_dates, n_windows)` → MAPE mean/std
- `segment_errors(y_true, y_pred, df, group_col)` → per-group MAPE DataFrame
- `plot_error_by_segment(segment_df, title)` → PNG for MLflow artifact
- `reshape_for_sequence(df, feature_cols, target_col, lookback)` → 3D array for LSTM/TFT

### `ml/utils/shap_utils.py`
Routes to the correct explainer based on model type:
- `TreeExplainer` for LightGBM, XGBoost
- `LinearExplainer` for Ridge
- `DeepExplainer` for PyTorch models (LSTM, TabNet)
- Logs `shap_summary.png` to the active MLflow run

---

## 8. Experiment Tracking Discipline

Every MLflow run must carry a `stage` tag:

```python
mlflow.set_tag("stage", "baseline")             # Stage 2
mlflow.set_tag("stage", "feature_ablation")     # Stage 3
mlflow.set_tag("stage", "model_selection")      # Stage 4
mlflow.set_tag("stage", "ensemble_exploration") # Stage 4b
mlflow.set_tag("stage", "hyperparam_tuning")    # Stage 5
mlflow.set_tag("stage", "hyperparam_best")      # Stage 5 best trial
mlflow.set_tag("stage", "production_candidate") # Stage 6 final run
```

---

## 9. Infrastructure

### JupyterLab (add to docker-compose.yml)
```yaml
jupyter:
  image: jupyter/scipy-notebook:latest
  ports:
    - "8888:8888"
  volumes:
    - .:/home/jovyan/work
  environment:
    - MLFLOW_TRACKING_URI=http://mlflow:5000
    - SNOWFLAKE_ACCOUNT=${SNOWFLAKE_ACCOUNT}
    - SNOWFLAKE_USER=${SNOWFLAKE_USER}
    - SNOWFLAKE_PASSWORD=${SNOWFLAKE_PASSWORD}
    - SNOWFLAKE_WAREHOUSE=${SNOWFLAKE_WAREHOUSE}
    - SNOWFLAKE_DATABASE=${SNOWFLAKE_DATABASE}
    - SNOWFLAKE_ROLE=${SNOWFLAKE_ROLE}
  networks:
    - nyc_tlc_backend
```

### PyTorch DirectML (for DL experiments on AMD GPU)
Add to `ml/requirements.txt`:
```
torch
torch-directml>=0.2
pytorch-tabnet>=4.1
```

Usage in DL forecaster classes:
```python
import torch_directml
device = torch_directml.device()  # uses RX 7700S via DirectML
# falls back to CPU if DirectML unavailable
```

### Optuna
Add to `ml/requirements.txt`:
```
optuna>=3.6
optuna-integration[mlflow]>=3.6
```

---

## 10. Branch Strategy

```
main
 └── ml-phase2                              # top-level ML branch — merges into main when all phases complete
      ├── ml/demand-forecast                # Phase 7 core pipeline: train, predict, Airflow DAG
      │    └── ml/demand-forecast-iterative-dev   # quality layer: utils, notebooks, experiments
      ├── ml/phase8-...                     # Phase 8 (DiD), future
      └── ml/phase9-...                     # Phase 9 (anomaly detection), future
```

**Merge order**:
1. `ml/demand-forecast-iterative-dev` → PR into `ml/demand-forecast` (quality layer completes Phase 7)
2. `ml/demand-forecast` (complete Phase 7) → PR into `ml-phase2`
3. Phase 8 and Phase 9 branch from `ml-phase2` after step 2 merges — they inherit
   `BaseForecaster`, all shared utils, and the notebook structure
4. `ml-phase2` → PR into `main` when all ML phases are complete

---

## 11. Implementation Checklist

### Infrastructure (blocks everything else)
- [ ] Add JupyterLab to `docker-compose.yml`
- [ ] Add Optuna + torch-directml + pytorch-tabnet to `ml/requirements.txt`
- [ ] Create `ml/notebooks/` directory structure
- [ ] Create `ml/experiments/` directory structure

### Shared Utilities
- [ ] `ml/models/base_forecaster.py` — BaseForecaster Protocol
- [ ] `ml/utils/data_quality.py` — feature matrix assertions
- [ ] `ml/utils/evaluation.py` — walk-forward CV + segmentation + sequence reshape
- [ ] `ml/utils/shap_utils.py` — tree + DL SHAP routing
- [ ] Add `stage` tag to existing `train.py`

### Model Implementations (BaseForecaster)
- [ ] `ml/models/demand_forecast/lgbm_forecaster.py`
- [ ] `ml/models/demand_forecast/xgb_forecaster.py` **(POSTPONED — future iteration)**
- [ ] `ml/models/demand_forecast/ridge_forecaster.py`
- [ ] `ml/models/demand_forecast/tabnet_forecaster.py` (Tier 2) **(POSTPONED — future iteration)**
- [ ] `ml/models/demand_forecast/lstm_forecaster.py` (Tier 2, DirectML) **(POSTPONED — future iteration)**
- [ ] `ml/models/demand_forecast/ensemble_forecaster.py`

### Experiment Scripts
- [ ] `ml/experiments/demand_forecast/baseline_comparison.py`
- [ ] `ml/experiments/demand_forecast/feature_ablation.py`
- [ ] `ml/experiments/demand_forecast/model_comparison.py`
- [ ] `ml/experiments/demand_forecast/ensemble_comparison.py`
- [ ] `ml/experiments/README.md`

### Demand Forecast Notebooks
- [ ] `00_eda.ipynb`
- [ ] `01_baselines.ipynb`
- [ ] `02_feature_engineering.ipynb`
- [ ] `03_model_selection.ipynb`
- [ ] `04_ensemble_exploration.ipynb`
- [ ] `05_hyperparameter_tuning.ipynb`
- [ ] `06_error_analysis.ipynb`

### Production Integration (after Stage 6 pass)
- [ ] Update `train.py` with best model class + tuned params
- [ ] Integrate `data_quality.py` assertions into `train.py`
- [ ] Add SHAP + segmentation artifacts to `train.py` MLflow logging
- [ ] Update `MODULAR_MONOLITH_STRUCTURE.md` with new directories
