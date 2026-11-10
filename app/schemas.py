"""Typed contracts shared by the API, the orchestrator and every agent."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, examples=["How does antecipação work?"])
    user_id: str = Field(..., min_length=1, max_length=64, examples=["cliente1988"])


class Route(str, Enum):
    KNOWLEDGE = "knowledge"
    SUPPORT = "support"
    ESCALATION = "escalation"
    OUT_OF_SCOPE = "out_of_scope"
    BLOCKED = "blocked"


class RouteStep(BaseModel):
    agent: Route
    instruction: str = Field("", description="What this agent should focus on in this step")


class RoutePlan(BaseModel):
    """Router output: an ordered list of agent steps plus a confidence score."""

    steps: list[RouteStep]
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""

    @property
    def primary(self) -> Route:
        return self.steps[0].agent if self.steps else Route.OUT_OF_SCOPE


class Source(BaseModel):
    title: str
    url: str


class ToolCall(BaseModel):
    tool: str
    ok: bool
    args: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentResult(BaseModel):
    agent: str
    answer: str
    sources: list[Source] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    confidence: float = 1.0
    needs_human: bool = False
    data: dict[str, Any] = Field(default_factory=dict)


class GuardrailReport(BaseModel):
    pii_masked: bool = False
    blocked: bool = False
    reason: str | None = None


class AgentContext(BaseModel):
    """Message passed between agents. `previous` carries earlier step outputs (data flow)."""

    trace_id: str
    user_id: str
    message: str
    masked_message: str
    instruction: str = ""
    previous: list[AgentResult] = Field(default_factory=list)


class ChatResponse(BaseModel):
    trace_id: str
    answer: str
    route: Route
    agents: list[str]
    sources: list[Source] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    confidence: float
    escalated: bool = False
    handoff_ticket: str | None = None
    guardrails: GuardrailReport = Field(default_factory=GuardrailReport)
    latency_ms: int
    mode: str
