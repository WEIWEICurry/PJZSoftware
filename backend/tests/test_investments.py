"""Synthetic investment acceptance with independent cash and cost expectations."""

import sqlite3
import uuid
from contextlib import closing
from decimal import Decimal

import pytest
from pjz.accounting import Accounting
from pjz.domain import RuleError
from pjz.investment_domain import Position, decimal_value, holding_share_bps
from pjz.investments import Investments
from pjz.storage import DataError, LedgerStore, inspect_backup, validate_database
from sqlalchemy import text
from test_daily_ledger import account, category, event, send, summary
from test_daily_ledger import ledger as ledger


def instrument(ledger, code="600001", kind="stock", market="SH"):
    response = send(
        ledger,
        "/investments/instruments",
        {
            "code": code,
            "name": "Synthetic " + code,
            "kind": kind,
            "market": market,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def trade(ledger, cash, stock, **extra):
    payload = {
        "account_id": cash,
        "instrument_id": stock,
        "action": "buy",
        "effective_date": "2026-01-10",
        "quantity": "100",
        "amount_fen": "100000",
        "costs_fen": "500",
        "cost_basis_fen": None,
        "amount_mode": "gross",
        "note": "",
        **extra,
    }
    return send(ledger, "/investments/trades", payload)


def page(ledger):
    response = ledger[1].get("/api/v1/investments")
    assert response.status_code == 200, response.text
    return response.json()


def price(ledger, stock, value="13", day="2026-01-20", revision=0, status="active"):
    return send(
        ledger,
        "/investments/valuations",
        {
            "instrument_id": stock,
            "price_date": day,
            "price": value,
            "revision": revision,
            "status": status,
        },
        "PUT",
    )


def test_independent_hand_example_full_cash_and_restore(ledger):
    cash = account(ledger, "Synthetic investment cash", "1000000", "securities")
    stock = instrument(ledger)
    assert trade(ledger, cash, stock).status_code == 200
    assert (
        trade(ledger, cash, stock, amount_fen="120000", effective_date="2026-01-11").status_code
        == 200
    )
    assert (
        trade(
            ledger,
            cash,
            stock,
            action="sell",
            quantity="50",
            amount_fen="65000",
            costs_fen="200",
            effective_date="2026-01-12",
        ).status_code
        == 200
    )
    assert price(ledger, stock).status_code == 200
    result = page(ledger)
    position = result["positions"][0]
    assert (
        position["quantity"],
        position["cost_fen"],
        position["realized_fen"],
        position["value_fen"],
        position["unrealized_fen"],
    ) == ("150", "165750", "9550", "195000", "29250")
    assert result["total_profit_fen"] == "38800"
    assert result["net_fen"] == "1038800"
    assert summary(ledger)["assets_fen"] == "843800"
    assert summary(ledger)["expense_fen"] == "0"
    assert summary(ledger)["income_fen"] == "0"
    assert ledger[1].get("/api/v1/events?start=2026-01-01&end=2026-01-31").json()["total"] == 1
    report = ledger[1].get("/api/v1/reports?period=month&anchor=2026-01-20").json()
    assert report["current"]["expense_fen"] == "0"
    store = ledger[0]
    payload = store.backup()
    assert inspect_backup(payload)
    restored = LedgerStore(store.restore(payload))
    try:
        assert (
            Investments(Accounting(restored.engine)).page()
            == Investments(Accounting(store.engine)).page()
        )
        validate_database(restored.path)
    finally:
        restored.close()


def test_net_fund_amount_and_fractional_cleanup(ledger):
    cash = account(ledger, "Synthetic fund cash", "100000")
    fund = instrument(ledger, "000001", "fund", "FUND")
    assert (
        trade(
            ledger,
            cash,
            fund,
            quantity="3.00000001",
            amount_fen="10001",
            costs_fen="1",
            amount_mode="net",
        ).status_code
        == 200
    )
    assert page(ledger)["positions"][0]["cost_fen"] == "10001"
    assert (
        trade(
            ledger,
            cash,
            fund,
            action="sell",
            quantity="1",
            amount_fen="4000",
            costs_fen="1",
            amount_mode="net",
        ).status_code
        == 200
    )
    # Allocated cost is 3334 fen; actual net proceeds 4000 fen.
    p = page(ledger)["positions"][0]
    assert (p["quantity"], p["cost_fen"], p["realized_fen"]) == ("2.00000001", "6667", "666")
    assert (
        trade(
            ledger,
            cash,
            fund,
            action="sell",
            quantity="2.00000001",
            amount_fen="8000",
            costs_fen="1",
            amount_mode="net",
        ).status_code
        == 200
    )
    p = page(ledger)["positions"][0]
    assert (p["quantity"], p["cost_fen"], p["realized_fen"], p["value_fen"]) == (
        "0",
        "0",
        "1999",
        "0",
    )
    assert page(ledger)["missing_price_count"] == 0
    assert summary(ledger)["assets_fen"] == "101999"


def test_unknown_initial_cost_is_not_zero_and_correctable(ledger):
    cash = account(ledger, "Synthetic initial", "50000")
    stock = instrument(ledger)
    response = trade(ledger, cash, stock, action="opening", amount_fen="0", costs_fen="0")
    identifier = response.json()["id"]
    result = page(ledger)
    assert result["positions"][0]["cost_fen"] is None
    assert result["net_fen"] is None
    assert summary(ledger)["assets_fen"] == "50000"
    assert price(ledger, stock, "10").status_code == 200
    result = page(ledger)
    assert result["known_value_fen"] == "100000"
    assert result["net_fen"] == "150000"
    assert result["total_profit_fen"] is None
    assert (
        trade(ledger, cash, stock, action="sell", quantity="1").json()["error"]["code"]
        == "INVESTMENT_COST_REQUIRED"
    )
    payload = {
        "account_id": cash,
        "instrument_id": stock,
        "action": "opening",
        "effective_date": "2026-01-10",
        "quantity": "100",
        "amount_fen": "0",
        "costs_fen": "0",
        "cost_basis_fen": "80000",
        "revision": 1,
    }
    assert send(ledger, "/investments/trades/" + identifier, payload, "PUT").status_code == 200
    assert page(ledger)["total_profit_fen"] == "20000"
    assert send(ledger, "/investments/trades/" + identifier, payload, "PUT").status_code == 409
    assert (
        trade(
            ledger, cash, stock, action="sell", quantity="1", amount_fen="1000", costs_fen="0"
        ).status_code
        == 200
    )


def test_historical_edits_void_and_cash_rollback(ledger):
    cash = account(ledger, "Synthetic chronology", "200000")
    stock = instrument(ledger)
    buy = trade(ledger, cash, stock).json()["id"]
    sell = trade(
        ledger,
        cash,
        stock,
        action="sell",
        quantity="80",
        amount_fen="90000",
        effective_date="2026-01-11",
    ).json()["id"]
    before = page(ledger)
    revision = ledger[0].metadata()["revision"]
    payload = {
        "account_id": cash,
        "instrument_id": stock,
        "action": "buy",
        "effective_date": "2026-01-10",
        "quantity": "50",
        "amount_fen": "100000",
        "costs_fen": "500",
        "revision": 1,
    }
    result = send(ledger, "/investments/trades/" + buy, payload, "PUT")
    assert result.json()["error"]["code"] == "INVESTMENT_INSUFFICIENT_QUANTITY"
    assert send(ledger, f"/investments/trades/{buy}/void", {"revision": 1}).status_code == 422
    assert page(ledger) == before
    assert ledger[0].metadata()["revision"] == revision
    assert send(ledger, f"/investments/trades/{sell}/void", {"revision": 1}).status_code == 200
    assert send(ledger, f"/investments/trades/{buy}/void", {"revision": 1}).status_code == 200
    assert page(ledger)["positions"] == []
    assert summary(ledger)["assets_fen"] == "200000"
    # Cash failures roll back the investment fact and its idempotency record.
    assert (
        trade(ledger, cash, stock, amount_fen="200000").json()["error"]["code"]
        == "INSUFFICIENT_BALANCE"
    )
    assert len(page(ledger)["trades"]) == 2


def test_accounts_independent_prices_revisions_void_and_budget(ledger):
    first = account(ledger, "Synthetic A", "200000")
    second = account(ledger, "Synthetic B", "300000")
    stock = instrument(ledger)
    trade(ledger, first, stock)
    trade(ledger, second, stock, amount_fen="120000")
    assert page(ledger)["missing_price_count"] == 2
    assert price(ledger, stock, "12").status_code == 200
    assert price(ledger, stock, "13", "2026-01-21").status_code == 200
    before = summary(ledger)
    assert price(ledger, stock, "14", "2026-01-21").status_code == 409
    assert price(ledger, stock, "14", "2026-01-21", 1).status_code == 200
    assert page(ledger)["positions"][0]["price"] == "14"
    assert price(ledger, stock, "14", "2026-01-21", 2, "void").status_code == 200
    assert {p["price"] for p in page(ledger)["positions"]} == {"12"}
    assert {p["cost_fen"] for p in page(ledger)["positions"]} == {"100500", "120500"}
    assert summary(ledger) == before
    cat = category(ledger, "餐饮")
    assert (
        send(
            ledger, f"/budgets/2026-01/{cat}", {"limit_fen": "10000", "revision": 0}, "PUT"
        ).status_code
        == 200
    )
    budgets = ledger[1].get("/api/v1/budgets/2026-01").json()
    assert next(b for b in budgets["items"] if b["category_id"] == cat)["used_fen"] == "0"


def test_duplicate_retries_and_ordinary_endpoint_rejects(ledger):
    cash = account(ledger, "Synthetic retry", "500000")
    stock = instrument(ledger)
    key = str(uuid.uuid4())
    payload = {
        "account_id": cash,
        "instrument_id": stock,
        "action": "buy",
        "effective_date": "2026-01-10",
        "quantity": "100",
        "amount_fen": "100000",
        "costs_fen": "0",
    }
    first = send(ledger, "/investments/trades", payload, key=key)
    assert first.status_code == 200
    assert send(ledger, "/investments/trades", payload, key=key).json() == first.json()
    assert len(page(ledger)["trades"]) == 1
    assert (
        send(ledger, "/investments/trades", {**payload, "quantity": "99"}, key=key).status_code
        == 409
    )
    identifier = first.json()["id"]
    assert (
        send(ledger, f"/events/{identifier}/void", {"revision": 1}).json()["error"]["code"]
        == "INVESTMENT_USE_WORKSPACE"
    )
    assert (
        trade(ledger, cash, stock, action="opening", amount_fen="0", costs_fen="0").json()["error"][
            "code"
        ]
        == "INVESTMENT_OPENING_ORDER"
    )


def test_archive_holding_guard_and_delete_history_guard(ledger):
    cash = account(ledger, "Synthetic holding guard", "0")
    stock = instrument(ledger)
    identifier = trade(
        ledger, cash, stock, action="opening", amount_fen="0", costs_fen="0", cost_basis_fen="100"
    ).json()["id"]
    payload = {"name": "Synthetic holding guard", "archived": True, "revision": 1}
    assert (
        send(ledger, "/accounts/" + cash, payload, "PATCH").json()["error"]["code"]
        == "INVESTMENT_ACCOUNT_HAS_HOLDINGS"
    )
    assert (
        send(ledger, f"/investments/trades/{identifier}/void", {"revision": 1}).status_code == 200
    )
    assert send(ledger, "/accounts/" + cash, payload, "PATCH").status_code == 200
    assert (
        send(ledger, "/accounts/" + cash + "/delete-preview", {}).json()["error"]["code"]
        == "INVESTMENT_ACCOUNT_HAS_HISTORY"
    )


@pytest.mark.parametrize(
    "value", ["0", "-1", "1e3", "NaN", "Infinity", "0.000000001", "1000000000000", "01", "1."]
)
def test_decimal_boundaries(value):
    with pytest.raises(RuleError):
        decimal_value(value)


def test_precision_and_last_sale_no_tail():
    p = Position()
    p.apply("buy", "0.00000003", 1, 0, None)
    assert p.apply("sell", "0.00000001", 1, 0, None) == 1
    assert (p.quantity, p.cost, p.realized) == (Decimal("0.00000002"), 1, 1)
    p.apply("sell", "0.00000002", 1, 0, None)
    assert (p.quantity, p.cost, p.realized) == (Decimal(0), 0, 1)


def test_cross_daily_cash_timeline_and_before_opening(ledger):
    cash = account(ledger, "Synthetic timeline", "0")
    bank = account(ledger, "Synthetic source", "200000")
    stock = instrument(ledger)
    event(ledger, bank, "100500", "transfer", target_account_id=cash, effective_date="2026-01-10")
    assert (
        trade(ledger, cash, stock, effective_date="2026-01-09").json()["error"]["code"]
        == "INSUFFICIENT_BALANCE"
    )
    assert trade(ledger, cash, stock).status_code == 200
    assert (
        trade(
            ledger,
            cash,
            stock,
            effective_date="2025-12-31",
            action="opening",
            amount_fen="0",
            costs_fen="0",
        ).status_code
        == 422
    )
    assert summary(ledger)["expense_fen"] == "0"


def test_v5_upgrade_failure_backup_then_success(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from test_simple_loans import legacy_v2

    directory = tmp_path / "legacy"
    database = legacy_v2(directory)
    engine = create_engine("sqlite:///" + database.as_posix())
    config = Config()
    config.set_main_option("script_location", "backend/pjz/migrations")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        config.attributes["connection"] = connection
        command.upgrade(config, "0005")
        connection.commit()
    engine.dispose()
    original = command.upgrade

    def fail(config, revision):
        original(config, revision)
        raise RuntimeError("Synthetic migration failure")

    monkeypatch.setattr(command, "upgrade", fail)
    with pytest.raises(RuntimeError):
        LedgerStore(directory)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='instruments'"
        ).fetchall()
    backups = list((directory / "backups").glob("before-v7-*"))
    assert len(backups) == 1
    assert inspect_backup(backups[0].read_bytes())
    monkeypatch.setattr(command, "upgrade", original)
    migrated = LedgerStore(directory)
    validate_database(migrated.path)
    migrated.close()


def test_tampered_cash_and_investment_relationship_rejected(ledger):
    cash = account(ledger, "Synthetic tamper", "200000")
    stock = instrument(ledger)
    identifier = trade(ledger, cash, stock).json()["id"]
    with ledger[0].engine.begin() as connection:
        connection.execute(
            text("UPDATE cash_entries SET delta_fen=0 WHERE event_id=:id"), {"id": identifier}
        )
    with pytest.raises(DataError):
        validate_database(ledger[0].path)

    with ledger[0].engine.begin() as connection:
        Accounting(ledger[0].engine).rebuild(connection)
        connection.execute(
            text("DELETE FROM investment_events WHERE event_id=:id"), {"id": identifier}
        )
    with pytest.raises(DataError):
        validate_database(ledger[0].path)


def test_price_overflow_rolls_back_and_stock_fraction_rejected(ledger):
    cash = account(ledger, "Synthetic overflow", "200000")
    stock = instrument(ledger)
    assert trade(ledger, cash, stock).status_code == 200
    before = page(ledger)
    assert price(ledger, stock, "999999999999").status_code == 422
    assert page(ledger) == before
    assert (
        trade(ledger, cash, stock, quantity="1.5").json()["error"]["code"]
        == "INVESTMENT_WHOLE_SHARES_REQUIRED"
    )


def test_successful_historical_recalculation_and_conflict_location(ledger):
    cash = account(ledger, "Synthetic recalculate", "200000")
    stock = instrument(ledger)
    buy = trade(ledger, cash, stock).json()["id"]
    sell = trade(
        ledger,
        cash,
        stock,
        action="sell",
        quantity="80",
        amount_fen="90000",
        effective_date="2026-01-11",
    ).json()["id"]
    payload = {
        "account_id": cash,
        "instrument_id": stock,
        "action": "buy",
        "effective_date": "2026-01-10",
        "quantity": "100",
        "amount_fen": "80000",
        "costs_fen": "500",
        "revision": 1,
    }
    assert send(ledger, "/investments/trades/" + buy, payload, "PUT").status_code == 200
    p = page(ledger)["positions"][0]
    assert (p["cost_fen"], p["realized_fen"]) == ("16100", "25100")
    assert summary(ledger)["assets_fen"] == "209000"
    response = send(
        ledger, "/investments/trades/" + buy, {**payload, "quantity": "10", "revision": 2}, "PUT"
    )
    assert response.json()["error"]["event_id"] == sell
    assert response.json()["error"]["effective_date"] == "2026-01-11"


def test_invalid_instrument_money_and_account_inputs(ledger):
    cash = account(ledger, "Synthetic invalid cash", "200000")
    debt = account(ledger, "Synthetic invalid debt", "1000", "liability")
    stock = instrument(ledger)
    assert trade(ledger, debt, stock).status_code == 422
    assert trade(ledger, cash, stock, quantity="1e2").status_code == 422
    assert trade(ledger, cash, stock, amount_fen="1.1").status_code == 422
    assert trade(ledger, cash, stock, action="sell", costs_fen="100001").status_code == 422
    assert (
        trade(
            ledger,
            cash,
            stock,
            action="opening",
            amount_fen="0",
            costs_fen="0",
            cost_basis_fen="-1",
        ).status_code
        == 422
    )
    assert (
        send(
            ledger,
            "/investments/instruments",
            {"name": "Synthetic bad", "market": "SH", "kind": "fund", "code": "000002"},
        ).status_code
        == 422
    )
    assert price(ledger, stock, "0").status_code == 422
    assert price(ledger, stock, "1", "2099-01-01").status_code == 422


@pytest.mark.parametrize(
    "value,total,complete,expected",
    [
        (1000, 4000, True, "2500"),
        (1, 3, True, "3333"),
        (1, 6, True, "1667"),
        (1, 20000, True, "1"),
        (0, 1000, True, "0"),
        (1000, 1000, True, "10000"),
        (None, 1000, True, None),
        (1000, 1000, False, None),
        (0, 0, True, None),
    ],
)
def test_holding_share_exact_rounding_and_unknown(value, total, complete, expected):
    assert holding_share_bps(value, total, complete) == expected


def test_portfolio_share_includes_all_accounts_not_cash_or_cost(ledger):
    first = account(ledger, "Synthetic share A", "1000000")
    second = account(ledger, "Synthetic share B", "9000000")
    stock = instrument(ledger)
    other = instrument(ledger, "600002")
    for cash, asset, basis in [
        (first, stock, "1000"),
        (second, other, None),
        (second, stock, "1000"),
    ]:
        assert (
            trade(
                ledger,
                cash,
                asset,
                action="opening",
                quantity="1",
                amount_fen="0",
                costs_fen="0",
                cost_basis_fen=basis,
            ).status_code
            == 200
        )
    assert price(ledger, stock, "10").status_code == 200
    assert all(p["share_bps"] is None for p in page(ledger)["positions"])
    assert price(ledger, other, "30").status_code == 200
    result = page(ledger)
    assert result["known_value_fen"] == "5000"
    shares = {(p["account_id"], p["instrument_id"]): p["share_bps"] for p in result["positions"]}
    assert shares == {(first, stock): "2000", (second, other): "6000", (second, stock): "2000"}
    assert price(ledger, other, "30", revision=1, status="void").status_code == 200
    assert all(p["share_bps"] is None for p in page(ledger)["positions"])


def test_holding_share_zero_total_closed_and_single_position(ledger):
    cash = account(ledger, "Synthetic zero share", "100000")
    stock = instrument(ledger)
    trade(ledger, cash, stock, quantity="1", amount_fen="1000", costs_fen="0")
    assert price(ledger, stock, "0.000001").status_code == 200
    assert page(ledger)["positions"][0]["value_fen"] == "0"
    assert page(ledger)["positions"][0]["share_bps"] is None
    assert price(ledger, stock, "10", revision=1).status_code == 200
    assert page(ledger)["positions"][0]["share_bps"] == "10000"
    trade(ledger, cash, stock, action="sell", quantity="1", amount_fen="1000", costs_fen="0")
    assert page(ledger)["positions"][0]["share_bps"] is None
    other = instrument(ledger, "600002")
    trade(ledger, cash, other, quantity="1", amount_fen="1000", costs_fen="0")
    assert price(ledger, other, "10").status_code == 200
    assert {p["instrument_id"]: p["share_bps"] for p in page(ledger)["positions"]} == {
        stock: "0",
        other: "10000",
    }
