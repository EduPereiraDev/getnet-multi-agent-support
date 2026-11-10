"""Router Agent: entry point that turns a message into an ordered execution plan.

Offline mode uses transparent keyword heuristics (PT + EN). LLM mode asks the model for a
`RoutePlan` via structured outputs and falls back to these heuristics on any error.
"""

import re

from app.config import get_settings
from app.llm.client import get_llm, load_prompt
from app.observability import log_event
from app.schemas import Route, RoutePlan, RouteStep

HUMAN_RE = re.compile(
    r"\b(human|humano|atendente|agent(e)? humano|falar com (algu[eé]m|uma pessoa)|ouvidoria|"
    r"procon|lawyer|advogado|cancel(ar)? (minha )?conta|chargeback|contesta[cç][aã]o)\b",
    re.IGNORECASE,
)

# Problems tied to *this* merchant's data → Customer Support.
SUPPORT_RE = re.compile(
    r"\b(my (card )?machine|my terminal|minha maquininha|my account|minha conta|yesterday'?s? sales|vendas de ontem|deposit(ed)?|deposita|"
    r"won'?t connect|n[aã]o conecta|offline|declin(e|ed)|recusad|negad|erro|error|ticket|chamado|"
    r"when will .* (money|paid)|quando (vou )?receb)\b",
    re.IGNORECASE,
)

# Getnet products/services → Knowledge (RAG).
GETNET_RE = re.compile(
    r"\b(getnet|get ?cl[aá]ssica|get ?smart|get ?mini|get ?tap|get ?conta|maquininha|card machine|pix|"
    r"payment link|link de pagamento|credi[aá]rio|antecipa[cç][aã]o|receivables|installments?|parcel|"
    r"taxa|fee|tef|split|e-?commerce|checkout|whatsapp|bank account|conta banc[aá]ria|empr[eé]stimo)\b",
    re.IGNORECASE,
)

# General-purpose information → Knowledge (web tools).
GENERAL_RE = re.compile(
    r"\b(weather|forecast|previs[aã]o|tempo em|clima|exchange rate|c[aâ]mbio|cota[cç][aã]o|euro|d[oó]lar|"
    r"news|not[ií]cia)\b",
    re.IGNORECASE,
)


def heuristic_plan(message: str) -> RoutePlan:
    text = message.lower()
    if HUMAN_RE.search(text):
        return RoutePlan(
            steps=[RouteStep(agent=Route.ESCALATION, instruction="User asked for a human / sensitive topic")],
            confidence=0.9,
            rationale="explicit human/sensitive request",
        )

    support = bool(SUPPORT_RE.search(text))
    getnet = bool(GETNET_RE.search(text))
    general = bool(GENERAL_RE.search(text))

    if support:
        steps = [RouteStep(agent=Route.SUPPORT, instruction="Use the merchant's data to diagnose/resolve")]
        # Operational issues also benefit from official troubleshooting content.
        if re.search(r"connect|conecta|internet|declin|recus|negad|erro|error", text):
            steps.append(RouteStep(agent=Route.KNOWLEDGE, instruction="Add official troubleshooting steps"))
        return RoutePlan(steps=steps, confidence=0.8, rationale="merchant-specific issue")
    if getnet:
        return RoutePlan(
            steps=[RouteStep(agent=Route.KNOWLEDGE, instruction="Answer from the Getnet knowledge base")],
            confidence=0.8,
            rationale="Getnet product/service question",
        )
    if general:
        return RoutePlan(
            steps=[RouteStep(agent=Route.KNOWLEDGE, instruction="General question: use web tools")],
            confidence=0.75,
            rationale="general-purpose question",
        )
    return RoutePlan(
        steps=[RouteStep(agent=Route.OUT_OF_SCOPE)],
        confidence=0.3,
        rationale="no known intent",
    )


class RouterAgent:
    name = "router"

    def plan(self, masked_message: str) -> RoutePlan:
        heuristic = heuristic_plan(masked_message)
        settings = get_settings()
        # Safety net: an explicit human/sensitive request always escalates, whatever the LLM says.
        if settings.resolved_mode == "llm" and heuristic.primary != Route.ESCALATION:
            try:
                plan = get_llm().structured(
                    load_prompt("router"), masked_message, RoutePlan, model=settings.router_model
                )
                if isinstance(plan, RoutePlan) and plan.steps:
                    return plan.model_copy(update={"rationale": f"llm: {plan.rationale}"})
            except Exception as exc:  # noqa: BLE001 - any LLM failure degrades to heuristics
                log_event("router.llm_fallback", error=repr(exc))
        return heuristic.model_copy(update={"rationale": f"heuristic: {heuristic.rationale}"})
