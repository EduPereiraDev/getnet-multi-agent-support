"""Output guardrails: PII leakage masking and grounding checks on the final answer."""

import re
from dataclasses import dataclass, field

from app.guardrails.input import PII_PATTERNS
from app.schemas import AgentResult

# Stricter than input masking so protocol/transaction ids are not mistaken for PII: CPF/CNPJ only in
# their formatted form, card numbers only when they pass the Luhn check. Phone masking is skipped on
# purpose: Getnet support numbers (4002-4000, 0800-648-8000) must survive.
OUTPUT_PATTERNS = {
    "card": PII_PATTERNS["card"],
    "cnpj": re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"),
    "cpf": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    "email": PII_PATTERNS["email"],
}
UNGROUNDED_DISCLAIMER = "I couldn't confirm this in Getnet's official content — please check with support."
UNGROUNDED_PENALTY = 0.3


@dataclass
class OutputCheck:
    answer: str
    pii_masked: bool = False
    flags: list[str] = field(default_factory=list)
    confidence_penalty: float = 0.0


def has_content(answer: str) -> bool:
    """False for empty answers and skeleton placeholders like "[... pending implementation]"."""
    text = answer.strip()
    return bool(text) and "pending implementation" not in text


GENERAL_TOOLS = {"get_weather", "get_exchange_rate", "web_search"}


def _is_ungrounded(result: AgentResult) -> bool:
    # Only Getnet product claims need official grounding; general web-tool answers are judged on their own.
    return (
        result.agent == "knowledge"
        and has_content(result.answer)
        and not result.sources
        and not any(tc.ok for tc in result.tool_calls)
        and not any(tc.tool in GENERAL_TOOLS for tc in result.tool_calls)
    )


def _luhn(number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", number)][::-1]
    total = sum(d if i % 2 == 0 else (d * 2 - 9 if d > 4 else d * 2) for i, d in enumerate(digits))
    return total % 10 == 0


def check_output(answer: str, results: list[AgentResult]) -> OutputCheck:
    if not answer.strip():
        return OutputCheck(answer=answer, flags=["empty"], confidence_penalty=1.0)

    check = OutputCheck(answer=answer)
    for kind, pattern in OUTPUT_PATTERNS.items():
        def mask(match: re.Match[str], kind: str = kind) -> str:
            if kind == "card" and not _luhn(match.group()):
                return match.group()
            check.pii_masked = True
            return f"[{kind.upper()}_MASKED]"

        check.answer = pattern.sub(mask, check.answer)
    if check.pii_masked:
        check.flags.append("pii_leak")

    if any(_is_ungrounded(r) for r in results):
        check.flags.append("ungrounded")
        check.answer = f"{check.answer}\n\n{UNGROUNDED_DISCLAIMER}"
        check.confidence_penalty = UNGROUNDED_PENALTY
    return check
