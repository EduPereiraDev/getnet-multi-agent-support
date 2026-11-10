"""Customer Support Agent: resolves merchant-specific issues using the merchant's data via tools.

Skeleton — implementation tracked in specs/03-tasks.md (T-11).
"""

from app.schemas import AgentContext, AgentResult, ToolCall
from app.tools.support_tools import CustomerNotFound, get_customer_profile


class SupportAgent:
    name = "support"

    def run(self, ctx: AgentContext) -> AgentResult:
        # TODO(T-11): tool-use loop (LLM) / intent → tool mapping (offline) over SUPPORT_TOOLS.
        try:
            profile = get_customer_profile(ctx.user_id)
        except CustomerNotFound as exc:
            return AgentResult(
                agent=self.name,
                answer="I couldn't find your merchant account. I'm handing this to a human agent.",
                tool_calls=[ToolCall(tool="get_customer_profile", ok=False, error=str(exc))],
                confidence=0.2,
                needs_human=True,
            )
        return AgentResult(
            agent=self.name,
            answer=f"[support agent pending implementation] merchant: {profile['business_name']}",
            tool_calls=[ToolCall(tool="get_customer_profile", ok=True)],
            confidence=0.5,
        )
