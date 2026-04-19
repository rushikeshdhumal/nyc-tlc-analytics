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
- [ ] Add forecast vs. actuals chart to Superset dashboard.
- [x] **Airflow DAG `retrain_demand_forecast`**: monthly retraining triggered as a downstream dependency of `ingest_nyc_taxi_raw` (after `dbt_transform` task group completes); loads latest features from Snowflake, retrains model, logs to MLflow, writes predictions back to Snowflake.
  - **First-run note**: `write_predictions` will fail until a Staging model is manually promoted to Production in the MLflow UI (`http://localhost:5000`). This is expected — train once, review `mape_vs_baseline > 0`, promote, then subsequent runs are fully automated.
- [x] Write ADR-005: LightGBM over TFT for demand forecasting.

## Phase 8 (ML): Congestion Pricing Impact Analysis
- [ ] Define treatment (Manhattan CBD zones) and control (outer borough zones) groups.
- [ ] Build difference-in-differences model: pre/post Jan 2025 congestion pricing rollout.
- [ ] Quantify revenue and trip count impact per zone.
- [ ] Visualize treatment effect in Superset.
- [ ] **Airflow DAG `congestion_pricing_analysis`**: one-shot DAG (no schedule, manual trigger only) that runs the DiD analysis script and writes results to Snowflake `ML` schema.
- [ ] Write ADR-008: DiD approach for congestion pricing causal inference.

## Phase 9 (ML): Anomaly Detection
- [ ] Build rolling z-score baseline for daily trip count and revenue per zone.
- [ ] Flag anomalous days (z > 3) and write to Snowflake `fct_anomalies` table.
- [ ] Surface anomaly flags in Superset dashboard.
- [ ] **Airflow DAG `detect_anomalies`**: monthly scoring DAG triggered after `ingest_nyc_taxi_raw` completes; runs anomaly scoring script against the latest Gold data and writes flags to Snowflake.
- [ ] Write ADR-009: anomaly detection approach.
