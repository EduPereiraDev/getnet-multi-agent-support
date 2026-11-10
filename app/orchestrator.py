"""Orchestrator: guardrails → router plan → agent steps (with data flow) → composition →
output guardrails → response."""

import json
import time

from pydantic import BaseModel

from app.agents.escalation import EscalationAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.router import RouterAgent
from app.agents.support import SupportAgent
from app.config import get_settings
from app.guardrails.input import check_input
from app.guardrails.output import check_output, has_content
from app.llm.client import get_llm, load_prompt
from app.observability import new_trace_id, span
from app.schemas import (
    AgentContext,
    AgentResult,
    ChatRequest,
    ChatResponse,
    GuardrailReport,
    Route,
    ToolCall,
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




class ComposedAnswer(BaseModel):
    answer: str


def compose_offline(results: list[AgentResult]) -> str:
    """Merchant-specific diagnosis first, then official guidance from the knowledge agent."""
    support = [r.answer for r in results if r.agent != "knowledge" and r.answer.strip()]
    knowledge = [r.answer for r in results if r.agent == "knowledge" and has_content(r.answer)]
    parts = list(support)
    if knowledge:
        parts.append("Official guidance:\n" + "\n\n".join(knowledge))
    return "\n\n".join(parts)


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
            results.append(self._run_agent(step.agent, ctx))

        def escalate(trigger: str) -> None:
            ctx = AgentContext(trace_id=trace_id, user_id=req.user_id, message=req.message,
                               masked_message=check.masked_message, previous=results.copy())
            results.append(self._run_agent(Route.ESCALATION, ctx, trigger=trigger))

        # Human handoff: explicit escalation, an agent asking for help, or low confidence.
        confidence = min(plan.confidence, *(r.confidence for r in results))
        needs_human = any(r.needs_human for r in results) or confidence < self.settings.escalation_confidence
        if needs_human and plan.primary != Route.ESCALATION:
            escalate("handoff")

        answer = ""
        answers = [r for r in results if r.agent != Route.ESCALATION.value]
        if answers:
            answer = self._compose(answers, check.masked_message, trace_id)
            with span("guardrail.output", trace_id) as s:
                out = check_output(answer, answers)
                s.update(flags=out.flags, pii_masked=out.pii_masked, penalty=out.confidence_penalty)
            answer = out.answer
            confidence = max(0.0, confidence - out.confidence_penalty)
            escalated = any(r.agent == Route.ESCALATION.value for r in results)
            if not escalated and confidence < self.settings.escalation_confidence:
                escalate("output_guardrail")

        escalations = [r.answer for r in results if r.agent == Route.ESCALATION.value and r.answer]
        answer = "\n\n".join(part for part in [answer, *escalations] if part)
        ticket = next((r.data["handoff_ticket"] for r in results if "handoff_ticket" in r.data), None)
        return respond(
            answer,
            plan.primary,
            ["router", *[r.agent for r in results]],
            results,
            confidence,
            escalated=ticket is not None,
            ticket=ticket,
        )

    def _run_agent(self, route: Route, ctx: AgentContext, **fields: str) -> AgentResult:
        """Runs one agent step; any failure becomes a zero-confidence result that forces a handoff."""
        with span(f"agent.{route.value}", ctx.trace_id, **fields) as s:
            try:
                return self.agents[route].run(ctx)
            except Exception as exc:  # noqa: BLE001 - an agent failure must never 500 the API
                s.update(agent_error=repr(exc))
                return AgentResult(
                    agent=route.value,
                    answer="",
                    confidence=0.0,
                    needs_human=True,
                    tool_calls=[ToolCall(tool=f"agent.{route.value}", ok=False, error=repr(exc))],
                )

    def _compose(self, results: list[AgentResult], masked_message: str, trace_id: str) -> str:
        if len(results) < 2:
            return results[0].answer if results else ""
        if self.settings.resolved_mode == "llm":
            payload = json.dumps(
                {
                    "question": masked_message,
                    "steps": [r.model_dump(include={"agent", "answer", "sources"}) for r in results],
                },
                ensure_ascii=False,
            )
            with span("composer", trace_id) as s:
                try:
                    composed = get_llm().structured(load_prompt("composer"), payload, ComposedAnswer)
                    if isinstance(composed, ComposedAnswer) and composed.answer.strip():
                        s.update(path="llm")
                        return composed.answer
                except Exception as exc:  # noqa: BLE001 - fall back to deterministic composition
                    s.update(path="offline", llm_error=repr(exc))
        return compose_offline(results)
