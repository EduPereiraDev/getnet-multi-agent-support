"""Input guardrails: PII masking, prompt-injection and harmful-request detection."""

import re
from dataclasses import dataclass, field

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "cnpj": re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),
    "cpf": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b"),
}

INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous|prior|above) (instructions|prompts?)",
    r"ignore (todas )?as instru[cç][oõ]es",
    r"disregard (your|the) (rules|instructions|system prompt)",
    r"(reveal|show|print) (your|the) (system )?prompt",
    r"you are now (in )?(dan|developer mode|jailbreak)",
    r"act as (an? )?(unrestricted|unfiltered)",
]

HARMFUL_PATTERNS = [
    r"clon(e|ar|ing) (a |um )?(card|cart[aã]o)",
    r"(stolen|roubad[oa]s?) (card|cart[oõ]es|cart[aã]o)",
    r"bypass (the )?(fraud|antifraud|3ds)",
    r"burlar (o )?(antifraude|sistema)",
    r"lavagem de dinheiro|money laundering",
    r"\b(hack|invadir)\b",
]

_injection = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)
_harmful = re.compile("|".join(HARMFUL_PATTERNS), re.IGNORECASE)


@dataclass
class InputCheck:
    masked_message: str
    pii_found: list[str] = field(default_factory=list)
    blocked: bool = False
    reason: str | None = None


def mask_pii(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    for kind, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            found.append(kind)
            text = pattern.sub(f"[{kind.upper()}_MASKED]", text)
    return text, found


def check_input(message: str) -> InputCheck:
    masked, pii = mask_pii(message.strip())
    if _injection.search(message):
        return InputCheck(masked, pii, blocked=True, reason="prompt_injection")
    if _harmful.search(message):
        return InputCheck(masked, pii, blocked=True, reason="harmful_request")
    return InputCheck(masked, pii)
