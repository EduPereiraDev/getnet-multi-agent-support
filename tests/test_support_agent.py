import pytest

import app.config
from app.agents.support import SupportAgent
from app.schemas import AgentContext


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "offline")
    app.config.get_settings.cache_clear()
    yield
    app.config.get_settings.cache_clear()


def _run(message: str, user_id: str = "cliente1988"):
    ctx = AgentContext(trace_id="t-1", user_id=user_id, message=message, masked_message=message)
    return SupportAgent().run(ctx)


def _tools(result) -> list[str]:
    return [c.tool for c in result.tool_calls]


def test_s03_settlement_schedule():
    res = _run("When will the money from yesterday's sales be deposited?")
    assert "get_settlement_schedule" in _tools(res)
    assert "R$ 345.25" in res.answer and "2026-11-11" in res.answer
    assert res.data["settlements"]["total_net"] == 345.25
    assert res.confidence == 0.8 and not res.needs_human


def test_s05_terminal_offline_opens_ticket():
    res = _run("My card machine won't connect to the internet, what should I do?")
    assert _tools(res) == ["get_terminal_status", "create_support_ticket"]
    assert "GS-0098812" in res.answer and "SUP-" in res.answer
    assert res.data["ticket"]["ticket_id"].startswith("SUP-")


def test_s08_decline_explains_codes():
    res = _run("My card machine is showing a transaction decline error.")
    assert "get_recent_transactions" in _tools(res)
    assert res.tool_calls[0].args == {"status": "declined"}
    assert "5 minutes" in res.answer and "51" in res.answer
    assert len(res.data["declined"]) == 2


def test_generic_message_returns_profile_summary():
    res = _run("Hello there")
    assert "Padaria" in res.answer and res.confidence == 0.5


def test_unknown_user_needs_human():
    res = _run("When will I receive my sales?", user_id="nobody")
    assert res.needs_human and res.confidence == 0.2
    assert not res.tool_calls[0].ok


def test_llm_failure_falls_back_to_offline(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "llm")
    app.config.get_settings.cache_clear()
    monkeypatch.setattr(SupportAgent, "_run_llm", lambda self, ctx: (_ for _ in ()).throw(RuntimeError("down")))
    res = _run("When will the money from yesterday's sales be deposited?")
    assert "get_settlement_schedule" in _tools(res)
