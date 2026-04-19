# ADR-006: MLflow as Experiment Tracker and Model Registry

| Field       | Value                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Date**    | 2026-04-19                   |
| **Author**  | Rushikesh Dhumal             |

---

## Context

Phase 6 adds ML models to the pipeline (demand forecasting, anomaly detection,
congestion pricing DiD). Three infrastructure needs arise:

1. **Experiment tracking** — each training run must log hyperparameters, eval
   metrics, feature lists, and training date ranges for reproducibility and
   comparison across runs.
2. **Model registry** — the Airflow retrain DAG must load a specific, versioned
   model for predictions; ad-hoc local pickle files offer no governance.
3. **Artifact storage** — diagnostic plots (feature importances, predictions vs.
   actuals, residuals) must be persisted alongside each run for review.

The solution must run locally in Docker Compose, integrate with Python training
scripts without vendor lock-in, and be self-hosted (no SaaS costs given the
Snowflake Trial budget constraint).

---

## Decision

Use **MLflow 2.x** as the experiment tracker, artifact store, and model
registry for all ML models in this project.

---

## Design

### Server topology

MLflow runs as a dedicated Docker service (`mlflow`) on the `nyc_tlc_backend`
network. Airflow containers reach it at `http://mlflow:5000`; the host
terminal reaches it at `http://localhost:5000`.

- **Backend store**: SQLite at `./mlflow/mlflow.db` (bind-mounted volume).
  Adequate for single-user development; migrate to PostgreSQL for multi-user
  production.
- **Artifact store**: local filesystem at `./mlflow/artifacts`
  (bind-mounted). Artifacts are stored alongside the database in the working
  directory.

### Tracking setup in all training scripts

```python
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
```

This allows scripts to run both inside Docker (`http://mlflow:5000` from env
var) and directly on the host terminal (fallback `http://localhost:5000`).

### Model lifecycle

Model versions progress through three stages: `Staging → Production → Archived`.

The `retrain_demand_forecast` DAG registers new models as `Staging` after each
monthly retraining run. Promotion to `Production` is a deliberate manual step,
gated on `test_mape < current Production` and `mape_vs_baseline > 0`
(`ML_EXPERIMENT_STANDARDS.md §4`).

The `mlflow_cleanup` DAG soft-deletes training runs older than 90 days,
protecting any run that backs a `Production` or `Staging` model version.

---

## Options Considered

| | MLflow (chosen) | Weights & Biases | DVC |
|---|---|---|---|
| **Self-hosted** | Yes (Docker Compose) | No (SaaS) | Yes |
| **Model Registry** | Built-in with stages | Built-in | Git-based, no stage transitions |
| **Python API** | First-class | First-class | CLI-focused |
| **Cost** | Free | Free tier has limits | Free |
| **Airflow integration** | Direct Python import | Direct Python import | CLI subprocess |

W&B was excluded because it requires SaaS. DVC was excluded because its
model registry lacks `Staging → Production` transitions required by the
MLOps governance rules in `ML_EXPERIMENT_STANDARDS.md`.

---

## Consequences

**Positive**
- Full experiment lineage: every training run is reproducible from its logged
  params, metrics, feature list, and serialised model artifact.
- Airflow retrain DAG loads the `Production` model by registry name — no
  file paths in DAG code, no silent stale-model risk.
- MLflow UI at `http://localhost:5000` enables side-by-side run comparison
  without any extra tooling.

**Trade-offs**
- SQLite serialises writes — not suitable for parallel training jobs.
  Acceptable for this single-user project.
- Artifact store is local disk — not replicated. Acceptable for development;
  a cloud artifact store (Azure Blob, S3) would be the production upgrade path.

---

## Files Changed

| File | Change |
|------|--------|
| `infra/docker/mlflow.Dockerfile` | New Dockerfile for MLflow tracking server |
| `docker-compose.yml` | Added `mlflow` service, bind-mounted `./mlflow` volume |
| `.env.example` | Added `MLFLOW_TRACKING_URI` |
| `orchestration/requirements.txt` | Added `mlflow==2.16.0` |
| `infra/docker/airflow.Dockerfile` | Added `mlflow==2.16.0` |
| `orchestration/dags/mlflow_cleanup.py` | New monthly run-archival DAG |
| `ml/` | Scaffolded ML module with utils, feature, and model stubs |
| `.github/workflows/ci.yml` | Added MLflow Docker build smoke test |
