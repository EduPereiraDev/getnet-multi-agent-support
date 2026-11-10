FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install ".[dev]"

COPY data ./data
COPY tests ./tests

# Build the RAG index at image build time from the offline seed corpus.
# Set INGEST_ONLINE=1 to also crawl the live Getnet pages listed in data/sources.yaml.
ARG INGEST_ONLINE=0
ENV INGEST_ONLINE=${INGEST_ONLINE}
RUN python -m app.rag.ingest || echo "ingest skipped (index will be built on startup)"

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
