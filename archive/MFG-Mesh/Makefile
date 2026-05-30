.PHONY: install demo test dbt-build dagster-dev clean kafka-up kafka-down

PYTHON ?= python3
PIP ?= pip3

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-full:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-full.txt

demo:
	$(PYTHON) scripts/run_demo.py

test:
	$(PYTHON) -m pytest

dbt-build:
	cd dbt_mfg_mesh && dbt build --profiles-dir .

dagster-dev:
	DAGSTER_HOME=$$(pwd)/.mfg_mesh/dagster dagster dev -m mfg_mesh.orchestration.assets

kafka-up:
	docker compose up -d redpanda

kafka-down:
	docker compose down

clean:
	rm -rf .mfg_mesh __pycache__ .pytest_cache build dist *.egg-info
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete
