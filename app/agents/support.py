"""Customer Support Agent: resolves merchant-specific issues using the merchant's data via tools.

LLM mode runs a tool-use loop over SUPPORT_TOOLS; offline mode maps the intent to tools
deterministically and renders a templated answer with the merchant's real numbers.
"""

import logging
from typing import Any

from app.config import get_settings
from app.schemas import AgentContext, AgentResult, ToolCall
from app.tools.support_tools import SUPPORT_TOOLS, CustomerNotFound, get_customer_profile, run_support_tool

log = logging.getLogger(__name__)

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "terminal": ("connect", "internet", "offline", "wifi", "wi-fi", "signal", "chip", "conecta", "sinal"),
    "decline": ("decline", "declined", "error", "negad", "recusad", "erro"),
    "settlement": (
        "deposit", "deposited", "receive", "paid", "money", "sales", "recebíveis", "receber", "depósito",
    ),
}

ISSUER_CODES = {"51", "05", "14", "54", "57", "59", "61"}


def detect_intent(text: str) -> str | None:
    lowered = text.lower()
    for intent, words in INTENT_KEYWORDS.items():
        if any(w in lowered for w in words):
            return intent
    return None


def _brl(value: float) -> str:
    return f"R$ {value:,.2f}"


class SupportAgent:
    name = "support"

    def run(self, ctx: AgentContext) -> AgentResult:
        try:
            profile = get_customer_profile(ctx.user_id)
        except CustomerNotFound as exc:
            return AgentResult(
                agent=self.name,
                answer="I couldn't find your merchant account. I'm handing this to a human agent.",
                tool_calls=[ToolCall(tool="get_customer_profile", ok=False, error=str(exc))],
                confidence=0.2,
                needs_human=True,
            )
        if get_settings().resolved_mode == "llm":
            try:
                return self._run_llm(ctx)
            except Exception as exc:  # noqa: BLE001 - any LLM failure degrades to offline
                log.warning("support LLM path failed, falling back to offline: %s", exc)
        return self._run_offline(ctx, profile)

    # LLM path -----------------------------------------------------------------------------
    def _run_llm(self, ctx: AgentContext) -> AgentResult:
        from app.llm.client import get_llm, load_prompt

        tools = [{"name": n, **spec} for n, (_fn, spec) in SUPPORT_TOOLS.items()]
        user_text = (
            f"Merchant user_id: {ctx.user_id}\n"
            f"Focus for this step: {ctx.instruction or 'resolve the merchant request'}\n\n"
            f"Merchant message:\n{ctx.masked_message}"
        )
        answer, calls = get_llm().run_tools(
            load_prompt("support"),
            user_text,
            tools,
            lambda name, args: run_support_tool(name, ctx.user_id, args),
        )
        ok = any(c.ok for c in calls)
        return AgentResult(
            agent=self.name,
            answer=answer,
            tool_calls=calls,
            confidence=0.85 if ok else 0.5,
            needs_human=any(not c.ok for c in calls) and not ok,
        )

    # Offline path -------------------------------------------------------------------------
    def _call(self, ctx: AgentContext, calls: list[ToolCall], name: str, **args: Any) -> dict[str, Any] | None:
        try:
            result = run_support_tool(name, ctx.user_id, args)
        except Exception as exc:  # noqa: BLE001
            calls.append(ToolCall(tool=name, ok=False, args=args, error=str(exc)))
            return None
        calls.append(ToolCall(tool=name, ok=True, args=args))
        return result

    def _run_offline(self, ctx: AgentContext, profile: dict[str, Any]) -> AgentResult:
        intent = detect_intent(ctx.masked_message)
        calls: list[ToolCall] = []
        handlers = {"settlement": self._settlement, "terminal": self._terminal, "decline": self._decline}
        if intent in handlers:
            answer, data = handlers[intent](ctx, calls, profile)
            confidence = 0.8
        else:
            calls.append(ToolCall(tool="get_customer_profile", ok=True))
            answer = (
                f"Hi, {profile['business_name']}! I can see your account: plan \"{profile['plan']}\", "
                f"settlements to {profile['settlement_account']}, products: {', '.join(profile['products'])}.\n"
                "How can I help? I can check when you'll receive your sales, the status of your card "
                "machines, or why a transaction was declined."
            )
            data, confidence = {"profile": profile}, 0.5
        failed = any(not c.ok for c in calls)
        return AgentResult(
            agent=self.name,
            answer=answer,
            tool_calls=calls,
            confidence=0.3 if failed else confidence,
            needs_human=failed,
            data={"intent": intent, **data},
        )

    def _settlement(self, ctx: AgentContext, calls: list[ToolCall], profile: dict[str, Any]) -> tuple[str, dict]:
        res = self._call(ctx, calls, "get_settlement_schedule")
        if res is None:
            return "I couldn't load your settlement schedule right now. I'm handing this to a specialist.", {}
        if not res["items"]:
            answer = f"I found no settlements for sales on {res['sale_date']}."
            return answer, {"settlements": res}
        lines = [f"Here is when you'll receive the money from your sales on {res['sale_date']}:"]
        for item in res["items"]:
            lines.append(
                f"- {item['method'].capitalize()}: gross {_brl(item['gross'])}, net {_brl(item['net'])}, "
                f"expected on {item['expected_date']} ({item['status']})"
            )
        lines.append(f"Total net: {_brl(res['total_net'])}.")
        lines.append(
            f"Your plan is \"{res['plan']}\" and the money is deposited into your {profile['settlement_account']}."
        )
        return "\n".join(lines), {"settlements": res}

    def _terminal(self, ctx: AgentContext, calls: list[ToolCall], profile: dict[str, Any]) -> tuple[str, dict]:
        res = self._call(ctx, calls, "get_terminal_status")
        if res is None:
            return "I couldn't check your card machines right now. I'm handing this to a specialist.", {}
        offline = [t for t in res["terminals"] if t["status"] != "online"]
        if not offline:
            answer = (
                "All your card machines are online right now. If the problem persists, restart the machine "
                "and run a communication test from its menu."
            )
            return answer, {"terminals": res["terminals"]}
        lines: list[str] = []
        for t in offline:
            lines.append(
                f"Your {t['model']} (serial {t['serial']}) is {t['status']} since {t['last_seen']} "
                f"(connectivity: {t['connectivity']}, battery {t['battery_pct']}%)."
            )
            if "wifi" in t["connectivity"]:
                lines += [
                    "Try these steps:",
                    "1. Check that your router is on and other devices have internet.",
                    "2. Confirm the Wi-Fi network and password configured on the machine.",
                    "3. Restart the card machine and the router, then run a communication test.",
                ]
            else:
                lines += [
                    "Try these steps:",
                    "1. Turn the machine off, remove and reinsert the chip, then turn it on.",
                    "2. Wait for the 2G/3G signal indicator to appear.",
                    "3. Run a communication test from the machine's menu.",
                ]
        serials = ", ".join(t["serial"] for t in offline)
        ticket = self._call(
            ctx, calls, "create_support_ticket", category="terminal",
            summary=f"Card machine offline: {serials}. Merchant reports no internet connection.",
        )
        if ticket:
            lines.append(
                f"I opened ticket {ticket['ticket_id']} (SLA {ticket['sla_hours']}h) so our team can follow up. "
                "Your machine has lifetime maintenance: if it still won't connect, we'll arrange a replacement."
            )
        return "\n".join(lines), {"terminals": res["terminals"], "ticket": ticket}

    def _decline(self, ctx: AgentContext, calls: list[ToolCall], profile: dict[str, Any]) -> tuple[str, dict]:
        res = self._call(ctx, calls, "get_recent_transactions", status="declined")
        if res is None:
            return "I couldn't load your transactions right now. I'm handing this to a specialist.", {}
        txs = res["transactions"]
        if not txs:
            return "I found no recently declined transactions on your account.", {"declined": []}
        lines = ["I found these recently declined transactions:"]
        for tx in txs:
            lines.append(
                f"- {tx['id']}: {_brl(tx['amount'])} ({tx.get('brand') or tx['method']}) - "
                f"code {tx.get('decline_code', 'n/a')}: {tx.get('decline_reason', 'not informed')}"
            )
        codes = {tx.get("decline_code") for tx in txs}
        if "DUP" in codes:
            lines.append(
                "Code DUP: an identical sale (same card and amount) within 5 minutes is automatically "
                "cancelled as a duplicate. Wait 5 minutes or change the amount before trying again."
            )
        issuer = sorted(c for c in codes if c in ISSUER_CODES)
        if issuer:
            lines.append(
                f"Code {', '.join(issuer)}: declined by the card issuer (e.g. 51 = insufficient funds). "
                "Your machine is fine; the customer must contact their issuing bank or use another payment method."
            )
        return "\n".join(lines), {"declined": txs}
