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

## Phase 8 (ML): Congestion Pricing Impact Analysis
- [ ] Define treatment (Manhattan CBD zones) and control (outer borough zones) groups.
- [ ] Build incremental DiD model: growing post-treatment window (Jan 2025 – present); re-runs monthly as new data lands, stabilising the effect estimate over time.
- [ ] Quantify revenue and trip count impact per zone; write aggregate results to `ML.fct_congestion_pricing_impact` (overwrite on each run — idempotent).
- [ ] Visualize treatment effect in Superset (aggregate effect over time).
- [ ] **Airflow DAG `congestion_pricing_analysis`**: triggered as a downstream dependency of `ingest_nyc_taxi_raw` (after `dbt_transform` completes, in parallel with `trigger_retrain_demand_forecast`); `schedule=None`, `reset_dag_run=True`.
- [ ] Write ADR-008: DiD approach for congestion pricing causal inference.
- [ ] *(Future)* Option 2: month-by-month cohort output — additive extension, no pipeline rework needed.

## Phase 9 (ML): Model Monitoring & Drift Detection
- [ ] Compute monthly prediction error metrics (MAE, RMSE, MAPE) against actuals in Gold — comparing `fct_demand_forecast` predictions to `fct_revenue_per_zone_hourly` trip counts for the same period.
- [ ] Detect feature distribution drift: track mean/std of key lag features month-over-month; flag when drift exceeds a threshold (e.g. >2σ shift vs. training window baseline).
- [ ] Write monitoring results to `ML.fct_model_monitoring` (one row per model version per month).
- [ ] Surface model health in Superset: prediction error trend over time, drift flags, model version history.
- [ ] **Airflow DAG `monitor_demand_forecast`**: triggered as a downstream dependency of `retrain_demand_forecast` (runs after predictions are written); `schedule=None`, `reset_dag_run=True`.
- [ ] Automated retraining signal: if MAPE degrades beyond the production baseline threshold, log a warning and open a clear path to trigger retraining.
- [ ] Write ADR-009: model monitoring and drift detection approach.
