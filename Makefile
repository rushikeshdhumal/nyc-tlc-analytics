# =============================================================================
# NYC TLC BI Pipeline — Developer Convenience Commands
# Requires: make (available via Git for Windows, WSL, or `choco install make`)
# =============================================================================

.PHONY: up down restart logs ps build

up:
	docker-compose up -d
	@echo ""
	@echo "========================================"
	@echo "  NYC TLC BI Pipeline - Stack Ready"
	@echo "========================================"
	@echo "  Airflow  -> http://localhost:8080"
	@echo "  Superset -> http://localhost:8088"
	@echo ""
	@echo "  Credentials: see .env (AIRFLOW_ADMIN_* / SUPERSET_ADMIN_*)"
	@echo "========================================"

down:
	docker-compose down

restart:
	docker-compose down
	docker-compose up -d
	@echo ""
	@echo "========================================"
	@echo "  NYC TLC BI Pipeline - Stack Ready"
	@echo "========================================"
	@echo "  Airflow  -> http://localhost:8080"
	@echo "  Superset -> http://localhost:8088"
	@echo ""
	@echo "  Credentials: see .env (AIRFLOW_ADMIN_* / SUPERSET_ADMIN_*)"
	@echo "========================================"

logs:
	docker-compose logs -f

ps:
	docker-compose ps

build:
	docker-compose build --no-cache
