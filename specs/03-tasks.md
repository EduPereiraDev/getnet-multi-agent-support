# 03 — Tasks

Status: ✅ done · 🟡 in progress · ⬜ todo. Each task lists the requirements it satisfies and how it
is verified. Sprint grouping and parallelism: [`05-execution-plan.md`](05-execution-plan.md)
(S1 = T-08 · S2 = T-14/T-15 · S3 = T-09/T-11 · S4 = T-10 · S5 = T-07/T-12/T-13 · S6 = T-16..T-19).

| ID | Task | Reqs | Verify | Status |
|---|---|---|---|---|
| T-01 | SDD specs: context, requirements, design, tasks, testing | all | review | ✅ |
| T-02 | Project skeleton: pyproject, Dockerfile, compose, Makefile, .env.example | NFR-01/02 | `docker compose build` | ✅ |
| T-03 | Pydantic contracts (`schemas.py`) + settings (`config.py`) | REQ-01/09 | unit tests | ✅ |
| T-04 | FastAPI `POST /chat`, `GET /health`, trace header | REQ-01/09 | `tests/test_api.py` | ✅ |
| T-05 | Input guardrails (PII mask, injection, harmful, length) | REQ-11, NFR-06 | `tests/test_guardrails.py` | ✅ |
| T-06 | Support tools over mock repository (5 tools) | REQ-07/08 | `tests/test_tools.py` | ✅ |
| T-07 | Router agent — offline heuristics + LLM structured output | REQ-02/03 | `tests/test_router.py`, eval set | 🟡 heuristics done |
| T-08 | RAG: sources.yaml, seed corpus, ingest, chunk, TF-IDF store, retrieve | REQ-04/06 | `tests/test_rag.py` | ⬜ |
| T-09 | Web tools: web search, weather (Open-Meteo), FX (Frankfurter) | REQ-05 | mocked tests | ⬜ |
| T-10 | Knowledge agent (RAG + web, citations) | REQ-04/05 | eval set | ⬜ |
| T-11 | Customer Support agent (tool loop + templated offline) | REQ-07 | eval set | ⬜ |
| T-12 | Human Escalation agent + handoff triggers | REQ-10/12 | tests | ⬜ |
| T-13 | Orchestrator: multi-step plans, context passing, output guardrails | REQ-03/12 | API tests | ⬜ |
| T-14 | Anthropic LLM client (tool loop, structured outputs, timeouts) | REQ-02/04/07, NFR-07 | manual + mocked | ⬜ |
| T-15 | Prompts in `app/prompts/*.md` | NFR-08 | review | ⬜ |
| T-16 | Observability: JSON logs, spans, latency | REQ-13, NFR-05 | log inspection | 🟡 base done |
| T-17 | Golden eval runner over 10 scenarios + extra adversarial cases | REQ-13 | `pytest tests/evals` | ⬜ |
| T-18 | README: build/run/test, architecture, workflow, RAG, tools, eval | all | review | 🟡 |
| T-19 | Docker end-to-end smoke (`docker compose up` + curl scenarios) | NFR-01 | `make smoke` | ⬜ |
