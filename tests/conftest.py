import os

import pytest
import yaml
from pathlib import Path

os.environ["LLM_MODE"] = "offline"  # never reach the real API from tests, even if exported in the shell
os.environ["INGEST_ONLINE"] = "0"  # tests never crawl, even if .env enables it
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "1000")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SCENARIOS = yaml.safe_load((Path(__file__).parent / "evals" / "scenarios.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)
