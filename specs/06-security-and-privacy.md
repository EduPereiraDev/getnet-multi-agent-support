# 06 — Security & Privacy (OWASP · OWASP LLM · LGPD)

The system handles merchant personal and financial data (Brazil). This spec maps the controls to
**OWASP Top 10 (2021)**, **OWASP Top 10 for LLM Applications (2025)** and **LGPD (Lei 13.709/2018)**.
It separates what is **enforced in code** from what is a **documented limitation** of this
challenge (mock data, no identity provider).

Evidence comes from three independent read-only audits (code/LLM, config/supply chain, coverage).
The fixes are tested in `tests/test_api.py`, `tests/test_orchestration.py` and `tests/test_guardrails.py`.

## 1. Data flow and where PII is controlled

```
request ──► input guardrails ──► masked_message ──► router / agents / LLM / logs
             (mask CPF, CNPJ, card, e-mail, phone;     (raw message is never stored, logged or
              block injection & harmful requests)       passed to agents — AgentContext has no raw field)
merchant tools ──► user_id bound server-side ──► answer ──► output guardrails ──► response
                                                             (mask formatted CPF/CNPJ, Luhn-valid cards,
                                                              e-mail; tool args & errors stripped)
```

## 2. OWASP Top 10 (2021)

| Item | Status | Control / evidence |
|---|---|---|
| A01 Broken access control | **Limitation (documented)** | No authentication: `user_id` comes from the body, as specified by the brief. Tools are bound to that id server-side (`run_support_tool(name, ctx.user_id, args)`), so the model can never switch merchants. **Production:** take the identity from a verified token (OAuth2/JWT or mTLS at the gateway) and ignore the body field. |
| A03 Injection | Enforced | No SQL or shell. Web-tool params are encoded by httpx. `user_id` must match `^[A-Za-z0-9_-]{1,64}$` (422 otherwise). |
| A04 Insecure design | Enforced | Router plans capped at 3 steps. Tool loop budget of 5. Per-IP rate limit (`RATE_LIMIT_PER_MINUTE`, 429). Human handoff on low confidence or failure. |
| A05 Security misconfiguration | Enforced | `nosniff`, `X-Frame-Options: DENY` and `Cache-Control: no-store` on every response. `/docs` can be turned off (`EXPOSE_DOCS=false`). Raw exception text is never returned (`tool_error`). The image has no dev deps or tests. `.dockerignore` keeps out `.env` and `.git`. Container runs as non-root. |
| A06 Vulnerable components | Partial | Dependencies are capped below the next major version. **Next:** a lockfile with hashes (`uv lock`), dependency scanning in CI, and a base image pinned by digest. |
| A08 Integrity | Partial | The RAG index is pickled but only written locally at build time; not reachable over HTTP. **Next:** `save_npz` + JSON vocab, or a hash check. |
| A09 Logging & monitoring | Enforced | JSON spans per step with `trace_id`. Logs carry PII *kinds*, never message text. **Next:** a per-trace audit record of merchant id and tools used (LGPD art. 37), kept in a restricted store. |
| A10 SSRF | Enforced | Runtime tools call fixed hosts only (Open-Meteo, Frankfurter, DuckDuckGo). The crawler only reads `data/sources.yaml` at build time. |

## 3. OWASP Top 10 for LLM Applications (2025)

| Item | Status | Control / evidence |
|---|---|---|
| LLM01 Prompt injection | Enforced (best-effort) | Regex filter on input. Every prompt treats user content as untrusted data. Explicit human requests override the LLM router. Tools are read-only (the only write is a ticket) and bound to the merchant server-side. The `user_id` channel is validated. Regex detection can be bypassed: impact is limited by design, not by detection. |
| LLM02 Sensitive info disclosure | Enforced | Only masked text reaches the LLM and the logs. Output masking runs on the answer. The public `tool_calls` list exposes only tool name and status (no model-written args, no errors). In multi-step plans the Knowledge LLM gets no free-text `web_search`, so merchant data from earlier steps cannot leave in a query. |
| LLM05 Improper output handling | Enforced | Answers are plain JSON text, never executed or rendered as HTML by the API. Sources come from the curated corpus and fixed APIs. |
| LLM06 Excessive agency | Enforced | Support tools are read-only except `create_support_ticket` (mock). `user_id` is injected by the server, never by the model. The loop has a budget, and an answer with no successful tool call is rejected. |
| LLM07 System prompt leakage | Enforced | Prompts hold no secrets, and they instruct the model not to reveal themselves. |
| LLM10 Unbounded consumption | Enforced | Message ≤ 2,000 chars. Plans ≤ 3 steps. ≤ 5 tool iterations. 30 s timeout with 1 retry. Rate limit per IP. **Production:** gateway quotas per authenticated merchant, plus a cost budget alert. |

## 4. LGPD

| Article | Status | How |
|---|---|---|
| Art. 6 I–III (finalidade, adequação, necessidade) | Enforced | Data is used only to answer the merchant's own request. Agents get only the masked message plus the tool data the intent needs; the raw message is dropped right after the guardrail. No conversation storage. |
| Art. 6 VII / Art. 46 (segurança, prevenção) | Enforced + limitation | Masking at input, output and logs. Rate limiting, headers, non-root container, secrets only via env (`.env` is git- and docker-ignored). Missing authentication is the documented gap (A01). |
| Art. 6 VI / Art. 9 (transparência) | Documented | This spec and the README list what is processed and where it goes. Answers cite their sources. |
| Art. 33 (transferência internacional) | **Limitation (documented)** | In LLM mode, the masked message and the tool results the answer needs (business name, amounts, terminal serials) are sent to Anthropic (outside Brazil). **Production:** a DPA with standard contractual clauses (art. 33 II), the zero-data-retention option, or a region-pinned deployment. Offline mode sends nothing out. |
| Art. 37 (registro das operações) | Partial | `trace_id`-correlated spans exist. **Production:** a processing record (RoPA) and an access log of merchant id and tools used, with restricted access. |
| Art. 18 (direitos do titular) | N/A here | No personal data is persisted (mock repository, stateless API). **Production:** access, correction and deletion flows owned by the system of record. |
| Art. 48 (comunicação de incidentes) | Out of scope | Belongs to the company's incident process (DPO + ANPD). Alerting hooks are in specs/04 §4. |

## 5. Residual risks (accepted for the challenge)

1. No authentication or authorisation: any caller can query any mock merchant.
2. Regex PII and injection detection is best-effort: it does not catch names, addresses or bank
   accounts.
3. An in-process rate limiter is per instance; production needs gateway quotas.
4. No lockfile or base-image digest.
5. International transfer to the LLM provider needs a legal basis before production.
