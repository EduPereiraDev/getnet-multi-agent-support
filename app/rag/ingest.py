"""RAG ingestion entry point: `python -m app.rag.ingest`.

Pipeline (T-08): load data/sources.yaml + data/seed/*.md → fetch & clean HTML (if INGEST_ONLINE=1)
→ chunk (~800 chars, 150 overlap) → TF-IDF index persisted to data/index/.
"""

import sys


def main() -> int:
    # TODO(T-08): implement ingestion; the build step tolerates a no-op for now.
    print("ingest: not implemented yet (T-08)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
