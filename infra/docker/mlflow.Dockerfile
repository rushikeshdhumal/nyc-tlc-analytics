# =============================================================================
# NYC TLC Pipeline — MLflow Tracking Server
# Serves the MLflow UI and REST API on port 5000.
#
# Backend store : PostgreSQL (shared postgres container, mlflow database)
#                 URI passed via MLFLOW_BACKEND_STORE_URI env var at runtime
# Artifact store: /mlflow/artifacts (bind-mounted from ./mlflow/artifacts/)
#
# Tracking URI inside Docker network : http://mlflow:5000
# Tracking URI from host terminal    : http://localhost:5000
# =============================================================================
FROM python:3.12-slim

RUN pip install --no-cache-dir mlflow==2.16.0 psycopg2-binary==2.9.9

EXPOSE 5000

# Shell form so $MLFLOW_BACKEND_STORE_URI is expanded at container start
CMD mlflow server \
    --host 0.0.0.0 \
    --port 5000 \
    --backend-store-uri "$MLFLOW_BACKEND_STORE_URI" \
    --default-artifact-root /mlflow/artifacts
