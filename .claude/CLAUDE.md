# CLAUDE.md - Project Intelligence & Rules

## 1. Core Engineering Principles
- **Modular Monolith First**: Keep `orchestration/`, `transform/`, and `infra/` strictly separated.
- **Idempotency**: Every DAG and SQL model must be "run-safe." Running the same code twice should never create duplicate data.
- **Cost Sensitivity**: Always assume we are on a Snowflake Trial. Use `X-SMALL` warehouses and ensure `AUTO_SUSPEND = 60`.

## 2. Technical Standards

### Snowflake & SQL
- **Schema-on-Read**: Ingest raw data as `VARIANT`. 
- **CTEs over Subqueries**: All dbt models must use Common Table Expressions (CTEs) for readability.
- **Upper Case Keywords**: Use `SELECT`, `FROM`, `WHERE` in all SQL files.
- **Metadata**: Every table must include `_ingested_at` and `_batch_id` columns.

### Python & Airflow
- **TaskFlow API**: Prefer `@dag` and `@task` decorators over traditional Operators.
- **Type Hinting**: All Python functions must include type hints (e.g., `def my_task(df: pd.DataFrame) -> str:`).
- **Environment Variables**: Use `os.getenv()` or Airflow Variables; never hardcode secrets.

### dbt (Transformation)
- **Primary Keys**: Every model must have a `unique` and `not_null` test on its primary key.
- **Modular Logic**: Logic goes in the `transform/` folder. Airflow only triggers the execution.

## 3. Project-Specific Guards
- **NYC TLC Data**: Use `MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE` for all `COPY INTO` commands that load directly from a stage file. **Exception**: `copy_into_bronze.sql` uses a `FROM (SELECT ...)` copy transform to inject metadata columns (`_source_file`, `_ingested_at`, `_batch_id`) — Snowflake does not support `MATCH_BY_COLUMN_NAME` with copy transforms, so column mapping is explicit in the SELECT instead.
- **Medallion Integrity**: Silver models must never reference the External Stage directly; they must pull from Bronze tables.
- **Naming**: 
  - Bronze tables prefix: `brz_`
  - Silver models prefix: `stg_` (Staging)
  - Gold models prefix: `fct_` (Fact) or `dim_` (Dimension)

## 4. ML & MLOps Standards

### Feature Engineering
- Features must be extracted exclusively from Gold tables (`fct_` prefix). Never read from Silver or Bronze in ML scripts.
- All feature extraction scripts live in `ml/features/`. They must be idempotent — re-running for the same date range produces the same feature matrix.
- Train/validation/test splits must always be **time-based**. Never shuffle time-series data randomly — this causes data leakage.
- The leakage boundary: only data available at prediction time (i.e., prior periods) may be used as features. No future values, no same-period targets as features.

### MLflow
- Every training run must log: model params, eval metrics (MAE, RMSE, MAPE), feature list, training data date range, and run date.
- Experiment naming convention: `{model_name}_{grain}` (e.g., `demand_forecast_hourly`).
- Register a model version in the MLflow Model Registry only after it beats the current Production baseline on the holdout set.
- MLflow tracking URI inside Docker network: `http://mlflow:5000`.

### ML Airflow DAGs
- ML DAGs orchestrate only — business logic lives in `ml/`, not in the DAG file.
- Every ML training script must accept `--run-date` as a CLI argument for reproducible backfills.
- Predictions must be written back to Snowflake `ML` schema before the DAG marks success.

### Snowflake ML Schema
- All ML outputs go to `NYC_TLC_DB.ML` schema.
- Prediction tables use `fct_` prefix (e.g., `fct_demand_forecast`).
- Anomaly flag tables use `fct_anomalies`.
- Causal inference results use `fct_congestion_pricing_impact`.

### Model Evaluation
- Demand forecasting baseline: predict last week's same-hour value (naive lag-168 baseline). Model must beat this on MAPE.
- Anomaly detection: flag days where z-score > 3 on rolling 30-day window.

## 5. Interaction Instructions
- When generating code, always refer to `MODULAR_MONOLITH_STRUCTURE.md` for file placement.
- Before suggesting a Snowflake query, check if it requires a specific warehouse or role setup.
- Before writing any ML training code, check `ML_FEATURE_CONTRACTS.md` for the canonical feature list and leakage boundary.
- Before writing any MLflow logging code, check `ML_EXPERIMENT_STANDARDS.md` for required params and metrics.
