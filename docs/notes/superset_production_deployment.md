# Superset Production Deployment — Future Work

This note captures what needs to change when Superset is moved from local Docker
to an online deployment accessible by multiple end users.

---

## Current state (local)

`viz/superset/superset_config.py` uses `FileSystemCache` with a 24h TTL.
This works for single-user local development: chart queries are cached to the
container's disk and Snowflake is only queried once per day per chart.

**Limitation:** FileSystemCache is tied to a single container's disk. If
multiple Superset workers run (or the container restarts and cache is lost),
every user triggers a fresh Snowflake query.

---

## What needs to change for online deployment

### 1. Swap FileSystemCache → Redis

Replace the cache backend in `viz/superset/superset_config.py`:

```python
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_REDIS_URL": "redis://redis:6379/0",
    "CACHE_DEFAULT_TIMEOUT": 86400,
}
DATA_CACHE_CONFIG = CACHE_CONFIG
```

All Superset instances share the same Redis cache — user A's query populates
it, user B gets the cached result instantly at zero Snowflake compute cost.

**Managed Redis options:**
- AWS: ElastiCache (Redis)
- Azure: Azure Cache for Redis
- GCP: Memorystore
- Self-hosted: add a `redis:7-alpine` service to docker-compose

### 2. Add Celery workers for async query execution

In production Superset, Celery workers execute Snowflake queries in the
background and write results to Redis. Users see a loading state instead of a
frozen browser; the result is cached for all subsequent users.

Production architecture:
```
User → Superset web → Celery worker → Snowflake
                             ↓
                          Redis cache ← all subsequent users hit this
```

Required additions:
- `celery` worker service in docker-compose / Kubernetes
- `CELERY_CONFIG` in `superset_config.py` pointing at Redis as the broker
- `RESULTS_BACKEND` in `superset_config.py` for storing async query results

### 3. Replace local Postgres with a managed metadata DB

The current `postgres:15-alpine` container stores Airflow metadata only.
Superset also needs a persistent metadata DB for dashboards, charts, and users.
For production, use a managed Postgres instance (RDS, Azure DB, Cloud SQL)
so dashboard definitions survive infrastructure changes.

---

## Lowest-friction option — Preset.io

[Preset.io](https://preset.io) is Apache Superset as a managed service, built
by the original Superset creators. It handles Redis, Celery, scaling, auth,
and SSO out of the box. Connect it directly to the Snowflake Gold layer
(`NYC_TLC_DB.GOLD`) and share dashboard links with stakeholders immediately.

Best choice when: the goal is sharing dashboards with non-technical users
without managing infrastructure.

---

## Files to update when implementing

| File | Change |
|---|---|
| `viz/superset/superset_config.py` | Swap `FileSystemCache` → `RedisCache`; add `CELERY_CONFIG` and `RESULTS_BACKEND` |
| `docker-compose.yml` | Add `redis` service; add `superset-worker` Celery service |
| `infra/docker/superset.Dockerfile` | Add `celery` and `redis` pip dependencies if not already present |
