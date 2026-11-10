"""Orchestration: LLM router with fallback, composition, output guardrails, graceful degradation."""

import pytest

import app.agents.router as router_mod
import app.orchestrator as orch_mod
from app.agents.knowledge import KnowledgeAgent
from app.agents.support import SupportAgent
from app.config import get_settings
from app.guardrails.output import UNGROUNDED_DISCLAIMER, check_output
from app.llm.client import LLMUnavailable
from app.orchestrator import Orchestrator
from app.schemas import AgentResult, ChatRequest, Route, RoutePlan, RouteStep, Source

S05 = "My card machine won't connect to the internet, what should I do?"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "offline")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def llm_mode(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "llm")
    get_settings.cache_clear()


class FakeLLM:
    mode = "llm"

    def __init__(self, result=None, error: Exception | None = None):
        self.result, self.error, self.calls = result, error, []

    def structured(self, system, user, schema, model=None):
        self.calls.append((schema, model))
        if self.error:
            raise self.error
        return self.result


def _knowledge_with_source(self, ctx):
    return AgentResult(
        agent="knowledge",
        answer="Restart the terminal and check the Wi-Fi/chip signal.",
        sources=[Source(title="Getnet FAQ", url="https://site.getnet.com.br/duvidas")],
        confidence=0.8,
    )


def _ask(message: str, user_id: str = "cliente1988"):
    return Orchestrator().handle(ChatRequest(message=message, user_id=user_id))


# --- Router -----------------------------------------------------------------


def test_router_uses_llm_plan_when_valid(llm_mode, monkeypatch):
    llm_plan = RoutePlan(steps=[RouteStep(agent=Route.SUPPORT)], confidence=0.7, rationale="needs data")
    fake = FakeLLM(result=llm_plan)
    monkeypatch.setattr(router_mod, "get_llm", lambda: fake)
    plan = router_mod.RouterAgent().plan("How does antecipação work?")
    assert [s.agent for s in plan.steps] == [Route.SUPPORT]
    assert plan.rationale.startswith("llm:")
    assert fake.calls[0][1] == get_settings().router_model


def test_router_rejects_empty_llm_plan(llm_mode, monkeypatch):
    monkeypatch.setattr(router_mod, "get_llm", lambda: FakeLLM(result=RoutePlan(steps=[], confidence=0.9)))
    plan = router_mod.RouterAgent().plan("How does antecipação work?")
    assert plan.primary == Route.KNOWLEDGE
    assert plan.rationale.startswith("heuristic:")


def test_router_falls_back_to_heuristics_on_llm_error(llm_mode, monkeypatch):
    monkeypatch.setattr(router_mod, "get_llm", lambda: FakeLLM(error=LLMUnavailable("down")))
    plan = router_mod.RouterAgent().plan(S05)
    assert [s.agent.value for s in plan.steps] == ["support", "knowledge"]
    assert plan.rationale.startswith("heuristic:")


def test_explicit_human_request_overrides_llm(llm_mode, monkeypatch):
    wrong = RoutePlan(steps=[RouteStep(agent=Route.KNOWLEDGE)], confidence=0.99)
    monkeypatch.setattr(router_mod, "get_llm", lambda: FakeLLM(result=wrong))
    plan = router_mod.RouterAgent().plan("I want to talk to a human")
    assert plan.primary == Route.ESCALATION


def test_router_offline_is_heuristic():
    assert router_mod.RouterAgent().plan(S05).rationale.startswith("heuristic:")


# --- Composition ------------------------------------------------------------


def test_multi_step_composes_support_then_official_guidance(monkeypatch):
    monkeypatch.setattr(KnowledgeAgent, "run", _knowledge_with_source)
    res = _ask(S05)
    assert res.agents[:3] == ["router", "support", "knowledge"]
    assert "Official guidance:" in res.answer
    assert res.answer.index("Official guidance:") > res.answer.index("GS-0098812")
    assert res.sources and res.sources[0].url.startswith("https://")


def test_empty_knowledge_is_skipped_in_composition(monkeypatch):
    monkeypatch.setattr(KnowledgeAgent, "run", lambda self, ctx: AgentResult(agent="knowledge", answer=""))
    res = _ask(S05)
    assert res.agents[:3] == ["router", "support", "knowledge"]
    assert "Official guidance" not in res.answer
    assert "GS-0098812" in res.answer


