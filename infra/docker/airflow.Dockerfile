# =============================================================================
# NYC TLC Pipeline — Airflow Service Image
# Base: Apache Airflow 2.9.3 (Python 3.11)
#
# Extends the official image with:
#   - dbt-snowflake  (transformation layer)
#   - astronomer-cosmos  (Airflow <> dbt bridge, Phase 4)
#   - apache-airflow-providers-snowflake  (SnowflakeOperator / Hook)
# =============================================================================
FROM apache/airflow:2.9.3

# Switch to root only for OS-level dependencies
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Back to the unprivileged airflow user for pip installs
USER airflow

# Copy and install Python dependencies defined in orchestration/requirements.txt
COPY orchestration/requirements.txt /tmp/airflow-requirements.txt
RUN pip install --no-cache-dir -r /tmp/airflow-requirements.txt
