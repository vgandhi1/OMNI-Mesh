.PHONY: help install seed iceberg dbt-telemetry dbt-commercial dbt-clinical dbt-all \
        dbt-ci embeddings rag dagster orchestrate finops test clean

PY ?= python
VENV ?= .venv
BIN := $(VENV)/bin

help:
	@echo "HEAL-Mesh local execution targets:"
	@echo "  make install         - create venv and install dependencies"
	@echo "  make seed            - generate synthetic wearable / Stripe / eCRF data"
	@echo "  make iceberg         - bootstrap Iceberg catalog + bronze tables"
	@echo "  make dbt-all         - run dbt medallion across telemetry/commercial/clinical"
	@echo "  make embeddings      - build vector store from gold metrics"
	@echo "  make rag             - run sample agentic RAG queries"
	@echo "  make orchestrate     - materialize end-to-end Dagster job"
	@echo "  make finops          - print FinOps audit queries against query log"
	@echo "  make dagster         - launch Dagster UI on http://localhost:3000"
	@echo "  make test            - run pytest unit tests"
	@echo "  make clean           - remove generated artifacts"

install:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt

seed:
	$(BIN)/python -m scripts.generate_synthetic_data

iceberg:
	$(BIN)/python -m scripts.bootstrap_iceberg

export HEAL_MESH_PROJECT_ROOT := $(CURDIR)

dbt-telemetry:
	cd domains/telemetry/dbt && $(CURDIR)/$(BIN)/dbt build --profiles-dir . --no-version-check

dbt-commercial:
	cd domains/commercial/dbt && $(CURDIR)/$(BIN)/dbt build --profiles-dir . --no-version-check

dbt-clinical:
	cd domains/clinical/dbt && $(CURDIR)/$(BIN)/dbt build --profiles-dir . --no-version-check

dbt-all: dbt-telemetry dbt-commercial dbt-clinical

# CI-grade dbt build: --warn-error promotes deprecation warnings, contract
# violations, and orphaned tests into hard failures. Use this target from
# CI/PR pipelines so a contract drift never lands on main.
dbt-ci:
	cd domains/telemetry/dbt && $(CURDIR)/$(BIN)/dbt build --profiles-dir . --warn-error --no-version-check
	cd domains/commercial/dbt && $(CURDIR)/$(BIN)/dbt build --profiles-dir . --warn-error --no-version-check
	cd domains/clinical/dbt && $(CURDIR)/$(BIN)/dbt build --profiles-dir . --warn-error --no-version-check

embeddings:
	$(BIN)/python -m ai_readiness.embeddings.vector_pipeline

rag:
	$(BIN)/python -m ai_readiness.rag.agentic_rag

orchestrate:
	$(BIN)/python -m scripts.run_end_to_end

orchestrate-dagster:
	DAGSTER_HOME=$(CURDIR)/.dagster HOME=$(CURDIR)/.dagster \
	  $(BIN)/dagster job execute -m orchestration.dagster.definitions -j heal_mesh_end_to_end

dagster:
	$(BIN)/dagster dev -m orchestration.dagster.definitions

finops:
	$(BIN)/python -m finops.run_audit

test:
	$(BIN)/pytest -q

clean:
	rm -rf data/lakehouse data/warehouse data/vector
	find . -name target -type d -prune -exec rm -rf {} + || true
	find . -name dbt_packages -type d -prune -exec rm -rf {} + || true
	find . -name logs -type d -prune -exec rm -rf {} + || true
