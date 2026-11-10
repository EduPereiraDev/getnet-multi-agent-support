from fastapi import FastAPI, Response

from app.config import get_settings
from app.observability import configure_logging
from app.orchestrator import Orchestrator
from app.schemas import ChatRequest, ChatResponse

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="Getnet Multi-Agent Support",
    version="0.1.0",
    description="Router → Knowledge (RAG + web) / Customer Support (tools) / Human Escalation agents.",
)
orchestrator = Orchestrator()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.resolved_mode}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, response: Response) -> ChatResponse:
    result = orchestrator.handle(req)
    response.headers["X-Trace-Id"] = result.trace_id
    return result
