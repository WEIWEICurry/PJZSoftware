"""Synthetic borrowing and lending, independently calculated balances and upgrades."""

import io
import sqlite3
import uuid
import zipfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pjz.accounting import Accounting
from pjz.storage import LedgerStore, inspect_backup, validate_database
from sqlalchemy import create_engine
from test_daily_ledger import account, send, summary
from test_daily_ledger import ledger as ledger


def loan(ledger, cash, action, amount, party=None, name=None, key=None, day="2026-01-10"):
    return send(
        ledger,
        "/loans",
        {
            "action": action,
            "cash_account_id": cash,
            "counterparty_id": party,
            "counterparty_name": name,
            "effective_date": day,
            "amount_fen": amount,
            "note": "Synthetic principal",
        },
        key=key,
    )


def balances(ledger):
    return {row["name"]: row["balance_fen"] for row in ledger[1].get("/api/v1/accounts").json()}


def test_four_actions_partial_returns_totals_retry_and_restore(ledger, tmp_path):
    store, client, _ = ledger
    cash = account(ledger, "Synthetic bank")
    key = str(uuid.uuid4())
    borrowed = loan(ledger, cash, "borrow", "100000", name="Synthetic person", key=key)
    assert borrowed.status_code == 200, borrowed.text
    assert (
        loan(ledger, cash, "borrow", "100000", name="Synthetic person", key=key).json()
        == borrowed.json()
    )
    debt = borrowed.json()["account_id"]
    assert loan(ledger, cash, "repay", "30000", party=debt).status_code == 200
    lent = loan(ledger, cash, "lend", "50000", name="Synthetic person")
    assert lent.status_code == 200, lent.text
    receivable = lent.json()["target_account_id"]
    assert loan(ledger, cash, "collect", "20000", party=receivable).status_code == 200
    assert balances(ledger) == {
        "Synthetic bank": "140000",
        "Synthetic person · 我欠": "70000",
        "Synthetic person · 欠我": "30000",
    }
    result = summary(ledger)
    assert {
        k: result[k]
        for k in (
            "income_fen",
            "expense_fen",
            "net_fen",
            "assets_fen",
            "receivable_fen",
            "debt_fen",
        )
    } == {
        "income_fen": "0",
        "expense_fen": "0",
        "net_fen": "100000",
        "assets_fen": "140000",
        "receivable_fen": "30000",
        "debt_fen": "70000",
    }
    snapshot = inspect_backup(store.backup())
    destination = tmp_path / "recovered"
    destination.mkdir()
    (destination / "ledger.sqlite3").write_bytes(snapshot)
    restored = LedgerStore(destination)
    try:
        assert {
            a["name"]: a["balance_fen"] for a in Accounting(restored.engine).accounts()
        } == balances(ledger)
    finally:
        restored.close()
    # Same direction and name reuses the object rather than duplicating the debt.
    assert loan(ledger, cash, "borrow", "100", name="Synthetic person").status_code == 200
    assert len(client.get("/api/v1/accounts").json()) == 3


def test_invalid_loan_rolls_back_new_object_and_overpayment(ledger):
    store, client, _ = ledger
    cash = account(ledger, "Synthetic bank", "1000")
    before = store.metadata()
    assert loan(ledger, cash, "lend", "1001", name="Synthetic failed").status_code == 422
    assert store.metadata() == before
    assert len(client.get("/api/v1/accounts").json()) == 1
    borrowed = loan(ledger, cash, "borrow", "100", name="Synthetic lender").json()
    debt = borrowed["account_id"]
    before_balances = balances(ledger)
    assert loan(ledger, cash, "repay", "101", party=debt).status_code == 422
    assert loan(ledger, cash, "collect", "1", party=debt).status_code == 422
    assert loan(ledger, debt, "borrow", "1", name="Synthetic invalid").status_code == 422
    assert loan(ledger, cash, "repay", "1", name="Synthetic absent").status_code == 422
    assert balances(ledger) == before_balances
    assert loan(ledger, cash, "repay", "100", party=debt).status_code == 200
    assert loan(ledger, cash, "repay", "1", party=debt).status_code == 422


