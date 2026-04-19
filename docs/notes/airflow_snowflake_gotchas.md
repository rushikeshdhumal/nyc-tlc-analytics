# Airflow + Snowflake Engineering Gotchas

Subtle bugs and non-obvious behaviours encountered during pipeline development.
Captured here so future maintainers don't repeat the same debugging cycles.

---

## 1. SnowflakeHook 5.x — account must be in JSON `extra`, not URI host

### Symptom
Tasks using `SnowflakeHook` fail with:

```
snowflake.connector.errors.DatabaseError: Account must be specified
```

Even when `AIRFLOW_CONN_SNOWFLAKE_DEFAULT` is set and looks correct.

### Root cause
`apache-airflow-providers-snowflake` 5.x changed where `SnowflakeHook` reads
the account identifier. It now reads from `connection.extra_dejson["account"]`.
The classic URI format (`snowflake://user:pass@account/db`) puts the account in
`connection.host`, which the hook no longer reads.

### Fix
Set the connection as a JSON string so `account` lands in `extra_dejson`:

```yaml
# docker-compose.yml — x-airflow-common environment
AIRFLOW_CONN_SNOWFLAKE_DEFAULT: >-
  {"conn_type":"snowflake","login":"${SNOWFLAKE_USER}","password":"${SNOWFLAKE_PASSWORD}",
   "extra":{"account":"${SNOWFLAKE_ACCOUNT}","database":"NYC_TLC_DB",
            "warehouse":"COMPUTE_WH","role":"DE_ROLE"}}
```

**Never use the URI format with provider version ≥ 5.x.**

---

## 2. Snowflake COPY INTO result tuple — index 4 is `error_limit`, not `errors_seen`

### Symptom
`validate_bronze_load` raises:

```
ValueError: [YYYY-MM] COPY INTO reported 1 error rows.
```

But `COPY_HISTORY` in Snowflake shows the file loaded cleanly with zero errors.

### Root cause
When `COPY INTO` uses a `FROM (SELECT ...)` transformation, Snowflake returns
one result row per file with this column layout:

| Index | Column | Notes |
|-------|--------|-------|
| 0 | `file` | Stage path |
| 1 | `status` | `LOADED`, `COPY_ALREADY_LOADED`, etc. |
| 2 | `rows_parsed` | |
| 3 | `rows_loaded` | |
| 4 | `error_limit` | **Always `1` when `ON_ERROR = 'ABORT_STATEMENT'`** |
| 5 | `errors_seen` | Actual error count — use this |
| 6 | `first_error` | |
| 7 | `first_error_line` | |
| 8 | `first_error_character` | |
| 9 | `first_error_column_name` | |

Reading index 4 as the error count reports `1` error for every successfully
loaded file because `error_limit` is always `1` with `ON_ERROR = 'ABORT_STATEMENT'`.

### Fix
Read `errors_seen` at index 5:

```python
errors = int(result_row[5] or 0) if len(result_row) > 5 else 0
```

This bug only manifests on the **first genuine COPY INTO load** for a file.
Re-runs of the same file return `COPY_ALREADY_LOADED` status, which bypasses
the error counting path entirely — masking the bug until new data arrives.

---

## 3. Snowflake COPY_HISTORY — correct column and argument names

Common mistakes when querying `INFORMATION_SCHEMA.COPY_HISTORY`:

| Wrong | Correct |
|-------|---------|
| `ROWS_LOADED` | `ROW_COUNT` |
| `TABLE_SCHEMA_NAME => 'BRONZE'` (separate arg) | Include schema in `TABLE_NAME => 'BRONZE.BRZ_YELLOW_TRIPDATA'` |
| `FIRST_ERROR_LINE` | `FIRST_ERROR_LINE_NUMBER` |

Working query template:

```sql
SELECT
    file_name,
    status,
    row_count,
    row_parsed,
    first_error_message,
    first_error_line_number,
    first_error_column_name
FROM TABLE(NYC_TLC_DB.INFORMATION_SCHEMA.COPY_HISTORY(
    TABLE_NAME => 'BRONZE.BRZ_YELLOW_TRIPDATA',
    START_TIME => DATEADD('hours', -2, CURRENT_TIMESTAMP())
))
ORDER BY last_load_time DESC;
```

---

## 4. CI DAG parsing with Cosmos — four requirements that must all be met

### Symptom
GitHub Actions DAG parse job fails with one of:

```
cosmos.exceptions.CosmosValueError: Could not find dbt_project.yml at /opt/airflow/transform/dbt_project.yml
```
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: variable
```
```
dbt.exceptions.DbtProfileError: missing env var SNOWFLAKE_ACCOUNT
```
```
ImportError: cannot import name 'context_to_airflow_vars'
```

### Root cause
Cosmos's `DbtTaskGroup` does real work at DAG load time — it validates the dbt
project path, writes a cache key to the Airflow metadata DB, and runs `dbt ls`
to discover models. Each failure above maps to a missing prerequisite.

### Fix — all four must be present in CI

**1. Install Airflow with the official constraints file**

Without it, pip freely resolves 200+ transitive dependencies and silently picks
incompatible versions (e.g. a newer Airflow that removed `context_to_airflow_vars`):

```bash
pip install "apache-airflow==2.9.3" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.9.3/constraints-3.12.txt"
```

**2. Initialise the Airflow metadata DB before parsing DAGs**

Cosmos writes its graph cache key to the `variable` table. The table does not
exist until the DB is initialised:

```bash
airflow db init
```

**3. Set `DBT_PROJECT_DIR` to the actual project path**

The DAG hardcodes `/opt/airflow/transform` (the Docker path). In CI the project
is at `$GITHUB_WORKSPACE/transform`. Use an env var with a Docker fallback:

```python
# ingest_nyc_taxi_raw.py
_DBT_PROJECT = Path(os.getenv("DBT_PROJECT_DIR", "/opt/airflow/transform"))
```

```yaml
# ci.yml
DBT_PROJECT_DIR: ${{ github.workspace }}/transform
```

**4. Set `SNOWFLAKE_*` env vars (dummy values are fine)**

Cosmos runs `dbt ls` at DAG load time to discover models. `profiles.yml` calls
`env_var('SNOWFLAKE_ACCOUNT')` etc. — if these are missing, `dbt ls` raises a
profile error even though no real Snowflake connection is made:

```yaml
SNOWFLAKE_ACCOUNT: dummy
SNOWFLAKE_USER: dummy
SNOWFLAKE_PASSWORD: dummy
SNOWFLAKE_ROLE: DE_ROLE
SNOWFLAKE_WAREHOUSE: COMPUTE_WH
SNOWFLAKE_DATABASE: NYC_TLC_DB
```
