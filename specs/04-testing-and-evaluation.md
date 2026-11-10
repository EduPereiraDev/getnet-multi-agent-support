# 04 — Testing & Evaluation Strategy

## 1. Test pyramid

| Layer | What | How | Runs offline |
|---|---|---|---|
| Unit | Guardrails regexes, PII masking, tools over mock data, chunker, retriever, router heuristics | `pytest tests/test_*.py` | ✅ |
| Contract | Pydantic schemas, API status codes, payload validation (422), response shape | FastAPI `TestClient` | ✅ |
| Integration (orchestration) | Full request through guardrails → router → agent(s) → response with **offline LLM** and **mocked HTTP** for web tools | `TestClient` + `respx`/monkeypatch | ✅ |
| Integration (LLM) | Same flows against the real model, marked `@pytest.mark.llm`, skipped without credentials | `pytest -m llm` | ❌ (needs key) |
| Evaluation | Golden dataset: expected route, agents, tools, must-contain facts, must-not-contain, escalation | `pytest tests/evals` + report | ✅ offline / LLM |
| E2E / smoke | Container up, curl the 10 scenarios, assert 200 + route | `make smoke` | ✅ |

## 2. Integration testing the orchestration (how we approach it)

1. **Deterministic doubles at the edges, real code in the middle.** Replace only the LLM (OfflineLLM
   or a scripted fake that returns a predefined `RoutePlan`/tool calls) and HTTP (weather/FX/search);
   everything else (router plan execution, context passing, tools, RAG, guardrails) runs for real.
2. **Assert on the trace, not just the text.** Each response exposes `route`, `agents`,
   `tool_calls`, `sources`, `escalated` — tests assert the *path* (e.g. scenario 5 must call
   `get_terminal_status` and then retrieve FAQ troubleshooting chunks).
3. **Failure injection.** Tool raises / times out → answer degrades gracefully and escalates;
   LLM error → offline fallback; empty retrieval → web search or "don't know" + escalation.
4. **Scripted LLM fakes** to test the tool-use loop: a fake returns `tool_use` → we execute the tool
   → fake returns final text; verifies loop limits and tool result plumbing.
5. **Contract tests** keep agents swappable (any agent must accept `AgentContext` and return a valid
   `AgentResult`).

## 3. Evaluation (AI quality)

Golden set = the 10 brief scenarios + adversarial/edge cases (prompt injection, PII in message,
asking for a human, out-of-scope, unknown user_id, Portuguese phrasing).

| Metric | Definition | Gate (CI) |
|---|---|---|
| Routing accuracy | expected route == actual | ≥ 90% |
| Tool selection accuracy | expected tools ⊆ called tools | ≥ 90% |
| Groundedness | product answers cite ≥1 source and contain the expected facts | ≥ 85% |
| Safety | adversarial cases blocked / masked / escalated as expected | 100% |
| Escalation precision | escalations only when expected | ≥ 90% |

LLM mode adds an **LLM-as-judge** pass (faithfulness to retrieved context, helpfulness, tone) on a
1–5 rubric, run nightly / pre-release, with a cheaper judge model.

## 4. Observability & production monitoring

- **Logs**: JSON per span (`request`, `guardrail`, `router`, `agent`, `tool`, `llm`), with `trace_id`.
- **Traces**: span model compatible with OpenTelemetry (exporter pluggable: Langfuse / Datadog / Jaeger).
- **Dashboards**: volume by route, containment rate, escalation rate, guardrail blocks by reason,
  tool error rate, p50/p95 latency per agent, tokens & cost per request, user feedback.
- **Alerts**: escalation rate spike, tool error rate > 5%, p95 > SLO, guardrail block spike
  (possible attack), retrieval "no result" rate rising (KB drift → re-ingest).
- **Feedback loop**: escalated/thumbs-down conversations → reviewed → added to golden set
  (regression) → prompt/KB fixes gated by the eval suite.
