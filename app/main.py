import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request, Response

from app.config import get_settings
from app.observability import configure_logging, log_event
from app.orchestrator import Orchestrator
from app.schemas import ChatRequest, ChatResponse

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="Getnet Multi-Agent Support",
    version="0.1.0",
    description="Router → Knowledge (RAG + web) / Customer Support (tools) / Human Escalation agents.",
    docs_url="/docs" if settings.expose_docs else None,
    redoc_url="/redoc" if settings.expose_docs else None,
    openapi_url="/openapi.json" if settings.expose_docs else None,
)
orchestrator = Orchestrator()

# In-process sliding-window limiter per client IP (OWASP API4 / LLM10: caps LLM cost per caller).
# Production: enforce at the API gateway with authenticated identities.
_requests: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(client: str) -> None:
    now = time.monotonic()
    window = _requests[client]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        log_event("rate_limited", client=client)
        raise HTTPException(status_code=429, detail="Too many requests, please retry in a minute.")
    window.append(now)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.resolved_mode}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, response: Response) -> ChatResponse:
    _check_rate_limit(request.client.host if request.client else "unknown")
    result = orchestrator.handle(req)
    response.headers["X-Trace-Id"] = result.trace_id
    return result