def test_edit_or_void_lending_cannot_break_later_collection(ledger):
    _, client, _ = ledger
    cash = account(ledger, "Synthetic bank")
    lent = loan(ledger, cash, "lend", "50000", name="Synthetic borrower").json()
    receivable = lent["target_account_id"]
    assert loan(ledger, cash, "collect", "20000", party=receivable).status_code == 200
    before = balances(ledger)
    changed = {
        k: lent[k]
        for k in (
            "kind",
            "account_id",
            "target_account_id",
            "amount_fen",
            "fee_fen",
            "effective_date",
            "category_id",
            "original_event_id",
            "note",
            "revision",
        )
    }
    changed["amount_fen"] = "19999"
    assert send(ledger, "/events/" + lent["id"], changed, "PUT").status_code == 422
    assert send(ledger, "/events/" + lent["id"] + "/void", {"revision": 1}).status_code == 422
    assert balances(ledger) == before
    # Receivables cannot be used as an ordinary income account.
    category = client.get("/api/v1/categories").json()[0]["id"]
    assert (
        send(
            ledger,
            "/events",
            {
                "kind": "income",
                "account_id": receivable,
                "amount_fen": "1",
                "effective_date": "2026-01-10",
                "category_id": category,
            },
        ).status_code
        == 422
    )


def legacy_v2(path: Path):
    path.mkdir()
    database = path / "ledger.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE ledger (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "revision INTEGER NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO ledger VALUES (?,?,1,?)", (str(uuid.uuid4()), "Synthetic v2", "2026-01-01")
        )
        connection.execute("PRAGMA user_version=1")
    engine = create_engine("sqlite:///" + database.as_posix())
    config = Config()
    config.set_main_option("script_location", str(Path("backend/pjz/migrations").resolve()))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.stamp(config, "0001")
        command.upgrade(config, "0002")
    service = Accounting(engine)
    service.create_account(
        {
            "name": "Synthetic legacy debt",
            "kind": "liability",
            "opening_date": "2026-01-01",
            "opening_fen": "70000",
        },
        str(uuid.uuid4()),
    )
    engine.dispose()
    return database


def test_v2_migration_preserves_old_debt_and_valid_backup(tmp_path):
    path = tmp_path / "v2"
    legacy_v2(path)
    store = LedgerStore(path)
    try:
        accounts = Accounting(store.engine).accounts()
        assert accounts[0]["balance_fen"] == "70000"
        assert accounts[0]["kind"] == "liability"
        backups = list((path / "backups").glob("before-v4-*"))
        assert len(backups) == 1
        with zipfile.ZipFile(io.BytesIO(backups[0].read_bytes())) as archive:
            old = tmp_path / "old.sqlite3"
            old.write_bytes(archive.read("ledger.sqlite3"))
        validate_database(old)
        restored = LedgerStore(store.restore(backups[0].read_bytes()))
        try:
            assert Accounting(restored.engine).accounts()[0]["balance_fen"] == "70000"
            with restored.engine.connect() as connection:
                assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == 4
        finally:
            restored.close()
        with sqlite3.connect(old) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        Accounting(store.engine).create_account(
            {
                "name": "Synthetic receivable",
                "kind": "receivable",
                "opening_date": "2026-01-01",
                "opening_fen": "100",
            },
            str(uuid.uuid4()),
        )
        validate_database(store.path)
    finally:
        store.close()


def test_v2_failed_migration_rolls_back_and_keeps_backup(tmp_path, monkeypatch):
    path = tmp_path / "v2"
    database = legacy_v2(path)
    original = command.upgrade

    def fail_after_upgrade(config, revision):
        original(config, revision)
        raise RuntimeError("Synthetic migration failure")

    monkeypatch.setattr(command, "upgrade", fail_after_upgrade)
    with pytest.raises(RuntimeError):
        LedgerStore(path)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002"
        assert connection.execute("SELECT kind FROM accounts").fetchone()[0] == "liability"
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    assert list((path / "backups").glob("before-v4-*"))
