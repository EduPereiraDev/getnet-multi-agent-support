"""Output guardrails: PII leakage masking and grounding checks on the final answer."""

from dataclasses import dataclass, field

from app.guardrails.input import PII_PATTERNS
from app.schemas import AgentResult

# Phone masking is skipped on purpose: Getnet support numbers (4002-4000, 0800-648-8000) must survive.
OUTPUT_PII_KINDS = ("card", "cnpj", "cpf", "email")
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


def _is_ungrounded(result: AgentResult) -> bool:
    return (
        result.agent == "knowledge"
        and has_content(result.answer)
        and not result.sources
        and not any(tc.ok for tc in result.tool_calls)
    )


def check_output(answer: str, results: list[AgentResult]) -> OutputCheck:
    if not answer.strip():
        return OutputCheck(answer=answer, flags=["empty"], confidence_penalty=1.0)

    check = OutputCheck(answer=answer)
    for kind in OUTPUT_PII_KINDS:
        pattern = PII_PATTERNS[kind]
        if pattern.search(check.answer):
            check.answer = pattern.sub(f"[{kind.upper()}_MASKED]", check.answer)
            check.pii_masked = True
    if check.pii_masked:
        check.flags.append("pii_leak")

    if any(_is_ungrounded(r) for r in results):
        check.flags.append("ungrounded")
        check.answer = f"{check.answer}\n\n{UNGROUNDED_DISCLAIMER}"
        check.confidence_penalty = UNGROUNDED_PENALTY
    return check
