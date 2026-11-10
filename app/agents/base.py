from typing import Protocol

from app.schemas import AgentContext, AgentResult


class Agent(Protocol):
    """Every agent takes an AgentContext and returns an AgentResult (transport-agnostic contract)."""

    name: str

    def run(self, ctx: AgentContext) -> AgentResult: ...
