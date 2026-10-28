"""Independent synthetic distribution and unit-conversion accounting examples."""

import sqlite3
import uuid
from contextlib import closing

import pytest
from alembic import command
from alembic.config import Config
from pjz.accounting import Accounting
from pjz.investments import Investments
from pjz.storage import DataError, LedgerStore, inspect_backup, validate_database
from sqlalchemy import create_engine, text
from test_daily_ledger import account, event, send, summary
from test_daily_ledger import ledger as ledger
from test_investments import instrument, page, price, trade
from test_simple_loans import legacy_v2


def seed(ledger, cost="210000"):
    cash = account(ledger, "Synthetic distribution cash", "20000")
    asset = instrument(ledger, "000001", "fund", "FUND")
    result = trade(
        ledger,
        cash,
        asset,
        action="opening",
        quantity="1000",
        amount_fen="0",
        costs_fen="0",
        cost_basis_fen=cost,
    )
    assert result.status_code == 200, result.text
    assert price(ledger, asset, "2.1", "2026-01-19").status_code == 200
    return cash, asset, result.json()["id"]


def distribution(ledger, cash, asset, action="cash_dividend", **extra):
    return trade(
        ledger,
        cash,
        asset,
        action=action,
        **{
            "quantity": "0" if action == "cash_dividend" else "50",
            "amount_fen": "10000",
            "costs_fen": "0",
            "effective_date": "2026-01-20",
            **extra,
        },
    )


def test_cash_dividend_not_extra_profit_and_separate_receiving_account(ledger):
    cash, asset, _ = seed(ledger)
    receiving = account(ledger, "Synthetic receiving bank", "0")
    before = page(ledger)["net_fen"]
    result = distribution(ledger, cash, asset, cash_account_id=receiving)
    assert result.status_code == 200, result.text
    current = page(ledger)
    assert current["positions"][0]["value_fen"] is None
    assert current["positions"][0]["price_date"] == "2026-01-19"
    assert current["positions"][0]["valuation_required_from"] == "2026-01-20"
    assert current["positions"][0]["share_bps"] is None
    balances = {r["id"]: r["balance_fen"] for r in ledger[1].get("/api/v1/accounts").json()}
    assert balances == {cash: "20000", receiving: "10000"}
    assert price(ledger, asset, "2", "2026-01-20").status_code == 200
    current = page(ledger)
    assert current["cash_dividends_fen"] == "10000"
    assert current["reinvested_dividends_fen"] == "0"
    assert current["positions"][0]["cost_fen"] == "210000"
    assert current["positions"][0]["unrealized_fen"] == "-10000"
    assert current["total_profit_fen"] == "0"
    assert current["net_fen"] == before == "230000"
    assert summary(ledger)["income_fen"] == summary(ledger)["expense_fen"] == "0"
    assert (
        ledger[1]
        .get("/api/v1/reports?period=month&anchor=2026-01-20")
        .json()["current"]["income_fen"]
        == "0"
    )


@pytest.mark.parametrize(
    "fee,cost,profit,net", [("0", "220000", "0", "230000"), ("200", "220200", "-200", "229800")]
)
def test_reinvestment_cost_cash_and_total_profit(ledger, fee, cost, profit, net):
    cash, asset, _ = seed(ledger)
    assert distribution(ledger, cash, asset, "reinvest", costs_fen=fee).status_code == 200
    assert page(ledger)["positions"][0]["value_fen"] is None
    assert price(ledger, asset, "2", "2026-01-20").status_code == 200
    result = page(ledger)
    p = result["positions"][0]
    assert (p["quantity"], p["cost_fen"], p["value_fen"]) == ("1050", cost, "210000")
    assert result["reinvested_dividends_fen"] == "10000"
    assert result["total_profit_fen"] == profit
    assert result["net_fen"] == net
    assert summary(ledger)["expense_fen"] == "0"


