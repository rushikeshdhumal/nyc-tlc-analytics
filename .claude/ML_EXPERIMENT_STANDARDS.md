# ML Experiment Standards

Defines MLflow experiment naming, required logged fields, model promotion rules,
and run hygiene for all ML models in this project.

---

## 1. Experiment Naming Convention

One MLflow experiment per model × grain combination:

| Model | Experiment Name |
|---|---|
| Demand Forecasting | `demand_forecast_hourly` |
| Anomaly Detection | `anomaly_detection_daily` |
| Congestion Pricing DiD | `congestion_pricing_did` |

Never log runs from different models into the same experiment.

---

## 2. Required Logged Fields Per Run

Every training run must log all of the following before the run is considered complete.

### Parameters (`mlflow.log_param`)

| Parameter | Description | Example |
|---|---|---|
| `model_type` | Algorithm name | `lightgbm` |
| `run_date` | Date the training script was executed | `2026-04-18` |
| `train_start` | Start date of training data | `2024-01-01` |
| `train_end` | End date of training data | `2025-10-31` |
| `val_start` | Start date of validation window | `2025-11-01` |
| `val_end` | End date of validation window | `2025-12-31` |
| `test_start` | Start date of holdout window | `2026-01-01` |
| `test_end` | End date of holdout window | `2026-01-31` |
| `features` | Comma-separated list of feature names | `hour_of_day,lag_168h_trip_count,...` |
| `n_features` | Total number of features | `12` |
| `hyperparams` | JSON string of model hyperparameters | `{"n_estimators": 500, "lr": 0.05}` |

### Metrics (`mlflow.log_metric`)

| Metric | Description | Required for |
|---|---|---|
| `val_mae` | Mean Absolute Error on validation set | Demand forecasting |
| `val_rmse` | Root Mean Squared Error on validation set | Demand forecasting |
| `val_mape` | Mean Absolute Percentage Error on validation set | Demand forecasting |
| `test_mae` | MAE on holdout set | Demand forecasting |
| `test_rmse` | RMSE on holdout set | Demand forecasting |
| `test_mape` | MAPE on holdout set | Demand forecasting |
| `baseline_mape` | Naive lag-168 MAPE on holdout set | Demand forecasting |
| `mape_vs_baseline` | `baseline_mape - test_mape` (positive = model beats baseline) | Demand forecasting |
| `anomaly_threshold` | Z-score threshold used | Anomaly detection |
| `anomalies_flagged` | Number of flagged rows in scoring run | Anomaly detection |
| `did_estimate` | DiD β₃ coefficient | Congestion pricing |
| `p_value` | p-value of DiD estimate | Congestion pricing |
| `r_squared` | R² of DiD regression | Congestion pricing |

### Artifacts (`mlflow.log_artifact`)

| Artifact | Description |
|---|---|
| `feature_importance.png` | Bar chart of top 20 feature importances (demand model) |
| `predictions_vs_actuals.png` | Line chart of holdout predictions vs actuals |
| `residuals.png` | Residual plot on holdout set |

### Model (`mlflow.sklearn.log_model` or `mlflow.lightgbm.log_model`)
- Log the trained model object under the artifact path `model/`
- Set `registered_model_name` only when promoting to Model Registry (see §4)

---

## 3. Run Naming Convention

Set `mlflow.set_tag("mlflow.runName", ...)` using this format:

```
{model_type}__{train_end}__{val_mape:.1f}pct
```

Examples:
- `lightgbm__2025-10-31__8.3pct`
- `lightgbm__2025-10-31__12.1pct`

This makes runs scannable in the MLflow UI without opening each one.

---

## 4. Model Registry and Promotion Rules

### Stages
MLflow Model Registry uses three stages:

| Stage | Meaning |
|---|---|
| `Staging` | Candidate model — passed validation, not yet promoted |
| `Production` | Current live model — used by Airflow DAG for predictions |
| `Archived` | Superseded versions — kept for reproducibility |

### Promotion criteria (demand forecasting)
A model may be promoted from `Staging` → `Production` only if:
1. `test_mape` < current Production model's `test_mape`
2. `mape_vs_baseline` > 0 (beats the naive lag-168 baseline)
3. All required params, metrics, and artifacts are logged

### Promotion criteria (anomaly detection)
No quantitative threshold — manual review of `anomalies_flagged` count and
`predictions_vs_actuals.png` before promotion.

### Promotion criteria (congestion pricing DiD)
One-shot analysis — no Production stage. Register under `Staging` only.
Document `did_estimate` and `p_value` in the ADR.

---

## 5. Airflow DAG Integration

- The `retrain_demand_forecast` DAG loads the `Production` stage model from
  MLflow Registry by name: `models:/demand_forecast_hourly/Production`
- If no `Production` model exists, the DAG must fail explicitly with a clear
  error — never fall back to a stale local file
- After retraining, the DAG registers the new model as `Staging` and logs
  a comparison metric. Promotion to `Production` is a manual step.

---

## 6. MLflow Tracking Server

| Setting | Value |
|---|---|
| Tracking URI (inside Docker) | `http://mlflow:5000` |
| Tracking URI (local terminal) | `http://localhost:5000` |
| Artifact store | `./mlflow/artifacts` (bind-mounted volume) |
| Backend store | SQLite at `./mlflow/mlflow.db` |

Set in all training scripts:
```python
import mlflow
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
```
