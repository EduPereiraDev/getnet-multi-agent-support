import pytest

from app.tools.support_tools import (
    SUPPORT_TOOLS,
    CustomerNotFound,
    get_recent_transactions,
    get_settlement_schedule,
    get_terminal_status,
    run_support_tool,
)


def test_has_at_least_two_tools():
    assert len(SUPPORT_TOOLS) >= 2


def test_settlements_fallback_to_latest_sale_date():
    res = get_settlement_schedule("cliente1988")
    assert res["items"] and res["total_net"] > 0


def test_terminal_offline_detected():
    statuses = {t["status"] for t in get_terminal_status("cliente1988")["terminals"]}
    assert "offline" in statuses


def test_declined_transactions_filter():
    txs = get_recent_transactions("cliente1988", status="declined")["transactions"]
    assert txs and all(t["status"] == "declined" for t in txs)


def test_ticket_creation_via_dispatcher():
    res = run_support_tool("create_support_ticket", "cliente1988", {"category": "terminal", "summary": "offline"})
    assert res["ticket_id"].startswith("SUP-")


def test_unknown_customer():
    with pytest.raises(CustomerNotFound):
        get_terminal_status("nobody")