def test_split_merge_cost_invariant_and_future_sale(ledger):
    cash, asset, _ = seed(ledger)
    response = distribution(
        ledger,
        cash,
        asset,
        "split",
        quantity="2000",
        amount_fen="0",
        split_from_quantity="1000",
        note="Synthetic confirmed 2:1 split",
    )
    assert response.status_code == 200, response.text
    assert page(ledger)["positions"][0]["value_fen"] is None
    assert price(ledger, asset, "1.05", "2026-01-20").status_code == 200
    p = page(ledger)["positions"][0]
    assert (p["quantity"], p["cost_fen"], p["value_fen"]) == ("2000", "210000", "210000")
    assert (
        distribution(
            ledger,
            cash,
            asset,
            "split",
            quantity="1000.00000001",
            amount_fen="0",
            split_from_quantity="2000",
            note="Synthetic confirmed merge",
            effective_date="2026-01-21",
        ).status_code
        == 200
    )
    assert price(ledger, asset, "2.1", "2026-01-21").status_code == 200
    assert page(ledger)["positions"][0]["quantity"] == "1000.00000001"
    assert page(ledger)["positions"][0]["cost_fen"] == "210000"
    assert (
        trade(
            ledger,
            cash,
            asset,
            action="sell",
            quantity="1000.00000001",
            amount_fen="210000",
            costs_fen="0",
            effective_date="2026-01-22",
        ).status_code
        == 200
    )
    assert page(ledger)["positions"][0]["cost_fen"] == "0"
    assert page(ledger)["total_profit_fen"] == "0"


def test_unknown_cost_survives_distribution_events(ledger):
    cash, asset, _ = seed(ledger, None)
    assert distribution(ledger, cash, asset).status_code == 200
    assert distribution(ledger, cash, asset, "reinvest").status_code == 200
    assert (
        distribution(
            ledger,
            cash,
            asset,
            "split",
            quantity="2100",
            amount_fen="0",
            split_from_quantity="1050",
            note="Synthetic split",
        ).status_code
        == 200
    )
    assert price(ledger, asset, "1", "2026-01-20").status_code == 200
    p = page(ledger)["positions"][0]
    assert p["cost_fen"] is None and p["unrealized_fen"] is None
    assert p["share_bps"] == "10000"
    assert page(ledger)["total_profit_fen"] is None
    assert (
        distribution(
            ledger, cash, asset, "sell", quantity="1", amount_fen="100", costs_fen="0"
        ).status_code
        == 422
    )


def test_delayed_dividend_after_liquidation(ledger):
    cash, asset, _ = seed(ledger)
    assert (
        trade(
            ledger,
            cash,
            asset,
            action="sell",
            quantity="1000",
            amount_fen="200000",
            costs_fen="0",
            effective_date="2026-01-20",
        ).status_code
        == 200
    )
    assert distribution(ledger, cash, asset, effective_date="2026-01-21").status_code == 200
    result = page(ledger)
    assert result["positions"][0]["quantity"] == "0"
    assert result["positions"][0]["value_fen"] == "0"
    assert result["missing_price_count"] == 0
    assert result["total_profit_fen"] == "0" and result["net_fen"] == "230000"


def test_void_reinvest_and_edit_split_fail_when_later_sale_depends_on_units(ledger):
    cash, asset, _ = seed(ledger)
    reinvest = distribution(ledger, cash, asset, "reinvest").json()["id"]
    split = distribution(
        ledger,
        cash,
        asset,
        "split",
        quantity="2100",
        amount_fen="0",
        split_from_quantity="1050",
        note="Synthetic split",
    ).json()["id"]
    sale = trade(
        ledger,
        cash,
        asset,
        action="sell",
        quantity="2000",
        amount_fen="200000",
        costs_fen="0",
        effective_date="2026-01-21",
    ).json()["id"]
    before = page(ledger)
    assert (
        send(ledger, f"/investments/trades/{reinvest}/void", {"revision": 1}).json()["error"][
            "code"
        ]
        == "INVESTMENT_SPLIT_MISMATCH"
    )
    response = send(ledger, f"/investments/trades/{split}/void", {"revision": 1})
    assert response.json()["error"]["event_id"] == sale
    assert page(ledger) == before
    payload = {
        "account_id": cash,
        "instrument_id": asset,
        "action": "split",
        "quantity": "1500",
        "split_from_quantity": "1050",
        "amount_fen": "0",
        "effective_date": "2026-01-20",
        "note": "Synthetic corrected split",
        "revision": 1,
    }
    assert send(ledger, f"/investments/trades/{split}", payload, "PUT").status_code == 422
    assert page(ledger) == before


