# 01 — Requirements

Notation: EARS-style ("WHEN … THE SYSTEM SHALL …"). Priority: **M** = must (core brief),
**B** = bonus, **N** = nice-to-have. Each ID is referenced by tasks and tests.

## Functional

| ID | Pri | Requirement |
|---|---|---|
| REQ-01 | M | THE SYSTEM SHALL expose `POST /chat` accepting `{"message": str, "user_id": str}` and returning JSON. |
| REQ-02 | M | WHEN a message arrives THE **Router Agent** SHALL classify it and produce an execution plan: one agent or an ordered sequence of agents. |
| REQ-03 | M | THE Router SHALL manage data flow between agents: the output of one step is available as context to the next step. |
| REQ-04 | M | WHEN the plan targets knowledge THE **Knowledge Agent** SHALL answer about Getnet products/services grounded in retrieved documents (RAG) and cite source URLs. |
| REQ-05 | M | WHEN the question is general-purpose (not about Getnet) THE Knowledge Agent SHALL use a **web search tool** (plus dedicated weather/FX tools when applicable). |
| REQ-06 | M | THE RAG pipeline SHALL ingest the specified URLs (getnet.net/en) **and additional Getnet sources** (site.getnet.com.br product + FAQ pages) into a persistent index. |
| REQ-07 | M | WHEN the plan targets support THE **Customer Support Agent** SHALL retrieve the user's data via tools to resolve the inquiry. |
| REQ-08 | M | THE Customer Support Agent SHALL have **at least 2 tools** (implemented: profile, settlements, terminals, transactions, ticket). |
| REQ-09 | M | THE response SHALL include the final answer, the agents involved, the route, the sources and a trace id. |
| REQ-10 | B | THE SYSTEM SHALL include a 4th **Human Escalation Agent** that creates a handoff ticket for a human operator. |
| REQ-11 | B | WHEN a request is unsafe, sensitive, irrelevant or unsupported THE **guardrails** SHALL block, mask or redirect it before any agent runs. |
| REQ-12 | B | WHEN confidence is below threshold, the user asks for a human, or a tool fails THE SYSTEM SHALL hand off to a human (redirect mechanism). |
| REQ-13 | B | THE SYSTEM SHALL provide an evaluation + observability strategy (golden dataset, metrics, structured logs, traces, alerts). |

## Non-functional

| ID | Pri | Requirement |
|---|---|---|
| NFR-01 | M | THE application SHALL build and run with `docker compose up --build` (and plain `docker build/run`). |
| NFR-02 | M | THE code SHALL be modular: one module per agent, tools, RAG, guardrails, LLM client, API. |
| NFR-03 | M | THE SYSTEM SHALL run **without an LLM key** in a deterministic offline mode (heuristic router + extractive answers) so tests and demos never depend on a paid API. |
| NFR-04 | M | Automated tests SHALL run with `pytest` offline (no network, no key). |
| NFR-05 | B | Every request SHALL emit structured JSON logs with `trace_id`, per-agent spans, latency and route. |
| NFR-06 | B | PII (CPF/CNPJ, card numbers, e-mail, phone) SHALL be masked before reaching the LLM and logs. |
| NFR-07 | N | External calls (LLM, web) SHALL have timeouts and graceful degradation (fallback answer or handoff, never a 500 with a stack trace). |
| NFR-08 | N | Prompts SHALL live in versioned files, separate from code. |

## Out of scope (explicit)

- Real Getnet customer data or authentication — support data is a **mock repository** behind a tool interface.
- Multi-turn memory across requests (each request is independent; `user_id` scopes data).
- UI — the API (+ OpenAPI docs at `/docs`) is the interface.
