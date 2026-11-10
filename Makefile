.PHONY: install ingest run test eval docker-up smoke

install:
	python -m venv .venv && .venv/bin/pip install -e ".[dev]"

ingest:
	python -m app.rag.ingest

run:
	uvicorn app.main:app --reload --port 8000

test:
	pytest -q

eval:
	pytest -q tests/evals

docker-up:
	docker compose up --build

smoke:
	./scripts/smoke.sh
