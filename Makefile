LOCAL_ENV ?= .env.local
MANAGED_ENV ?= .env.cloud
LOCAL_PROJECT ?= rfid-hospital-local

COMPOSE_LOCAL = docker compose --env-file $(LOCAL_ENV) --profile local
COMPOSE_MANAGED = docker compose --env-file $(MANAGED_ENV) --profile managed

.PHONY: local-up managed-up stop-local stop-managed status-local status-managed \
	logs-local logs-managed migrate-local migrate-managed migration-current-local \
	migration-current-managed simulator-local tests smoke reset-local

local-up:
	$(COMPOSE_LOCAL) up -d --build --wait

managed-up:
	$(COMPOSE_MANAGED) up -d --build --wait

stop-local:
	$(COMPOSE_LOCAL) down --remove-orphans

stop-managed:
	$(COMPOSE_MANAGED) down --remove-orphans

status-local:
	$(COMPOSE_LOCAL) ps -a

status-managed:
	$(COMPOSE_MANAGED) ps -a

logs-local:
	$(COMPOSE_LOCAL) logs --follow --tail=100

logs-managed:
	$(COMPOSE_MANAGED) logs --follow --tail=100

migrate-local:
	$(COMPOSE_LOCAL) run --rm migrate-local alembic upgrade head

migrate-managed:
	$(COMPOSE_MANAGED) run --rm migrate-managed alembic upgrade head

migration-current-local:
	$(COMPOSE_LOCAL) run --rm migrate-local alembic current

migration-current-managed:
	$(COMPOSE_MANAGED) run --rm migrate-managed alembic current

simulator-local:
	$(COMPOSE_LOCAL) run --rm --no-deps \
		-e MQTT_CLIENT_ID=easy-local-simulator \
		-e MQTT_TOPIC=easy/dev/hupaa/portal-01/reader-01/readings \
		ingestor-local python -m rfid_ingestion.simulator \
		--reader-id reader-01 --count 3 --interval 1

tests:
	python3 -m pytest -q

smoke:
	bash tests/infrastructure/compose-smoke-test.sh

reset-local:
	COMPOSE_PROJECT_NAME=$(LOCAL_PROJECT) \
		CONFIRM_RESET_LOCAL=$(CONFIRM_RESET_LOCAL) \
		bash scripts/reset-local-dev.sh
