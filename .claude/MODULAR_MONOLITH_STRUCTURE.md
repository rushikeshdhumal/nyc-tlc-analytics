# Modular Monolith Architecture

## 1. Repository Directory Structure
To maintain loose coupling between services, the repository must follow this structure:

root/
├── .claude/               # AI Instructions & Project Context
├── .github/               # CI/CD Workflows (GitHub Actions)
├── orchestration/         # AIRFLOW SERVICE
│   ├── dags/              # Python DAG definitions
│   │   ├── ingest_nyc_taxi_raw.py
│   │   ├── retrain_demand_forecast.py
│   │   ├── detect_anomalies.py
│   │   ├── congestion_pricing_analysis.py
│   │   └── mlflow_cleanup.py
│   ├── plugins/           # Custom Airflow operators/sensors
│   └── include/           # Helper scripts and SQL templates
│       └── sql/           # COPY INTO and DDL templates
├── transform/             # DBT SERVICE
│   ├── models/            # Bronze, Silver, Gold SQL models
│   ├── tests/             # Custom data quality tests
│   ├── macros/            # Reusable SQL snippets
│   └── dbt_project.yml    # dbt configuration
├── ml/                    # ML SERVICE
│   ├── features/          # Feature extraction scripts (read from Snowflake Gold)
│   │   └── demand_features.py
│   ├── models/            # Model training and evaluation scripts
│   │   ├── demand_forecast/
│   │   │   ├── train.py
│   │   │   └── predict.py
│   │   ├── anomaly_detection/
│   │   │   ├── train.py
│   │   │   └── score.py
│   │   └── causal_inference/
│   │       └── congestion_pricing_did.py
│   └── utils/             # Shared ML utilities (Snowflake I/O, MLflow helpers)
│       ├── snowflake_io.py
│       └── mlflow_utils.py
├── infra/                 # INFRASTRUCTURE AS CODE
│   ├── docker/            # Service-specific Dockerfiles
│   │   ├── airflow.Dockerfile
│   │   ├── superset.Dockerfile
│   │   └── mlflow.Dockerfile
│   ├── terraform/         # (Optional) Cloud infra scripts
│   └── scripts/           # Shell scripts for environment setup
├── viz/                   # VISUALIZATION ASSETS
│   └── superset/          # Superset dashboards/exports
└── .env.example           # Centralized environment variable template

## 2. Module Communication Rules
- **Decoupling**: The `transform/` (dbt) directory must be runnable independently of Airflow.
- **The Bridge**: Use Astronomer Cosmos to dynamically parse the dbt project into Airflow tasks. Airflow should "know" about dbt, but dbt should not "know" about Airflow.
- **Data Handoff**: All data communication happens via Snowflake. No service should write local files for another service to read. This applies to ML too — feature extraction reads from Snowflake Gold, predictions write back to Snowflake ML schema.
- **ML Isolation**: Scripts in `ml/` must be runnable independently of Airflow. Airflow DAGs in `orchestration/dags/` call into `ml/` as a library — `ml/` must not import from `orchestration/`.
- **No Cross-Layer Reads**: `ml/features/` reads only from Gold tables (`fct_` prefix). Never read from Silver or Bronze directly in ML scripts.

## 3. Snowflake Schema Ownership

| Schema   | Owner        | Written by                        | Read by                        |
|----------|--------------|-----------------------------------|--------------------------------|
| BRONZE   | Airflow DAG  | `COPY INTO` in `ingest_nyc_taxi_raw` | dbt Silver models only         |
| SILVER   | dbt          | `stg_` models                     | dbt Gold models only           |
| GOLD     | dbt          | `fct_` / `dim_` models            | Superset, `ml/features/`       |
| ML       | ML scripts   | `ml/models/*/predict.py`          | Superset, Airflow validation   |

## 4. Containerization Strategy
- **Docker Compose**: A single `docker-compose.yml` in the root manages all services including MLflow.
- **Shared Network**: All containers run on the `nyc_tlc_backend` bridge network.
- **Volume Mounting**: Use bind mounts for `orchestration/dags`, `transform/models`, and `ml/` during development for hot reloading.
- **MLflow**: Runs as a separate container with a persistent volume for the artifact store. Tracking URI is `http://mlflow:5000` within the Docker network.

## 5. Coding Standards per Module

### Orchestration (Airflow)
- Use the TaskFlow API (`@dag`, `@task`) for all DAGs.
- DAGs orchestrate — they do not contain business logic. ML logic lives in `ml/`, SQL lives in `include/sql/`.
- All ML DAG tasks call functions from `ml/` via direct Python import (execution mode: LOCAL).

### Transformation (dbt)
- Follow the dbt Style Guide. Every model must have a corresponding `.yml` entry with at least one `unique` and `not_null` test.
- CTEs over subqueries. Upper case SQL keywords.

### ML
- Every training script must accept `--run-date` as a CLI argument for reproducible backfills.
- Every training run must log to MLflow: model params, eval metrics, feature list, training data date range.
- Feature extraction scripts must be idempotent — re-running for the same date range produces the same feature matrix.
- Train/validation/test splits must always be time-based (no random shuffling of time-series data).

### Infrastructure
- Use `.env` for all credentials. Never hardcode secrets in any module.
- MLflow artifact store path: `./mlflow/artifacts` (bind-mounted into the MLflow container).
