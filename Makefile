.PHONY: install ingest ingest-online run test eval docker-up smoke

BIN := .venv/bin

install:
	python3 -m venv .venv && $(BIN)/pip install -e ".[dev]"

ingest:
	$(BIN)/python -m app.rag.ingest

ingest-online:
	INGEST_ONLINE=1 $(BIN)/python -m app.rag.ingest

run:
	$(BIN)/uvicorn app.main:app --reload --port 8000

test:
	$(BIN)/pytest -q

eval:
	$(BIN)/pytest -q tests/evals

docker-up:
	docker compose up --build

smoke:
	./scripts/smoke.sh
