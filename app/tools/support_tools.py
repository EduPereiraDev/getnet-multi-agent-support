"""Customer Support tools over a merchant data repository (mock JSON behind an interface).

Each tool is a plain function + a JSON schema, so the same definitions serve the
Anthropic tool-use loop and the offline mode.
"""

import json
import uuid
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Callable

from app.config import DATA_DIR


class CustomerNotFound(LookupError):
    pass


@lru_cache
def _load() -> dict[str, Any]:
    return json.loads((DATA_DIR / "mock" / "customers.json").read_text(encoding="utf-8"))


def _customer(user_id: str) -> dict[str, Any]:
    data = _load().get(user_id)
    if data is None:
        raise CustomerNotFound(f"user_id '{user_id}' not found")
    return data


def get_customer_profile(user_id: str) -> dict[str, Any]:
    return _customer(user_id)["profile"]


def get_settlement_schedule(user_id: str, sale_date: str | None = None) -> dict[str, Any]:
    """Settlements (recebíveis) for a sale date (YYYY-MM-DD). Defaults to yesterday."""
    target = sale_date or (date.today() - timedelta(days=1)).isoformat()
    items = [s for s in _customer(user_id)["settlements"] if s["sale_date"] == target]
    if not items and sale_date is None:
        # Demo data is pinned to a fixed date; fall back to the most recent sale date.
        all_items = _customer(user_id)["settlements"]
        if all_items:
            target = max(s["sale_date"] for s in all_items)
            items = [s for s in all_items if s["sale_date"] == target]
    return {
        "sale_date": target,
        "plan": get_customer_profile(user_id)["plan"],
        "items": items,
        "total_net": round(sum(s["net"] for s in items), 2),
    }


def get_terminal_status(user_id: str, serial: str | None = None) -> dict[str, Any]:
    terminals = _customer(user_id)["terminals"]
    if serial:
        terminals = [t for t in terminals if t["serial"] == serial]
    return {"terminals": terminals}


def get_recent_transactions(user_id: str, status: str | None = None, limit: int = 10) -> dict[str, Any]:
    txs = _customer(user_id)["transactions"]
    if status:
        txs = [t for t in txs if t["status"] == status]
    return {"transactions": sorted(txs, key=lambda t: t["date"], reverse=True)[:limit]}


def create_support_ticket(user_id: str, category: str, summary: str) -> dict[str, Any]:
    _customer(user_id)
    return {
        "ticket_id": f"SUP-{uuid.uuid4().hex[:8].upper()}",
        "category": category,
        "summary": summary,
        "status": "open",
        "sla_hours": 24,
    }


ToolFn = Callable[..., dict[str, Any]]

SUPPORT_TOOLS: dict[str, tuple[ToolFn, dict[str, Any]]] = {
    "get_customer_profile": (
        get_customer_profile,
        {
            "description": "Get the merchant's profile: plan, settlement account, products, enabled features.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ),
    "get_settlement_schedule": (
        get_settlement_schedule,
        {
            "description": "Get when the merchant receives the money (settlements/recebíveis) for a sale date.",
            "input_schema": {
                "type": "object",
                "properties": {"sale_date": {"type": "string", "description": "YYYY-MM-DD; default yesterday"}},
                "additionalProperties": False,
            },
        },
    ),
    "get_terminal_status": (
        get_terminal_status,
        {
            "description": "Get status, connectivity, signal and battery of the merchant's card machines.",
            "input_schema": {
                "type": "object",
                "properties": {"serial": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    ),
    "get_recent_transactions": (
        get_recent_transactions,
        {
            "description": "List the merchant's recent transactions, optionally filtered by status (approved/declined).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["approved", "declined"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "additionalProperties": False,
            },
        },
    ),
    "create_support_ticket": (
        create_support_ticket,
        {
            "description": "Open a support ticket when the issue needs follow-up (e.g. technician, replacement).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["terminal", "settlement", "transaction", "other"]},
                    "summary": {"type": "string"},
                },
                "required": ["category", "summary"],
                "additionalProperties": False,
            },
        },
    ),
}


def run_support_tool(name: str, user_id: str, args: dict[str, Any]) -> dict[str, Any]:
    fn, _ = SUPPORT_TOOLS[name]
    return fn(user_id=user_id, **args)
