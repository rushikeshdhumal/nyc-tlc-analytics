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

## 4. Interaction Instructions
- When generating code, always refer to `MODULAR_MONOLITH_STRUCTURE.md` for file placement.
- Before suggesting a Snowflake query, check if it requires a specific warehouse or role setup.
