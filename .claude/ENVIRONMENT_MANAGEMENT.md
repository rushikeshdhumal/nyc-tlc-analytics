# Environment & Secret Management

## 1. Security Philosophy
- **Zero Credentials in Git**: No passwords, account IDs, or private keys are to be committed to the repository.
- **Environment Parity**: Local development uses a `.env` file; production/GitHub Actions will use Secret Stores.
- **Service Isolation**: Each module (Airflow, dbt) pulls only the specific variables it needs.

## 2. Snowflake Connection Template
The following variables are required to connect our Modular Monolith to the Snowflake Trial account:


| Variable | Description | Example |
| :--- | :--- | :--- |
| `SNOWFLAKE_ACCOUNT` | Account identifier (Org-Account) | `xy12345.us-east-1` |
| `SNOWFLAKE_USER` | Your DE_ROLE user | `DE_ADMIN` |
| `SNOWFLAKE_PASSWORD` | Secure password | `*********` |
| `SNOWFLAKE_ROLE` | The active role for the pipeline | `DE_ROLE` |
| `SNOWFLAKE_WAREHOUSE` | Compute resource | `COMPUTE_WH` |
| `SNOWFLAKE_DATABASE` | Project database | `NYC_TLC_DB` |

## 3. Configuration Files (The Templates)

### dbt (`profiles.yml`)
Located in `transform/`, this file will use env_var lookups:
```yaml
nyc_tlc_project:
  outputs:
    dev:
      type: snowflake
      account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
      user: "{{ env_var('SNOWFLAKE_USER') }}"
      password: "{{ env_var('SNOWFLAKE_PASSWORD') }}"
      role: "{{ env_var('SNOWFLAKE_ROLE') }}"
      database: "{{ env_var('SNOWFLAKE_DATABASE') }}"
      warehouse: "{{ env_var('SNOWFLAKE_WAREHOUSE') }}"
      schema: silver  # Default target
```

### Airflow (`.env`)
Located in the root, managed by Docker Compose:
AIRFLOW_CONN_SNOWFLAKE_DEFAULT='snowflake://USER:PASS@ACCOUNT/WAREHOUSE/DATABASE?role=DE_ROLE'

## 4. Initialization Workflow
- Copy `.env.example` to `.env.`
- Fill in the Snowflake Trial credentials.
- Use `direnv` or `source .env` to load variables into the local shell for dbt testing.
- Verify connectivity using `dbt debug`.