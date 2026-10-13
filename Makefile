.PHONY: instalar test lint cubo-local cubo-init cubo-borrar

instalar:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

cubo-local:
	docker compose -f infra/docker-compose.yml up -d

cubo-init:
	uv sync --extra cubo
	ODC_CONFIG_PATH=infra/datacube.conf uv run datacube system init
	ODC_CONFIG_PATH=infra/datacube.conf uv run datacube product add config/productos/ard_s1s2_mensual.yaml

cubo-borrar:
	docker compose -f infra/docker-compose.yml down -v
