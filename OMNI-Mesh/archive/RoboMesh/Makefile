# =============================================================================
# RoboMesh — one-line helpers for every phase of the demo
# Run `make` (no args) to see the help text.
# =============================================================================

PY      ?= python3
VENV    ?= .venv
ACTIVATE = . $(VENV)/bin/activate

.DEFAULT_GOAL := help

.PHONY: help venv install install-ml generate ingest medallion vla shards \
        governance semantic orchestrate closed-loop train-sample \
        dbt-run dbt-test dbt-ci demo dagster ui test clean nuke

help: ## Show this help.
	@echo "RoboMesh — available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create a local Python virtual environment.
	$(PY) -m venv $(VENV)
	@echo "venv created — activate with: source $(VENV)/bin/activate"

install: ## Install all (core) Python dependencies into the active environment.
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install -e .

install-ml: ## Install optional ML extras (PyTorch + torchvision + Ray + WebDataset).
	$(PY) -m pip install -r requirements-ml.txt

generate: ## Phase 0 — synthesize raw multimodal robotics data into Bronze drops.
	$(PY) -m robomesh.cli generate

ingest: ## Phase 1 — register raw drops into the Apache Iceberg catalog (Bronze).
	$(PY) -m robomesh.cli ingest

medallion: ## Phase 2 — run Silver (time-sync) + Gold (VLA tokenization) transforms.
	$(PY) -m robomesh.cli medallion

vla: ## Phase 2.5 — PyTorch CV embeddings → silver.frame_embeddings + gold v2.
	$(PY) -m robomesh.cli vla

shards: ## Phase 2.5 — pre-shuffled WebDataset shards for VLA training.
	$(PY) -m robomesh.cli shards

train-sample: ## Inspect a few samples through the Ray/PyTorch training interface.
	$(PY) -m robomesh.cli train-sample

governance: ## Phase 3 — enforce dbt-style contracts and SHA-256 masking.
	$(PY) -m robomesh.cli governance

semantic: ## Phase 4 — generate summaries + embeddings, populate ChromaDB index.
	$(PY) -m robomesh.cli semantic

orchestrate: ## Phase 5 — Dagster materialization + FinOps audit report.
	$(PY) -m robomesh.cli orchestrate

closed-loop: ## Phase 6 — stream live VLA inference events back into Bronze.
	$(PY) -m robomesh.cli closed-loop

dbt-run: ## Run the dbt project (Silver + Gold contracts via DuckDB).
	cd dbt_project && dbt run --profiles-dir .

dbt-test: ## Run dbt data tests.
	cd dbt_project && dbt test --profiles-dir .

dbt-ci: ## CI-grade dbt build: --warn-error promotes any warning (incl. contract drift) to a failure.
	cd dbt_project && dbt build --profiles-dir . --warn-error --no-version-check

demo: generate ingest medallion vla shards governance semantic orchestrate closed-loop ## End-to-end pipeline (incl. VLA + closed loop).
	@echo "\n✔ RoboMesh demo complete — run 'make ui' to open the agentic explorer."

dagster: ## Launch the Dagster webserver on http://localhost:3000.
	DAGSTER_HOME=$(PWD)/dagster_home dagster dev -m robomesh.orchestration.definitions

ui: ## Launch the Streamlit Agentic RAG explorer on http://localhost:8501.
	streamlit run app/streamlit_app.py

test: ## Run unit tests.
	pytest

clean: ## Remove transient build artifacts.
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +

nuke: clean ## Also remove generated data / catalog / vector index.
	rm -rf data/ dagster_home/ chroma_db/ dbt_project/target dbt_project/logs
