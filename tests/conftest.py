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


class _BlockedAnthropic:
    """Stands in for the real SDK client: tests that switch to LLM mode must inject fakes."""

    def __init__(self, *args, **kwargs):
        pass

    @property
    def messages(self):
        raise RuntimeError("real Anthropic API calls are blocked in tests")


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    import app.llm.client as llm_client

    monkeypatch.setattr(llm_client.anthropic, "Anthropic", _BlockedAnthropic)
    llm_client.get_llm.cache_clear()
    yield
    llm_client.get_llm.cache_clear()
