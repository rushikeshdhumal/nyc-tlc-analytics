# NYC TLC Analytics Pipeline: Project Plan

---

## Phase 1 (BI): Environment & Snowflake Foundation ✅
- [x] Initialize local development with Docker (Airflow & Apache Superset).
- [x] Set up Snowflake account and RBAC (Roles: DE_ROLE, ANALYST_ROLE).
- [x] Create Snowflake External Stage pointing to Azure Blob Storage (SAS token).
- [x] Verify connection by querying metadata from the External Stage.

## Phase 2 (BI): Ingestion & Bronze Layer ✅
- [x] Create Airflow DAG `ingest_nyc_taxi_raw` using TaskFlow API.
- [x] Automate monthly Parquet download from TLC CDN → Azure Blob inside the DAG.
- [x] Implement `COPY INTO` logic for Yellow Taxi Parquet files (VARIANT, schema-on-read).
- [x] Validate Bronze load — row count reconciliation, error row check, idempotent replay.

## Phase 3 (BI): Transformation & Medallion Architecture ✅
- [x] Initialize dbt project within the repository.
- [x] **Silver Layer**: `stg_yellow_tripdata` — typed, deduplicated, data quality filters applied.
- [x] **Gold Layer**: `fct_revenue_per_zone_hourly` and `fct_revenue_daily`.
- [x] Implement `dbt test` for unique keys, not_null, and relationship integrity.
- [x] Convert Silver and Gold models to incremental materialization.

## Phase 4 (BI): Orchestration & Quality ✅
- [x] Integrate dbt into Airflow using Astronomer Cosmos (DbtTaskGroup).
- [x] Silver tests run before Gold builds — bad Silver data never reaches Gold.
- [x] 6-month rolling window in `download_to_azure` catches TLC publish delays automatically.
- [x] GitHub Actions CI: lint, DAG parse, dbt parse, Docker build, optional Snowflake integration.

## Phase 5 (BI): Visualization & Serving ✅
- [x] Connect Apache Superset to Snowflake Gold tables.
- [x] Build interactive dashboard: "NYC TLC Yellow Taxi Analytics" (KPI scorecards, revenue trends, borough/vendor splits, demand heatmap, tip % by borough).
- [x] README with architecture diagram, Mermaid DAG, ADR links, ML roadmap.

---

## Phase 6 (ML): MLOps Infrastructure ✅
- [x] Scaffold `ml/` folder structure and add to `MODULAR_MONOLITH_STRUCTURE.md`.
- [x] Add MLflow tracking server to Docker Compose (with persistent artifact store volume).
- [x] Add `MLFLOW_TRACKING_URI` to `.env.example`.
- [x] Define MLflow experiment naming convention and required logged params/metrics (see `ML_EXPERIMENT_STANDARDS.md`).
- [x] **Airflow DAG `mlflow_cleanup`**: monthly job to archive stale MLflow runs older than 90 days, keeping Model Registry clean.
- [x] Add MLflow service to CI smoke test.
- [x] Write ADR-006: MLflow as experiment tracker and model registry.

## Phase 7 (ML): Demand Forecasting
- [x] Load 2024 historical data (Jan–Dec 2024) into Bronze and run `dbt build --full-refresh`. Bronze now has ~94M rows covering Jan 2024 – present.
- [x] Build feature extraction script: pull from `fct_revenue_per_zone_hourly`, engineer lag and calendar features.
- [x] Train LightGBM model: hourly trip count per zone, early stopping on rolling validation window (splits derived from `run_date` via `_compute_splits()`).
- [x] Log experiment to MLflow: params, metrics (MAE, RMSE, MAPE), feature importances.
- [x] Register best model in MLflow Model Registry.
- [x] Write predictions back to Snowflake (`ML` schema, `fct_demand_forecast` table).
- [x] **Airflow DAG `retrain_demand_forecast`**: monthly retraining triggered as a downstream dependency of `ingest_nyc_taxi_raw` (after `dbt_transform` task group completes); loads latest features from Snowflake, retrains model, logs to MLflow, writes predictions back to Snowflake.
  - **First-run note**: `write_predictions` will fail until a model version is assigned alias `production` in the MLflow UI (`http://localhost:5000`). This is expected — train once (alias `staging`), review `mape_vs_baseline > 0`, then promote by moving alias `production`.
- [x] **CI**: extend lint + syntax check to `ml/`; add `ml-checks` job with module import smoke test (postponed forecasters skipped).
  - **Note**: when you resume XGB/LSTM/TabNet, the only CI changes needed are removing those three entries from `POSTPONED` in the smoke test and adding `pytorch-tabnet` back to `requirements-ci.txt`.
- [x] Write ADR-005: LightGBM over TFT for demand forecasting.

## Phase 8 (ML): Congestion Pricing Impact Analysis ✅
- [x] Define treatment (Manhattan CBD Yellow Zone) and control (Brooklyn, Queens, Bronx) groups.
- [x] Build incremental DiD model (`congestion_pricing_did.py`): TWFE OLS with zone + day-of-week fixed effects; growing post-treatment window stabilises β₃ estimate monthly.
- [x] Quantify revenue and trip count impact per zone; write per-zone per-period summary rows to `ML.fct_congestion_pricing_impact`; idempotent (delete-then-insert on `_run_date`).
- [x] **Airflow DAG `congestion_pricing_analysis`**: triggered in parallel with `retrain_demand_forecast` after `dbt_transform`; `schedule=None`, `reset_dag_run=True`. Verified end-to-end.
- [x] Write ADR-007: DiD approach for congestion pricing causal inference.
- [x] Superset view SQL (`infra/scripts/congestion_pricing_views.sql`) and chart spec notes ready — dashboard build deferred as a future extension.
- [x] `DAGS_ARE_PAUSED_AT_CREATION=false` added to docker-compose to prevent silent queuing of newly discovered DAGs.
- [ ] *(Future)* Build Superset congestion pricing dashboard from `viz/superset/congestion_pricing_impact__v1.0.0__2026-04-23.notes.md`.

## Phase 9 (ML): Model Monitoring & Drift Detection ✅
- [x] Compute monthly prediction error metrics (MAE, RMSE, MAPE) against actuals in Gold — comparing `fct_demand_forecast` predictions to `fct_revenue_per_zone_hourly` trip counts for the same period.
- [x] Detect feature distribution drift: track mean/std of key lag features month-over-month; flag when drift exceeds 2σ vs. training window baseline stored as `feature_baseline.json` MLflow artifact (zero extra Snowflake credits).
- [x] Write monitoring results to `ML.fct_model_monitoring` (one row per run_date; idempotent delete-then-insert).
- [x] **Airflow DAG `monitor_demand_forecast`**: triggered as a downstream dependency of `retrain_demand_forecast` (after `write_predictions`); `schedule=None`, `reset_dag_run=True`. Verified end-to-end.
- [x] MAPE degradation signal: `mape_degraded = True` if current MAPE > training test_mape × 1.2 OR current MAPE > naive lag-168 baseline MAPE. Emits Airflow WARNING log; no auto-retrain (cost guard on Snowflake Trial).
- [x] `train.py` extended to log `feature_baseline.json` artifact on every retrain run.
- [x] Write ADR-009: model monitoring and drift detection approach.
- [ ] *(Future)* Build Superset monitoring dashboard: prediction error trend, drift flags, model version history.
