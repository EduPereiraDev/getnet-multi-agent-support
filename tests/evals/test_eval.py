"""Release gate: the golden dataset must meet the thresholds in specs/04 (offline mode, no network)."""

import pytest

from app.evaluation import gate_violations, run_eval
from app.tools import web_tools


def _fake_weather(city: str, day_offset: int = 1) -> dict:
    return {"ok": True, "city": city, "country": "Brazil", "date": "2026-11-11", "temp_max_c": 27.0,
            "temp_min_c": 18.0, "precipitation_probability_pct": 40, "condition": "partly cloudy",
            "source": "https://open-meteo.com"}


def _fake_fx(base: str, quote: str = "BRL") -> dict:
    return {"ok": True, "base": base.upper(), "quote": quote.upper(), "rate": 6.21, "date": "2026-11-10",
            "source": "https://frankfurter.dev"}


def _fake_search(query: str, max_results: int = 5) -> dict:
    return {"ok": True, "results": [{"title": "Result", "url": "https://example.com", "snippet": query}]}


@pytest.fixture(scope="module")
def report():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(web_tools, "get_weather", _fake_weather)
        mp.setattr(web_tools, "get_exchange_rate", _fake_fx)
        mp.setattr(web_tools, "web_search", _fake_search)
        yield run_eval()


def test_eval_gates(report):
    assert not gate_violations(report), f"metrics={report['metrics']} failures={report['failures']}"


def test_safety_cases_never_fail(report):
    safety_failures = {cid: checks for cid, checks in report["failures"].items() if "safety" in checks}
    assert not safety_failures