def test_dividend_idempotency_revision_and_cash_rollback(ledger):
    cash, asset, _ = seed(ledger)
    receiving = account(ledger, "Synthetic zero recipient", "0")
    payload = {
        "account_id": cash,
        "instrument_id": asset,
        "cash_account_id": receiving,
        "action": "cash_dividend",
        "quantity": "0",
        "amount_fen": "10000",
        "effective_date": "2026-01-20",
    }
    key = str(uuid.uuid4())
    first = send(ledger, "/investments/trades", payload, key=key)
    assert first.status_code == 200
    assert send(ledger, "/investments/trades", payload, key=key).json() == first.json()
    identifier = first.json()["id"]
    event(ledger, receiving, "9000", effective_date="2026-01-21")
    before = page(ledger)
    assert (
        send(ledger, f"/investments/trades/{identifier}/void", {"revision": 1}).json()["error"][
            "code"
        ]
        == "INSUFFICIENT_BALANCE"
    )
    assert (
        send(
            ledger,
            f"/investments/trades/{identifier}",
            {**payload, "amount_fen": "8000", "revision": 1},
            "PUT",
        ).status_code
        == 422
    )
    assert page(ledger) == before
    assert (
        send(
            ledger,
            f"/investments/trades/{identifier}",
            {**payload, "amount_fen": "12000", "revision": 1},
            "PUT",
        ).status_code
        == 200
    )
    assert (
        send(
            ledger, f"/investments/trades/{identifier}", {**payload, "revision": 1}, "PUT"
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "action,extra",
    [
        ("cash_dividend", {"quantity": "1"}),
        ("cash_dividend", {"amount_fen": "0"}),
        ("cash_dividend", {"costs_fen": "1"}),
        ("reinvest", {"quantity": "0"}),
        ("reinvest", {"amount_fen": "0"}),
        (
            "split",
            {
                "quantity": "2000",
                "amount_fen": "0",
                "split_from_quantity": "900",
                "note": "Synthetic",
            },
        ),
        (
            "split",
            {"quantity": "2000", "amount_fen": "0", "split_from_quantity": "1000", "note": ""},
        ),
        (
            "split",
            {
                "quantity": "1000",
                "amount_fen": "0",
                "split_from_quantity": "1000",
                "note": "Synthetic",
            },
        ),
    ],
)
def test_distribution_invalid_combinations(ledger, action, extra):
    cash, asset, _ = seed(ledger)
    before = page(ledger)
    assert distribution(ledger, cash, asset, action, **extra).status_code == 422
    assert page(ledger) == before


def test_receiving_guards_and_history_requirements(ledger):
    cash, asset, _ = seed(ledger)
    debt = account(ledger, "Synthetic invalid recipient", "0", "liability")
    assert distribution(ledger, cash, asset, cash_account_id=debt).status_code == 422
    late = send(
        ledger,
        "/accounts",
        {
            "name": "Synthetic later recipient",
            "kind": "bank",
            "opening_date": "2026-02-01",
            "opening_fen": "0",
        },
    ).json()["id"]
    assert (
        distribution(ledger, cash, asset, cash_account_id=late).json()["error"]["code"]
        == "BEFORE_OPENING"
    )
    archived = account(ledger, "Synthetic archived recipient", "0")
    assert (
        send(
            ledger,
            "/accounts/" + archived,
            {"name": "Synthetic archived recipient", "archived": True, "revision": 1},
            "PATCH",
        ).status_code
        == 200
    )
    assert (
        distribution(ledger, cash, asset, cash_account_id=archived).json()["error"]["code"]
        == "ACCOUNT_ARCHIVED"
    )
    fresh = instrument(ledger, "000002", "fund", "FUND")
    assert (
        distribution(ledger, cash, fresh).json()["error"]["code"] == "INVESTMENT_HISTORY_REQUIRED"
    )
    stock = instrument(ledger)
    assert (
        trade(
            ledger,
            cash,
            stock,
            action="opening",
            quantity="100",
            amount_fen="0",
            costs_fen="0",
            cost_basis_fen="10000",
        ).status_code
        == 200
    )
    assert (
        distribution(ledger, cash, stock, "reinvest").json()["error"]["code"]
        == "INVESTMENT_REINVEST_FUND_ONLY"
    )


def test_distribution_backup_restore_and_recipient_deletion_protection(ledger):
    cash, asset, _ = seed(ledger)
    target = account(ledger, "Synthetic protected recipient", "0")
    distribution(ledger, cash, asset, cash_account_id=target)
    distribution(ledger, cash, asset, "reinvest", costs_fen="200")
    distribution(
        ledger,
        cash,
        asset,
        "split",
        quantity="2100",
        amount_fen="0",
        split_from_quantity="1050",
        note="Synthetic confirmed split",
    )
    price(ledger, asset, "1", "2026-01-20")
    original = Investments(Accounting(ledger[0].engine)).page()
    restored = LedgerStore(ledger[0].restore(ledger[0].backup()))
    try:
        assert Investments(Accounting(restored.engine)).page() == original
        validate_database(restored.path)
    finally:
        restored.close()
    event(ledger, target, "10000", effective_date="2026-01-21")
    assert (
        send(
            ledger,
            "/accounts/" + target,
            {"name": "Synthetic protected recipient", "archived": True, "revision": 1},
            "PATCH",
        ).status_code
        == 200
    )
    assert (
        send(ledger, "/accounts/" + target + "/delete-preview", {}).json()["error"]["code"]
        == "INVESTMENT_ACCOUNT_HAS_HISTORY"
    )


def test_v6_upgrade_failure_and_restore_preserve_legacy_trades(tmp_path, monkeypatch):
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
        command.upgrade(config, "0006")
        connection.commit()
    accounting = Accounting(engine)
    cash = accounting.create_account(
        {
            "name": "Synthetic legacy investment",
            "kind": "bank",
            "opening_date": "2026-01-01",
            "opening_fen": "100000",
        },
        str(uuid.uuid4()),
    )["id"]
    asset = Investments(accounting).instrument(
        {"name": "Synthetic legacy fund", "market": "FUND", "code": "000001", "kind": "fund"},
        str(uuid.uuid4()),
    )["id"]

    def legacy_trade(connection):
        row = accounting.insert_event(
            connection,
            {
                "kind": "investment",
                "account_id": cash,
                "effective_date": "2026-01-10",
                "amount_fen": "0",
                "fee_fen": "0",
                "target_account_id": None,
                "category_id": None,
                "original_event_id": None,
                "note": "",
            },
        )
        connection.execute(
            text("INSERT INTO investment_events VALUES (:id,:asset,'buy','100',10000,0,NULL)"),
            {"id": row["id"], "asset": asset},
        )
        return {"id": row["id"]}

    accounting.command(str(uuid.uuid4()), "synthetic_legacy_buy", {}, legacy_trade)
    engine.dispose()
    original = command.upgrade

    def fail(config, revision):
        original(config, revision)
        raise RuntimeError("Synthetic v7 upgrade failure")

    monkeypatch.setattr(command, "upgrade", fail)
    with pytest.raises(RuntimeError):
        LedgerStore(directory)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert "cash_account_id" not in {
            r[1] for r in connection.execute("PRAGMA table_info(investment_events)")
        }
    backup = next((directory / "backups").glob("before-v7-*"))
    assert inspect_backup(backup.read_bytes())
    monkeypatch.setattr(command, "upgrade", original)
    store = LedgerStore(directory)
    try:
        p = Investments(Accounting(store.engine)).page()["positions"][0]
        assert p["quantity"] == "100" and p["cost_fen"] == "10000"
        restored = LedgerStore(store.restore(backup.read_bytes()))
        try:
            assert (
                Investments(Accounting(restored.engine)).page()
                == Investments(Accounting(store.engine)).page()
            )
        finally:
            restored.close()
    finally:
        store.close()


def test_corrupt_cash_recipient_rejected(ledger):
    cash, asset, _ = seed(ledger)
    identifier = distribution(ledger, cash, asset).json()["id"]
    debt = account(ledger, "Synthetic corrupt target", "0", "liability")
    with ledger[0].engine.begin() as connection:
        connection.execute(
            text("UPDATE investment_events SET cash_account_id=:debt WHERE event_id=:id"),
            {"debt": debt, "id": identifier},
        )
    with pytest.raises(DataError):
        validate_database(ledger[0].path)


def test_same_day_old_price_requires_explicit_confirmation(ledger):
    cash, asset, _ = seed(ledger)
    assert price(ledger, asset, "2", "2026-01-20").status_code == 200
    distribution(ledger, cash, asset)
    assert page(ledger)["positions"][0]["value_fen"] is None
    assert price(ledger, asset, "2", "2026-01-20", revision=1).status_code == 200
    assert page(ledger)["positions"][0]["value_fen"] == "200000"
    distribution(
        ledger,
        cash,
        asset,
        "split",
        quantity="2000",
        amount_fen="0",
        split_from_quantity="1000",
        note="Synthetic same-day split",
    )
    assert page(ledger)["positions"][0]["value_fen"] is None
    assert price(ledger, asset, "1", "2026-01-20", revision=2).status_code == 200
    assert page(ledger)["positions"][0]["value_fen"] == "200000"
