# =============================================================================
# NYC TLC Pipeline — Airflow Service Image
# Base: Apache Airflow 2.9.3 (Python 3.12)
#
# Extends the official image with:
#   - apache-airflow-providers-snowflake
#   - dbt-core + dbt-snowflake  (transformation layer)
#   - astronomer-cosmos          (Airflow <> dbt bridge, Phase 4)
#   - protobuf 4.x               (required by dbt-core 1.8.x)
#   - azure-storage-blob         (download_to_azure DAG task)
#   - requests                   (TLC CDN download)
#
# Dependencies are installed in two steps to avoid pip ResolutionTooDeep:
#   1. Main packages (snowflake provider, dbt, cosmos, azure)
#   2. protobuf pinned last to guarantee 4.x wins over the base image's 3.x
# =============================================================================
FROM apache/airflow:2.9.3

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

COPY orchestration/requirements.txt /tmp/airflow-requirements.txt

# Install all pinned dependencies except protobuf
RUN pip install --no-cache-dir \
    apache-airflow-providers-snowflake==5.6.0 \
    dbt-core==1.8.7 \
    dbt-snowflake==1.8.4 \
    astronomer-cosmos==1.8.0 \
    azure-storage-blob==12.22.0 \
    requests==2.32.3 \
    mlflow==2.16.0

# Pin protobuf last — must win over the base image's 3.x
RUN pip install --no-cache-dir "protobuf==4.25.3"
