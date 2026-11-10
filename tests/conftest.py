import os

import pytest
import yaml
from pathlib import Path

os.environ.setdefault("LLM_MODE", "offline")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SCENARIOS = yaml.safe_load((Path(__file__).parent / "evals" / "scenarios.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)
