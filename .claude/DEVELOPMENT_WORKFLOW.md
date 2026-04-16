# Development Workflow & VS Code Guide

## 1. Local Environment Setup
Before starting, ensure **Docker Desktop** is running and your `.env` file is populated with Snowflake credentials.

- **Start all services**: `docker-compose up -d`
- **Check service status**: `docker-compose ps`
- **View logs (e.g., Airflow)**: `docker-compose logs -f airflow-webserver`
- **Stop all services**: `docker-compose down`

## 2. VS Code Recommended Extensions
Install these extensions to turn VS Code into a Data Engineering IDE:
- **dbt Power User**: For model compilation, lineage, and running dbt from the UI.
- **Python (Microsoft)**: Essential for Airflow DAG development and linting.
- **Snowflake (Official)**: To run ad-hoc SQL queries directly against your trial account.
- **Docker**: To manage and exec into your containers without leaving the IDE.
- **YAML**: For error-free editing of `dbt_project.yml` and Airflow configurations.

## 3. Transformation Workflow (dbt)
The `transform/` folder should be treated as its own unit. 

- **Install dependencies**: `dbt deps`
- **Verify connection**: `dbt debug`
- **Run a specific model**: `dbt run --select stg_yellow_taxi`
- **Run all tests**: `dbt test`
- **Generate documentation**: `dbt docs generate && dbt docs serve` (Access via `localhost:8080`)

### Lookup Table Initialization
Before running your models for the first time, load the static lookup data:
- `dbt seed` (This creates the `taxi_zone_lookup` table in your Snowflake `silver` schema).

## 4. Orchestration Workflow (Airflow)
- **Airflow UI**: Access at `http://localhost:8080` (Default: `admin`/`admin`).
- **Sync DAGs**: Since we use volume mounting, changes to `orchestration/dags/` will appear in the UI automatically.
- **Manual Trigger**: Use the "Play" button in the UI or run:
  `docker exec -it airflow-scheduler airflow dags trigger ingest_nyc_taxi`

## 5. Troubleshooting Cheat Sheet
- **dbt "Table not found"**: Ensure you have run `dbt seed` or your Bronze layer ingestion first.
- **Airflow "DAG Import Error"**: Check `docker-compose logs` for Python syntax errors or missing dbt-cosmos dependencies.
- **Snowflake "Unauthorized"**: Ensure your `.env` variables match your Snowflake User/Role exactly.

## 6. Daily Shutdown
To save resources and Snowflake credits:
1. `docker-compose stop` (stops containers but keeps data).
2. Check the Snowflake UI to ensure your **Warehouse** status is `Suspended`.
