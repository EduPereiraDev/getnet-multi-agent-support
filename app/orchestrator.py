"""Orchestrator: guardrails → router plan → agent steps (with data flow) → response."""

import time

from app.agents.escalation import EscalationAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.router import RouterAgent
from app.agents.support import SupportAgent
from app.config import get_settings
from app.guardrails.input import check_input
from app.observability import new_trace_id, span
from app.schemas import (
    AgentContext,
    AgentResult,
    ChatRequest,
    ChatResponse,
    GuardrailReport,
    Route,
)

BLOCKED_ANSWER = (
    "I can't help with that request. I can answer questions about Getnet products and services "
    "or help with your account, card machine, sales and settlements."
)
OUT_OF_SCOPE_ANSWER = (
    "I'm Getnet's assistant. I can help with Getnet products (card machines, Pix, Payment Link, "
    "crediário, receivables advance), your account and sales, or general questions like weather and "
    "exchange rates. Could you rephrase your question?"
)


class Orchestrator:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.router = RouterAgent()
        self.agents = {
            Route.KNOWLEDGE: KnowledgeAgent(),
            Route.SUPPORT: SupportAgent(),
            Route.ESCALATION: EscalationAgent(),
        }

    def handle(self, req: ChatRequest) -> ChatResponse:
        start = time.perf_counter()
        trace_id = new_trace_id()
        mode = self.settings.resolved_mode

        with span("guardrail.input", trace_id) as s:
            check = check_input(req.message)
            s.update(blocked=check.blocked, reason=check.reason, pii=check.pii_found)
        guard = GuardrailReport(pii_masked=bool(check.pii_found), blocked=check.blocked, reason=check.reason)

        def respond(answer: str, route: Route, agents: list[str], results: list[AgentResult],
                    confidence: float, escalated: bool = False, ticket: str | None = None) -> ChatResponse:
            return ChatResponse(
                trace_id=trace_id,
                answer=answer,
                route=route,
                agents=agents,
                sources=[src for r in results for src in r.sources],
                tool_calls=[tc for r in results for tc in r.tool_calls],
                confidence=round(confidence, 2),
                escalated=escalated,
                handoff_ticket=ticket,
                guardrails=guard,
                latency_ms=int((time.perf_counter() - start) * 1000),
                mode=mode,
            )

        if check.blocked:
            return respond(BLOCKED_ANSWER, Route.BLOCKED, ["guardrails"], [], 1.0)

        with span("router", trace_id) as s:
            plan = self.router.plan(check.masked_message)
            s.update(steps=[st.agent.value for st in plan.steps], confidence=plan.confidence)

        if plan.primary == Route.OUT_OF_SCOPE:
            return respond(OUT_OF_SCOPE_ANSWER, Route.OUT_OF_SCOPE, ["router"], [], plan.confidence)

        results: list[AgentResult] = []
        for step in plan.steps:
            ctx = AgentContext(
                trace_id=trace_id,
                user_id=req.user_id,
                message=req.message,
                masked_message=check.masked_message,
                instruction=step.instruction,
                previous=results.copy(),
            )
            with span(f"agent.{step.agent.value}", trace_id):
                results.append(self.agents[step.agent].run(ctx))

        # Human handoff: explicit escalation, an agent asking for help, or low confidence.
        confidence = min(plan.confidence, *(r.confidence for r in results))
        needs_human = any(r.needs_human for r in results) or confidence < self.settings.escalation_confidence
        if needs_human and plan.primary != Route.ESCALATION:
            ctx = AgentContext(trace_id=trace_id, user_id=req.user_id, message=req.message,
                               masked_message=check.masked_message, previous=results.copy())
            with span("agent.escalation", trace_id, trigger="handoff"):
                results.append(self.agents[Route.ESCALATION].run(ctx))

        ticket = next((r.data["handoff_ticket"] for r in results if "handoff_ticket" in r.data), None)
        # TODO(T-13): compose multi-step answers with the LLM and run output guardrails.
        answer = "\n\n".join(r.answer for r in results)
        return respond(
            answer,
            plan.primary,
            ["router", *[r.agent for r in results]],
            results,
            confidence,
            escalated=ticket is not None,
            ticket=ticket,
        )
