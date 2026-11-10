FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime dependencies only: tests and dev tools stay out of the image (see .dockerignore).
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

COPY data ./data

# Build the RAG index at image build time: curated seed corpus + live crawl of data/sources.yaml.
# Pages that fail to fetch are skipped, so a build without network still indexes the seed (INGEST_ONLINE=0 forces seed-only).
ARG INGEST_ONLINE=1
ENV INGEST_ONLINE=${INGEST_ONLINE}
RUN python -m app.rag.ingest

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
