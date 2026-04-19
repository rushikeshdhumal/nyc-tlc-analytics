# =============================================================================
# NYC TLC Pipeline — MLflow Tracking Server
# Serves the MLflow UI and REST API on port 5000.
#
# Backend store : SQLite at /mlflow/mlflow.db  (bind-mounted from ./mlflow/)
# Artifact store: /mlflow/artifacts            (bind-mounted from ./mlflow/)
#
# Tracking URI inside Docker network : http://mlflow:5000
# Tracking URI from host terminal    : http://localhost:5000
# =============================================================================
FROM python:3.12-slim

RUN pip install --no-cache-dir mlflow==2.16.0

EXPOSE 5000

CMD ["mlflow", "server", \
     "--host", "0.0.0.0", \
     "--port", "5000", \
     "--backend-store-uri", "sqlite:////mlflow/mlflow.db", \
     "--default-artifact-root", "/mlflow/artifacts"]
