"""Synthetic read-only investment task and date-window acceptance."""

from datetime import date

from pjz.accounting import Accounting
from pjz.investment_todos import investment_todos
from pjz.investments import Investments
from test_daily_ledger import account, send
from test_daily_ledger import ledger as ledger
from test_investments import instrument, page, price, trade
from test_recurring import drafts, generate, setup_plan


def todos(ledger, day="2026-01-20"):
    return investment_todos(Investments(Accounting(ledger[0].engine)), date.fromisoformat(day))


def test_price_tasks_group_accounts_ignore_future_and_closed_and_seven_day_boundary(ledger):
    first = account(ledger, "Synthetic first", "1000000", "securities")
    second = account(ledger, "Synthetic second", "1000000", "securities")
    missing = instrument(ledger, "000001", "fund", "FUND")
    stale = instrument(ledger, "000002", "fund", "FUND")
    boundary = instrument(ledger, "000003", "fund", "FUND")
    closed = instrument(ledger, "000004", "fund", "FUND")
    unknown = instrument(ledger, "000005", "fund", "FUND")
    for cash, asset in [
        (first, missing),
        (second, missing),
        (first, stale),
        (first, boundary),
        (first, closed),
    ]:
        assert (
            trade(ledger, cash, asset, quantity="1", amount_fen="100", costs_fen="0").status_code
            == 200
        )
    assert (
        trade(
            ledger, first, closed, action="sell", quantity="1", amount_fen="100", costs_fen="0"
        ).status_code
        == 200
    )
    assert (
        trade(
            ledger, first, unknown, action="opening", quantity="5", amount_fen="0", costs_fen="0"
        ).status_code
        == 200
    )
    for asset, day in [
        (missing, "2026-01-25"),
        (stale, "2026-01-12"),
        (boundary, "2026-01-13"),
        (unknown, "2026-01-20"),
    ]:
        assert price(ledger, asset, "1", day).status_code == 200
    before, revision = page(ledger), ledger[0].metadata()["revision"]
    result = todos(ledger)
    assert result.revision == revision and result.as_of == "2026-01-20"
    assert [(t.kind, t.instrument_id) for t in result.items if t.kind == "missing_price"] == [
        ("missing_price", missing)
    ]
    assert "Synthetic first" in next(t.detail for t in result.items if t.kind == "missing_price")
    assert "Synthetic second" in next(t.detail for t in result.items if t.kind == "missing_price")
    assert [(t.kind, t.instrument_id) for t in result.items if t.kind == "stale_price"] == [
        ("stale_price", stale)
    ]
    assert [(t.account_id, t.instrument_id) for t in result.items if t.kind == "unknown_cost"] == [
        (first, unknown)
    ]
    assert page(ledger) == before and ledger[0].metadata()["revision"] == revision
    assert ledger[1].get("/api/v1/investments/todos").status_code == 200
    ledger[1].cookies.clear()
    assert ledger[1].get("/api/v1/investments/todos").status_code == 401


def test_distribution_invalid_price_becomes_missing_not_stale(ledger):
    cash = account(ledger, "Synthetic events", "100000", "securities")
    fund = instrument(ledger, "000001", "fund", "FUND")
    assert (
        trade(ledger, cash, fund, quantity="10", amount_fen="100", costs_fen="0").status_code == 200
    )
    assert price(ledger, fund, "1", "2026-01-10").status_code == 200
    assert (
        trade(
            ledger,
            cash,
            fund,
            action="split",
            effective_date="2026-01-15",
            quantity="20",
            amount_fen="0",
            costs_fen="0",
            split_from_quantity="10",
            note="Synthetic conversion",
        ).status_code
        == 200
    )
    result = todos(ledger)
    assert [t.kind for t in result.items] == ["missing_price"]
    assert result.items[0].required_from == "2026-01-15"


def test_paused_pending_kept_skipped_future_and_deleted_excluded(ledger):
    plan, cash, _ = setup_plan(ledger, cash_amount="0")
    generate(ledger, plan, "2026-01-01", "2026-01-03")
    pending = drafts(ledger, plan)
    assert (
        send(
            ledger,
            "/recurring/review",
            {"rows": [{"id": pending[0]["id"], "revision": 1, "decision": "skip"}]},
        ).status_code
        == 200
    )
    assert (
        send(ledger, f"/recurring/{plan['id']}/pause", {"revision": 1, "paused": True}).status_code
        == 200
    )
    result = todos(ledger, "2026-01-02")
    assert len(result.items) == 1
    item = result.items[0]
    assert item.count == 1 and item.start == "2026-01-02" and item.end == "2026-01-02"
    assert "已暂停" in item.detail
    archived = send(
        ledger,
        f"/accounts/{cash}",
        {"name": "Synthetic recurring cash", "archived": True, "revision": 1},
        "PATCH",
    )
    assert archived.status_code == 200, archived.text
    assert "已归档账户" in todos(ledger, "2026-01-02").items[0].detail
    assert send(ledger, f"/recurring/{plan['id']}/delete", {"revision": 2}).status_code == 200
    assert todos(ledger).items == []


def test_long_backlog_opens_bounded_oldest_range_and_empty_state(ledger):
    assert todos(ledger).items == []
    response = send(
        ledger,
        "/accounts",
        {"name": "Synthetic old", "kind": "bank", "opening_date": "2024-01-01", "opening_fen": "0"},
    )
    cash = response.json()["id"]
    asset = instrument(ledger, "000001", "fund", "FUND")
    response = send(
        ledger,
        "/recurring",
        {
            "name": "Synthetic old plan",
            "account_id": cash,
            "instrument_id": asset,
            "start_date": "2024-01-01",
            "frequency": "daily",
            "amount_fen": "1000",
            "costs_fen": "1",
        },
    )
    plan = response.json()
    generate(ledger, plan, "2024-01-01", "2024-01-02")
    item = todos(ledger).items[0]
    assert item.start == "2024-01-01" and item.end == "2024-12-31" and item.count == 2
    assert (date.fromisoformat(item.end) - date.fromisoformat(item.start)).days == 365
