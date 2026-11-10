"""Knowledge Agent (offline mode): RAG extractive answers + web tools, with web tools stubbed (no network)."""

from typing import Any

import pytest

from app import config
from app.agents.knowledge import KnowledgeAgent, extract_city
from app.schemas import AgentContext, AgentResult
from app.tools import web_tools


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_MODE", "offline")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def web_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple, dict]]:
    """Stub every web tool; record calls. Tests override individual tools as needed."""
    calls: list[tuple[str, tuple, dict]] = []

    def stub(name: str, result: dict[str, Any]):
        def fn(*args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append((name, args, kwargs))
            return result

        return fn

    monkeypatch.setattr(
        web_tools, "get_weather",
        stub("get_weather", {
            "ok": True, "city": "Porto Alegre", "country": "Brazil", "date": "2026-11-11",
            "temp_max_c": 29.1, "temp_min_c": 18.4, "precipitation_probability_pct": 40,
            "condition": "rain showers", "source": "https://open-meteo.com",
        }),
    )
    monkeypatch.setattr(
        web_tools, "get_exchange_rate",
        stub("get_exchange_rate", {
            "ok": True, "base": "EUR", "quote": "BRL", "rate": 6.1234, "date": "2026-11-10",
            "source": "https://frankfurter.dev",
        }),
    )
    monkeypatch.setattr(
        web_tools, "web_search",
        stub("web_search", {
            "ok": True,
            "results": [
                {"title": f"Result {i}", "url": f"https://example.com/{i}", "snippet": f"Snippet {i}"}
                for i in range(1, 5)
            ],
        }),
    )
    return calls


def run(message: str, previous: list[AgentResult] | None = None) -> AgentResult:
    ctx = AgentContext(
        trace_id="t-1", user_id="cliente1988", message=message, masked_message=message, previous=previous or []
    )
    return KnowledgeAgent().run(ctx)


def urls(result: AgentResult) -> list[str]:
    return [s.url for s in result.sources]


def test_s01_compares_both_card_machines(web_calls):
    res = run("What's the difference between the Get Clássica and the Get Smart?")
    assert "Get Clássica" in res.answer and "Get Smart" in res.answer
    assert any("todas-as-maquininhas" in u for u in urls(res))
    assert res.confidence == 0.75
    assert res.tool_calls[0].tool == "search_knowledge_base" and res.tool_calls[0].args["hits"] > 0
    assert not web_calls


def test_s09_crediario_installments(web_calls):
    res = run("How many installments can I split a sale into with the crediário?")
    assert "48" in res.answer
    assert any("crediario" in u for u in urls(res))


def test_s04_pix_bank_account(web_calls):
    res = run("Do I need a bank account to receive my sales via Pix?")
    assert any("/pix/" in u for u in urls(res))
    assert "conta" in res.answer.lower()


def test_s06_antecipacao(web_calls):
    res = run("How does receivables advance (antecipação) work with Getnet?")
    assert any("antecipacao" in u for u in urls(res))


def test_s10_payment_link_whatsapp(web_calls):
    res = run("Can I sell through WhatsApp using the Payment Link?")
    assert any("link-de-pagamento" in u for u in urls(res))
    assert "WhatsApp" in res.answer


def test_answers_cite_their_sources(web_calls):
    res = run("How does receivables advance (antecipação) work with Getnet?")
    for url in urls(res):
        assert url in res.answer


def test_s02_weather_tomorrow(web_calls):
    res = run("What's the weather forecast in Porto Alegre tomorrow?")
    assert web_calls == [("get_weather", ("Porto Alegre",), {"day_offset": 1})]
    assert res.tool_calls[0].tool == "get_weather" and res.tool_calls[0].ok
    assert "Porto Alegre" in res.answer and "18.4" in res.answer and "40%" in res.answer
    assert urls(res) == ["https://open-meteo.com"]


@pytest.mark.parametrize(
    ("message", "city"),
    [
        ("Qual a previsão do tempo em São Paulo amanhã?", "São Paulo"),
        ("Will it rain in Rio de Janeiro today?", "Rio de Janeiro"),
        ("What's the weather like?", None),
    ],
)
def test_extract_city(message, city):
    assert extract_city(message) == city


def test_s07_euro_exchange_rate(web_calls):
    res = run("What's the euro exchange rate today?")
    assert web_calls == [("get_exchange_rate", ("EUR", "BRL"), {})]
    assert "1 EUR = R$ 6.1234" in res.answer
    assert res.tool_calls[0].tool == "get_exchange_rate"
    assert urls(res) == ["https://frankfurter.dev"]


def test_unknown_general_question_uses_web_search(web_calls):
    res = run("Who won the 2022 FIFA World Cup final?")
    assert [c[0] for c in web_calls] == ["web_search"]
    assert [t.tool for t in res.tool_calls] == ["search_knowledge_base", "web_search"]
    assert res.tool_calls[0].args["hits"] == 0
    assert len(res.sources) == 3 and "Result 1" in res.answer


def test_web_search_miss_is_honest(web_calls, monkeypatch):
    monkeypatch.setattr(web_tools, "web_search", lambda *a, **k: {"ok": False, "error": "offline"})
    res = run("Who won the 2022 FIFA World Cup final?")
    assert "couldn't find" in res.answer
    assert res.confidence == 0.3


def test_weather_tool_failure_lowers_confidence(web_calls, monkeypatch):
    monkeypatch.setattr(web_tools, "get_weather", lambda *a, **k: {"ok": False, "error": "timeout"})
    res = run("What's the weather forecast in Porto Alegre tomorrow?")
    assert res.confidence == 0.3
    assert res.needs_human is False
    assert res.tool_calls[0].ok is False and res.tool_calls[0].error == "timeout"


def test_multi_step_after_support_gives_official_guidance(web_calls):
    support = AgentResult(
        agent="support",
        answer="Your Get Clássica (serial ABC123) is offline since 09:00 (connectivity: chip).",
        data={"intent": "terminal"},
    )
    res = run("My card machine won't connect to the internet, what should I do?", previous=[support])
    assert res.answer.startswith("Official Getnet guidance:")
    assert "troubleshooting" in res.answer.lower() or "reinicie" in res.answer.lower()
    assert "ABC123" not in res.answer
    assert any("operacional" in u for u in urls(res))
