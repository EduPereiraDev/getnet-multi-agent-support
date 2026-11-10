# 00 — Context & Sources

> Spec-Driven Development (SDD) flow used in this repo:
> **context → requirements → design → tasks → implementation → verification**.
> Every task in `03-tasks.md` traces back to a requirement ID in `01-requirements.md`,
> and every requirement has an acceptance check in `04-testing-and-evaluation.md`.

## 1. Problem statement

Getnet (Santander group acquirer, #1 LATAM acquirer by purchase volume, 1.2M+ active merchants)
needs a **multi-agent support system** that receives a merchant message plus a `user_id`, decides
which specialist should act, and returns a grounded, safe, useful JSON answer over HTTP.

## 2. Inputs analysed

| Source | What it gave us |
|---|---|
| Challenge brief `AI_Hardcore_Engineer_Multi-Agent.md` | Hard requirements (3+ agents, RAG + web search, 2+ support tools, FastAPI POST, Docker, testing strategy, README), bonus items (4th agent, guardrails, human handoff, eval/observability) and 10 example scenarios. |
| Recruiter e-mail | SDD is mandatory, 60-min core-dev box, best attempt wins, GitHub repo + unlisted YouTube video (≤15 min), 1-week deadline. |
| https://www.getnet.net/en (global) | Positioning: "The Leading AI Payments Company in Latin America and Europe", solutions (in-person, online, omnichannel, value-added, **Agentic Commerce**), footprint (BR, MX, CL, AR, UY, CO, ES, PT). Thin on product detail → **not enough alone for the scenarios**. |
| https://site.getnet.com.br/ (Brazil) | The products named in the scenarios live here: Get Mini / **Get Clássica** / **Get Smart** / Get Tap, **Pix**, **Link de Pagamento**, **Crediário** (up to 48x), Get Conta, Empréstimo, TEF, fees table. |
| https://site.getnet.com.br/duvidas/ (+ ~30 FAQ sub-pages) | The richest grounding: settlement terms (D+1/D+2/D+31), Pix key rules, Algar chip/connectivity steps, duplicate-sale auto-cancel (decline-like behaviour), antecipação rules, crediário enablement, link de pagamento rules. |
| Getnet AI vision (CTO interview — itsitio.com; agentic-commerce coverage — letsmoney.com.br) | "There must always be a human who understands" → **human-in-the-loop**; security as a pillar, tokenisation, **mandatory audit gates before production** → guardrails + evaluation gates; "the ecosystem must be strong and simple" → simple API, one endpoint. Agentic commerce with agent identification/validation and prior consumer authorisation. |
| LinkedIn — Leonardo Frisso (Global Director of AI Operations / AI Deployment Engineering, Getnet; ex-Head of AI Ops Engineering at CloudWalk; ex-Pagar.me risk & ops) | Focus on **Forward Deployed Engineering**, **E2E agentic operations** and AI delivery: teams that "build and deploy autonomous agents that automate business processes end to end"; mission to "build the operational layer through hard AI Engineering". Recent shares stress that value comes from **redesigning workflows**, not just adding AI to existing ones. |

## 2.1 Design implications of the AI vision

1. **Resolve, don't just answer.** The Support Agent must *act* on the user's data (look up settlements,
   terminal status, declined transactions, open a ticket), so a case can close without a human.
2. **Operations metrics are first-class.** Every response reports what happened (route, agents,
   tools, escalation) so we can measure **automation/containment rate, escalation rate, latency and
   cost per resolution** — the KPIs an AI Ops org runs on.
3. **Human-in-the-loop by design.** Low confidence, explicit request, sensitive topics or tool
   failures → Human Escalation Agent with a structured handoff (no dead ends).
4. **Production gates.** Guardrails + offline evaluation suite as a release gate ("no car passes a
   red light"), structured logs/traces for monitoring.
5. **Simple surface, deployable anywhere.** One endpoint, one container, runs offline for demos/tests.

## 3. Key insight that shapes the design

The suggested source (`getnet.net/en`) does **not** contain the facts needed to answer most
example questions (Get Clássica vs Get Smart, Pix, crediário, antecipação, payment link). The
brief explicitly says *"please, look for other sources"*. Therefore the knowledge base ingests
**the global site + the Brazilian product pages + the Brazilian FAQ**, and every chunk keeps its
`source_url` so answers can cite where they came from.

## 4. Scenario → expected route (golden set seed)

| # | Message | Expected route | Why |
|---|---|---|---|
| 1 | Difference between Get Clássica and Get Smart? | `knowledge` (RAG) | Product catalogue |
| 2 | Weather forecast in Porto Alegre tomorrow? | `knowledge` (web/weather tool) | General-purpose, external |
| 3 | When will yesterday's sales be deposited? | `support` | Needs the user's settlement data |
| 4 | Do I need a bank account to receive via Pix? | `knowledge` (RAG) | FAQ / product rule |
| 5 | Card machine won't connect to the internet | `support` → `knowledge` | User's terminal status + troubleshooting steps from FAQ |
| 6 | How does antecipação work with Getnet? | `knowledge` (RAG) | Product rule |
| 7 | Euro exchange rate today? | `knowledge` (web/FX tool) | General-purpose, real-time |
| 8 | Card machine showing a transaction decline error | `support` → `knowledge` | User's recent declined transactions + FAQ |
| 9 | How many installments with crediário? | `knowledge` (RAG) | Product rule |
| 10 | Can I sell through WhatsApp with the Payment Link? | `knowledge` (RAG) | Product rule |
