"""Human Escalation Agent (bonus): structured handoff to a human operator."""

import uuid

from app.schemas import AgentContext, AgentResult, ToolCall


class EscalationAgent:
    name = "escalation"

    def run(self, ctx: AgentContext) -> AgentResult:
        # TODO(T-12): LLM case summary for the operator; push to a real queue (Zendesk/Teams).
        ticket = f"HUM-{uuid.uuid4().hex[:8].upper()}"
        reasons = [r.agent for r in ctx.previous if r.needs_human]
        return AgentResult(
            agent=self.name,
            answer=(
                "I've forwarded your request to a Getnet specialist "
                f"(protocol {ticket}). You'll be contacted shortly. "
                "Support hours: 6am–10pm, 4002-4000 (capitals) or 0800-648-8000."
            ),
            tool_calls=[ToolCall(tool="create_handoff_ticket", ok=True, args={"reasons": reasons})],
            confidence=1.0,
            data={"handoff_ticket": ticket},
        )
