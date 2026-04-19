# Modular Monolith Architecture

## 1. Repository Directory Structure
To maintain loose coupling between services, the repository must follow this structure:

root/
├── .claude/               # AI Instructions & Project Context
├── .github/               # CI/CD Workflows (GitHub Actions)
├── orchestration/         # AIRFLOW SERVICE
│   ├── dags/              # Python DAG definitions
│   ├── plugins/           # Custom Airflow operators/sensors
│   └── include/           # Helper scripts and SQL templates
├── transform/             # DBT SERVICE
│   ├── models/            # Bronze, Silver, Gold SQL models
│   ├── tests/             # Custom data quality tests
│   ├── macros/            # Reusable SQL snippets
│   └── dbt_project.yml    # dbt configuration
├── infra/                 # INFRASTRUCTURE AS CODE
│   ├── docker/            # Service-specific Dockerfiles
│   ├── terraform/         # (Optional) Cloud infra scripts
│   └── scripts/           # Shell scripts for environment setup
├── viz/                   # VISUALIZATION ASSETS
│   └── superset/          # Superset dashboards/exports
└── .env.example           # Centralized environment variable template

## 2. Module Communication Rules
- Decoupling: The transform/ (dbt) directory must be runnable independently of Airflow.
- The Bridge: Use Astronomer Cosmos to dynamically parse the dbt project into Airflow tasks. Airflow should "know" about dbt, but dbt should not "know" about Airflow.
- Data Handoff: All data communication happens via Snowflake. No service should write local files for another service to read.

## 3. Containerization Strategy
- Docker Compose: A single docker-compose.yml in the root will manage all services.
- Shared Network: All containers will run on a backend network to allow local Superset to talk to local Airflow (if needed) and both to talk to Snowflake.
- Volume Mounting: Use bind mounts for orchestration/dags and transform/models during development to allow for "hot reloading" of code changes.

## 4. Coding Standards per Module
- Orchestration: Use the Airflow TaskFlow API (@dag, @task) for cleaner Python code.
- Transformation: Follow the dbt Style Guide. Every model must have a corresponding .yml entry with at least one unique and not_null test.
- Infrastructure: Use a .env file for all credentials. NEVER hardcode Snowflake passwords or AWS keys in any module.