def test_llm_composer_used_and_falls_back(llm_mode, monkeypatch):
    monkeypatch.setattr(router_mod, "get_llm", lambda: FakeLLM(error=LLMUnavailable("down")))
    monkeypatch.setattr(KnowledgeAgent, "run", _knowledge_with_source)
    monkeypatch.setattr(orch_mod, "get_llm", lambda: FakeLLM(result=orch_mod.ComposedAnswer(answer="Merged answer.")))
    assert _ask(S05).answer.startswith("Merged answer.")

    monkeypatch.setattr(orch_mod, "get_llm", lambda: FakeLLM(error=LLMUnavailable("down")))
    assert "Official guidance:" in _ask(S05).answer


def test_escalation_answer_is_appended_last():
    res = _ask("I want to talk to a human")
    assert res.escalated and res.handoff_ticket.startswith("HUM-")
    assert res.agents == ["router", "escalation"]
    assert res.handoff_ticket in res.answer


# --- Graceful degradation -----------------------------------------------------


def test_agent_exception_escalates_instead_of_500(client, monkeypatch):
    def boom(self, ctx):
        raise RuntimeError("tool backend down")

    monkeypatch.setattr(SupportAgent, "run", boom)
    r = client.post("/chat", json={"message": "When will yesterday's sales be deposited?", "user_id": "cliente1988"})
    assert r.status_code == 200
    body = r.json()
    assert body["escalated"] is True
    assert body["handoff_ticket"].startswith("HUM-")
    assert body["agents"][-1] == "escalation"
    failed = [tc for tc in body["tool_calls"] if tc["tool"] == "agent.support"]
    assert failed and failed[0]["ok"] is False and failed[0]["error"] == "tool_error"  # raw text stays in logs only


# --- Output guardrails --------------------------------------------------------


def test_output_masks_leaked_cpf_but_keeps_support_phone(monkeypatch):
    def leaky(self, ctx):
        return AgentResult(
            agent="support",
            answer="Owner CPF 123.456.789-09 confirmed. Call 4002-4000 or 0800-648-8000.",
            confidence=0.9,
        )

    monkeypatch.setattr(SupportAgent, "run", leaky)
    res = _ask("When will yesterday's sales be deposited?")
    assert "123.456.789-09" not in res.answer
    assert "[CPF_MASKED]" in res.answer
    assert "4002-4000" in res.answer and "0800-648-8000" in res.answer


def test_ungrounded_knowledge_gets_disclaimer_and_penalty():
    results = [AgentResult(agent="knowledge", answer="Antecipação costs 1% per month.", confidence=0.9)]
    out = check_output(results[0].answer, results)
    assert "ungrounded" in out.flags
    assert out.answer.endswith(UNGROUNDED_DISCLAIMER)
    assert out.confidence_penalty == pytest.approx(0.3)


def test_grounded_and_empty_answers():
    grounded = [AgentResult(agent="knowledge", answer="x", sources=[Source(title="t", url="https://u")])]
    assert check_output("x", grounded).flags == []
    empty = check_output("  ", [])
    assert empty.flags == ["empty"] and empty.confidence_penalty == 1.0


def test_ungrounded_penalty_triggers_escalation(monkeypatch):
    def ungrounded(self, ctx):
        return AgentResult(agent="knowledge", answer="Antecipação is free forever.", confidence=0.7)

    monkeypatch.setattr(KnowledgeAgent, "run", ungrounded)
    res = _ask("How does antecipação work with Getnet?")
    assert UNGROUNDED_DISCLAIMER in res.answer
    assert res.confidence < get_settings().escalation_confidence
    assert res.escalated and res.agents[-1] == "escalation"


@pytest.mark.parametrize(
    "text",
    ["Protocol 20261110123456789 opened", "Transaction id 12345678901234", "Ticket HD-12345678901"],
)
def test_output_masking_keeps_ids(text):
    assert check_output(text, []).answer == text


def test_output_masking_card_and_formatted_cpf():
    out = check_output("Card 4111 1111 1111 1111, CPF 123.456.789-09, call 4002-4000", [])
    assert "4111" not in out.answer and "123.456.789-09" not in out.answer and "4002-4000" in out.answer


def test_router_plan_is_capped_at_three_steps():
    with pytest.raises(ValueError):
        RoutePlan(steps=[RouteStep(agent=Route.KNOWLEDGE)] * 4, confidence=0.9)


def test_public_tool_calls_have_no_args():
    res = _ask(S05)
    assert res.tool_calls and all(tc.args == {} for tc in res.tool_calls)
